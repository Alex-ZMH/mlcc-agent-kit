"""ABACUS 3.10.1 out_pot=2 scalar field and its own task provenance.

The cube contains electron potential energy in Ry, not a voltage for a
positive test charge. No alignment, mean subtraction or charge correction
is performed. A bare cube never establishes native execution provenance.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
import re
from typing import Any, Mapping

import numpy as np
from ase.data import atomic_numbers

from .abacus import BOHR_PER_ANGSTROM, _convergence_marker, _read_stru
from .electronic import _parse_input, _parse_input_kmesh
from .site_runner import _parse_scontrol_fields

RY_TO_EV = 13.605698
BOHR_TO_ANGSTROM = 1.0 / BOHR_PER_ANGSTROM
HEADER_HALF_QUANTUM_BOHR = 0.5e-6
_HEADER = re.compile(
    r"STEP:\s+(\d+)\s+Cubefile created from ABACUS\. Inner loop is z, followed by y and x"
    r"(?: \[software_contract_only\])?"
)
_OFF_FLAGS = ("efield_flag", "dip_cor_flag", "gate_flag", "imp_sol", "use_paw", "lspinorb", "noncolin")
_ON_FLAGS = ("vl_in_h", "vion_in_h", "vh_in_h")


def _number(token: str) -> float:
    value = float(token.replace("D", "E").replace("d", "e"))
    if not math.isfinite(value):
        raise ValueError("electrostatic cube contains a non-finite value")
    return value


def read_abacus_electrostatic_cube(path: str | Path) -> dict[str, Any]:
    """Read one scalar cube; preserve z-fast flat values and full grid basis."""
    path = Path(path).resolve()
    if path.name != "ElecStaticPot.cube":
        raise ValueError("expected ElecStaticPot.cube, not a density or total-potential file")
    lines = path.read_text(encoding="utf-8").splitlines()
    header = _HEADER.fullmatch(lines[0].strip())
    spin = re.fullmatch(r"([12])\s+\(nspin\)", lines[1].strip())
    if header is None or spin is None:
        raise ValueError("expected ABACUS 3.10.1 scalar electrostatic cube header without Fermi energy")
    origin_line = lines[2].split()
    if len(origin_line) != 4 or int(origin_line[0]) <= 0:
        raise ValueError("expected positive atom count and scalar cube origin")
    natoms = int(origin_line[0])
    origin = np.array([_number(value) for value in origin_line[1:]])
    shape, steps = [], []
    for line in lines[3:6]:
        fields = line.split()
        if len(fields) != 4 or int(fields[0]) <= 0:
            raise ValueError("expected positive Bohr grid dimensions and three step components")
        shape.append(int(fields[0]))
        steps.append([_number(value) for value in fields[1:]])
    steps_array = np.asarray(steps)
    if np.linalg.det(steps_array) == 0:
        raise ValueError("cube step vectors do not span a cell")
    cell = steps_array * np.asarray(shape)[:, None]
    atoms = []
    for line in lines[6:6 + natoms]:
        fields = line.split()
        if len(fields) != 5:
            raise ValueError("expected atomic number, valence charge and three Bohr coordinates")
        number = int(fields[0])
        if number <= 0 or number > 118:
            raise ValueError("unsupported cube atomic number")
        position = np.asarray([_number(value) for value in fields[2:]])
        atoms.append({"atomic_number": number, "valence_charge": _number(fields[1]),
                      "position_bohr": position.tolist(),
                      "position_angstrom": (position * BOHR_TO_ANGSTROM).tolist()})
    if len(atoms) != natoms:
        raise ValueError("cube atom header is incomplete")
    values = [_number(token) for line in lines[6 + natoms:] for token in line.split()]
    if len(values) != math.prod(shape):
        raise ValueError("cube scalar count differs from nx*ny*nz")
    software = "software_contract_only" in lines[0]
    return {
        "schema": "mlcc.abacus-electrostatic-cube.v1", "source_file": str(path),
        "comments": lines[:2], "step": int(header.group(1)), "nspin": int(spin.group(1)),
        "shape": shape, "origin_bohr": origin.tolist(), "step_vectors_bohr": steps,
        "cell_bohr": cell.tolist(), "origin_angstrom": (origin * BOHR_TO_ANGSTROM).tolist(),
        "step_vectors_angstrom": (steps_array * BOHR_TO_ANGSTROM).tolist(),
        "cell_angstrom": (cell * BOHR_TO_ANGSTROM).tolist(), "atoms": atoms,
        "values_Ry": values, "values_eV": [value * RY_TO_EV for value in values],
        "axis_order": "x_outer_y_middle_z_inner", "flat_index": "(ix*ny+iy)*nz+iz",
        "unit_conversion": {"Ry_to_eV": RY_TO_EV, "Bohr_to_angstrom": BOHR_TO_ANGSTROM,
                            "Bohr_constant_source": "mlcc.abacus.BOHR_PER_ANGSTROM reciprocal"},
        "print_precision": {"geometry_decimal_places": 6, "potential_scientific_decimal_places": 9,
                            "geometry_half_quantum_bohr": HEADER_HALF_QUANTUM_BOHR,
                            "cell_row_half_quantum_bohr": [n * HEADER_HALF_QUANTUM_BOHR for n in shape],
                            "potential_half_quantum_rule_Ry": "0.5 * 10**(printed_exponent - 9)"},
        "evidence_kind": "software_contract_only" if software else "unbound_native_format",
        "native_output_observed": False, "native_GPU_accepted": False,
        "scientific_qualification": False, "production_qualification": False,
    }


def _map_cube_atoms(cube: Mapping[str, Any], atom_map: Mapping[str, Any],
                    result: Mapping[str, Any], method: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Bind element-grouped cube rows through the persisted STRU map."""
    entries = sorted(atom_map["abacus_order"], key=lambda item: item["abacus_index"])
    count = len(cube["atoms"])
    if len(entries) != count or [item["abacus_index"] for item in entries] != list(range(count)):
        raise ValueError("cube atom count/order differs from STRU atom map")
    if sorted(item["source_index"] for item in entries) != list(range(count)):
        raise ValueError("STRU atom map source indices are not a permutation")
    source_ids = atom_map["source_atom_ids"]
    if len(set(source_ids)) != count or result["atom_ids"] != source_ids:
        raise ValueError("result atom IDs differ from STRU atom map")
    cell = np.asarray(result["final_atoms"]["cell_angstrom"])
    cell_tolerance = np.asarray(cube["shape"])[:, None] * HEADER_HALF_QUANTUM_BOHR * BOHR_TO_ANGSTROM + 1e-8
    if not np.all(np.abs(np.asarray(cube["cell_angstrom"]) - cell) <= cell_tolerance):
        raise ValueError("cube cell differs from fixed task cell beyond header print precision")
    mapped = []
    for atom, entry in zip(cube["atoms"], entries):
        index, element = entry["source_index"], entry["element"]
        if entry["atom_id"] != source_ids[index] or result["final_atoms"]["symbols"][index] != element:
            raise ValueError("cube atom mapping differs from result element/atom ID")
        if atom["atomic_number"] != atomic_numbers[element]:
            raise ValueError("cube atomic number differs from mapped element")
        valence = _number(str(method["pseudopotential_metadata"][element]["valence_electrons_per_atom"]))
        if abs(atom["valence_charge"] - valence) > 0.5e-6:
            raise ValueError("cube valence charge differs from pseudopotential metadata")
        delta = np.asarray(atom["position_angstrom"]) - result["final_atoms"]["positions_angstrom"][index]
        if not np.all(np.isfinite(delta)):
            raise ValueError("mapped source coordinates must be finite")
        fractional_delta = delta @ np.linalg.inv(cell)
        delta -= np.rint(fractional_delta) @ cell
        if np.any(np.abs(delta) > HEADER_HALF_QUANTUM_BOHR * BOHR_TO_ANGSTROM + 1e-8):
            raise ValueError("cube atom coordinates differ beyond header print precision")
        mapped.append({**atom, "abacus_index": entry["abacus_index"], "source_index": index,
                       "atom_id": entry["atom_id"], "element": element})
    return mapped


def read_abacus_electrostatic_task(task_path: str | Path) -> dict[str, Any]:
    """Read only this task's out_pot=2 artifact and saved native provenance."""
    directory = Path(task_path).resolve()
    if directory.is_file():
        directory = directory.parent
    task = json.loads((directory / "task.json").read_text(encoding="utf-8"))
    result = json.loads((directory / "result.json").read_text(encoding="utf-8"))
    method = json.loads((directory / "method.json").read_text(encoding="utf-8"))
    model_path = Path(task["model_path"]) / "model.json"
    model = json.loads(model_path.read_text(encoding="utf-8"))
    study_path = Path(task["study_file"])
    study = json.loads(study_path.read_text(encoding="utf-8"))
    atom_map_path = directory / "STRU.atom-map.json"
    atom_map = json.loads(atom_map_path.read_text(encoding="utf-8"))
    for record in (task, result, method, model, study):
        if record.get("evidence_kind") == "software_contract_only" or record.get("fixture_purpose") == "software_contract_only":
            raise ValueError("software contract fixture cannot establish native potential provenance")
    if (task["engine"], task["engine_version"], task["calculation"], task["runner"]) != ("abacus", "3.10.1", "scf", "slurm"):
        raise ValueError("electrostatic source requires ABACUS 3.10.1 Slurm SCF")
    if (task["status"], task["scheduler_state"], task["exit_code"]) != ("COMPLETED", "COMPLETED", "0:0"):
        raise ValueError("electrostatic source requires COMPLETED/0:0")
    scheduler_raw = task["scheduler_query_raw_stdout"]
    scheduler = _parse_scontrol_fields(scheduler_raw)
    if (scheduler["JobId"], scheduler["JobState"], scheduler["ExitCode"]) != (str(task["scheduler_job_id"]).split(";")[0], "COMPLETED", "0:0"):
        raise ValueError("saved actual Slurm observation differs from task")
    for key in ("task_id", "scheduler_job_id", "method_set"):
        if result[key] != task[key]:
            raise ValueError(f"result {key} differs from task")
    if result["electronic_converged"] is not True or result["stage"] != "scf":
        raise ValueError("saved result is not an electronically converged SCF")
    identity = (task["model_id"], task["model_version"])
    for record in (method, model, atom_map, study["model"]):
        if (record["model_id"], record["version"]) != identity:
            raise ValueError("method/model/Study/atom-map identity differs from task")
    if study["study_id"] != task["study_id"] or method["method_set"] != task["method_set"]:
        raise ValueError("Study or method identity differs from task")
    if (method["engine"], method["abacus_version_target"], method["basis_type"], method["stage"]) != ("abacus", "3.10.1", "pw", "scf"):
        raise ValueError("potential method must be ABACUS 3.10.1 PW SCF")
    if method["nspin"] not in (1, 2) or method["lspinorb"] is not False or method["noncolin"] is not False:
        raise ValueError("potential source requires non-SOC collinear nspin 1 or 2")
    if task["calculation_conditions"]["cell_constraint"] != "fixed_cell":
        raise ValueError("potential source requires fixed_cell")
    if method["output_control"] != {"out_pot": 2} or type(method["output_control"]["out_pot"]) is not int:
        raise ValueError("method did not request the explicit out_pot=2 contract")
    native = directory / f"OUT.{method['suffix']}"
    expected_artifact = {
        "schema": "mlcc.abacus-electrostatic-output.v1",
        "relative_path": f"OUT.{method['suffix']}/ElecStaticPot.cube",
        "kind": "local_ionic_plus_hartree", "value_unit": "Ry", "geometry_unit": "Bohr",
        "native_output_observed": False, "native_GPU_accepted": False,
    }
    if method["requested_artifacts"]["electrostatic_potential"] != expected_artifact or task["requested_artifacts"]["electrostatic_potential"] != expected_artifact:
        raise ValueError("task/method requested potential artifact differs from the source contract")
    if method["input_qualification"]["input_qualified"] is not True:
        raise ValueError("potential source requires saved NC input qualification")
    for element in method["element_order"]:
        if method["pseudopotential_metadata"][element]["type"] not in ("NC", "ONCV_NC"):
            raise ValueError("potential source supports norm-conserving pseudopotentials only")
    inputs = {"INPUT": _parse_input(directory / "INPUT"), "OUT.INPUT": _parse_input(native / "INPUT")}
    bool_values = {"0": False, "1": True, "false": False, "true": True}
    for label, parameters in inputs.items():
        if int(parameters["out_pot"]) != 2 or int(parameters["out_interval"]) != 1:
            raise ValueError(f"{label} does not request out_pot=2/out_interval=1")
        for key in _OFF_FLAGS:
            if bool_values[parameters[key].lower()] is not False:
                raise ValueError(f"{label} unsupported potential flag {key}")
        for key in _ON_FLAGS:
            if bool_values[parameters[key].lower()] is not True:
                raise ValueError(f"{label} missing potential component {key}")
        for key in ("basis_type", "device", "dft_functional", "ks_solver", "suffix"):
            if parameters[key].lower() != str(method[key]).lower():
                raise ValueError(f"{label} {key} differs from method")
        if parameters["calculation"] != "scf" or int(parameters["nspin"]) != method["nspin"]:
            raise ValueError(f"{label} stage or spin differs from method")
        for input_key, method_key in (("ecutwfc", "ecutwfc_Ry"), ("scf_thr", "scf_thr"),
                                      ("scf_nmax", "scf_nmax"), ("nbands", "nbands"),
                                      ("mixing_beta", "mixing_beta")):
            if not math.isclose(_number(parameters[input_key]), method["parameters"][method_key], rel_tol=1e-10, abs_tol=0):
                raise ValueError(f"{label} {input_key} differs from saved numerical method")
        if parameters["mixing_type"] != method["mixing_type"] or parameters["symmetry"] != str(method["symmetry"]):
            raise ValueError(f"{label} mixing/symmetry differs from method")
        expected_smearing = "fixed" if method["occupations"] == "fixed" else method["smearing_method"]
        if parameters["smearing_method"] != expected_smearing:
            raise ValueError(f"{label} occupations differ from method")
        q = method["net_charge"]
        if not math.isfinite(q) or isinstance(q, bool) or int(q) != q:
            raise ValueError("potential source requires an explicit integer method charge")
        if q != 0:
            if _number(parameters["nelec"]) != 0 or _number(parameters["nelec_delta"]) != -q:
                raise ValueError(f"{label} charge differs from method")
        elif ("nelec" in parameters and _number(parameters["nelec"]) != 0) or ("nelec_delta" in parameters and _number(parameters["nelec_delta"]) != 0):
            raise ValueError(f"{label} contradicts neutral method charge")
    mesh, shift = _parse_input_kmesh(directory / "KPT")
    if mesh != method["kpoints"] or shift != [0, 0, 0]:
        raise ValueError("task KPT differs from explicit method mesh/zero-shift contract")
    log_path = native / "running_scf.log"
    for name, expected in (("running_scf.log", log_path), ("INPUT", directory / "INPUT"), ("method.json", directory / "method.json"), ("STRU.atom-map.json", atom_map_path)):
        path = Path(result["source_files"][name])
        if not path.is_absolute():
            path = directory / path
        if path.resolve() != expected.resolve():
            raise ValueError(f"result source {name} is not bound to this task")
    native_log = log_path.read_text(encoding="utf-8")
    if re.search(r"\bABACUS\s+v3\.10\.1\b", native_log) is None:
        raise ValueError("native log does not establish ABACUS v3.10.1")
    if _convergence_marker(native_log, stage="scf")[0] is not True:
        raise ValueError("native SCF did not converge")
    if model["atom_ids"] != result["atom_ids"] or atom_map["source_atom_ids"] != result["atom_ids"]:
        raise ValueError("model/result/atom-map atom IDs differ")
    if not np.allclose(model["lattice_angstrom"], result["final_atoms"]["cell_angstrom"], rtol=0, atol=1e-7):
        raise ValueError("saved fixed-cell result differs from model")
    if [atom["element"] for atom in model["atoms"]] != result["final_atoms"]["symbols"]:
        raise ValueError("model/result atom elements differ")
    if not np.allclose([atom["cart_coords_angstrom"] for atom in model["atoms"]], result["final_atoms"]["positions_angstrom"], rtol=0, atol=1e-7):
        raise ValueError("fixed geometry result differs from model")
    stru = _read_stru(directory / "STRU", atom_map)
    if not np.allclose(stru.cell.array, result["final_atoms"]["cell_angstrom"], rtol=0, atol=1e-7) or not np.allclose(stru.positions, result["final_atoms"]["positions_angstrom"], rtol=0, atol=1e-7):
        raise ValueError("task STRU differs from saved fixed geometry")
    cube = read_abacus_electrostatic_cube(native / "ElecStaticPot.cube")
    if cube["evidence_kind"] == "software_contract_only":
        raise ValueError("mathematical cube cannot establish native potential provenance")
    if cube["nspin"] != method["nspin"] or cube["step"] != 0 or cube["origin_bohr"] != [0.0, 0.0, 0.0]:
        raise ValueError("native cube spin/SCF step/origin differs from the 3.10.1 source contract")
    mapped_atoms = _map_cube_atoms(cube, atom_map, result, method)
    return {
        "schema": "mlcc.abacus-electrostatic-potential.v1", "status": "native_source_bound_unaligned",
        "task_id": task["task_id"], "scheduler_job_id": task["scheduler_job_id"],
        "native_job": {"scheduler_fields": scheduler, "raw_scontrol": scheduler_raw},
        "study_id": study["study_id"], "model_id": identity[0], "model_version": identity[1],
        "method_set": method["method_set"], "method": method, "conditions": task["calculation_conditions"],
        "input_parameters": inputs, "atom_map": atom_map, "mapped_atoms": mapped_atoms,
        "kind": "local_ionic_plus_hartree", "value_unit": "Ry", "geometry_unit": "Bohr",
        "sign_convention": "electron_potential_energy", "includes_XC": False, "includes_nonlocal_pseudopotential": False,
        "energy_zero": {"Hartree_G0": "zero", "local_ionic_G0": "retained_pseudopotential_convention",
                        "total_mean_subtracted": False, "fermi_subtracted": False, "vacuum_subtracted": False},
        "cube": cube,
        "source_files": {"task.json": str(directory / "task.json"), "result.json": str(directory / "result.json"),
                         "method.json": str(directory / "method.json"), "model.json": str(model_path),
                         "Study": str(study_path), "STRU.atom-map.json": str(atom_map_path),
                         "INPUT": str(directory / "INPUT"), "OUT.INPUT": str(native / "INPUT"),
                         "KPT": str(directory / "KPT"), "STRU": str(directory / "STRU"),
                         "running_scf.log": str(log_path), "ElecStaticPot.cube": cube["source_file"]},
        "native_output_observed": True, "native_GPU_accepted": method["device"] == "gpu",
        "electronic_converged": True, "scientific_qualification": False, "production_qualification": False,
        "aligned_host_vbm_eV": None, "potential_alignment_eV": None,
        "FNV_eFNV_correction_eV": None, "charged_formation_energy_eV": None,
    }
