"""Strain response from saved, explicitly branched Berry sources.

No native log parser, branch selection, solver submission or qualification.
Engineering-Voigt shear is gamma=2*epsilon; cells contain row lattice vectors.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np

from .modeling import read_model_artifacts
from .model_derivatives import _model_charge_state
from .berry import _read_input, _bool_input, _E_PER_BOHR2_TO_C_PER_M2
from .abacus import BOHR_PER_ANGSTROM
from .polarization import (
    _point_record, _model_geometry, _parent_identity_records, _periodic_close,
    _number, _integer_or_none, _METHOD_KEYS,
)

VOIGT_ORDER = ["xx", "yy", "zz", "yz", "xz", "xy"]
E_ANGSTROM2 = 1.602176634e-19 * 1e20
BOUNDARY = "clamped_ion_fixed_fractional"
RELAXED_BOUNDARIES = {
    "relaxed_ion_fixed_cell": "all_internal_dofs",
    "constrained_ion_fixed_cell": "selected_internal_dofs",
}


def _read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _same_path(first, second):
    return Path(first).resolve() == Path(second).resolve()


def _reduced_charge(P, Q, M, n, basis):
    """Explicit native modulus and branch declaration, never unwrap by proximity."""
    P = _number(P, name="polarization")
    Q = _number(Q, name="quantum")
    if Q <= 0 or isinstance(M, bool) or M not in (1, 2):
        raise ValueError("positive quantum and native quantum_factor 1 or 2 required")
    n = _integer_or_none(n, name="branch_integer")
    if basis is not None and (not isinstance(basis, str) or not basis.strip()):
        raise ValueError("branch_basis must be nonempty text or null")
    if n is None or basis is None:
        return None
    return M * (P / Q + n)


def _pair_response(pair, minus, plus, reference_cell, reference_volume):
    component = pair["voigt_component"]
    h = _number(plus["strain"], name="plus strain")
    hm = _number(minus["strain"], name="minus strain")
    if (component not in VOIGT_ORDER or minus["voigt_component"] != component
            or plus["voigt_component"] != component or h <= 0
            or not math.isclose(hm, -h, rel_tol=0, abs_tol=1e-12)):
        raise ValueError("central pair requires opposite equal nonzero strain in one Voigt component")
    slopes, contributions, missing = {}, {}, []
    reference_cell = np.asarray(reference_cell, dtype=float)
    for gdir in (1, 2, 3):
        key = str(gdir)
        slopes[key] = None
        contributions[key] = None
        for point in (minus, plus):
            if key not in point["directions"]:
                missing.append({"point_id": point["point_id"], "gdir": gdir, "reason": "missing_source"})
            elif point["directions"][key]["reduced_charge"] is None:
                missing.append({"point_id": point["point_id"], "gdir": gdir, "reason": "missing_branch_declaration"})
        if any(item["gdir"] == gdir for item in missing):
            continue
        slope = (plus["directions"][key]["reduced_charge"] - minus["directions"][key]["reduced_charge"]) / (2 * h)
        slopes[key] = slope
        contributions[key] = (E_ANGSTROM2 / reference_volume * slope * reference_cell[gdir - 1]).tolist()
    proper = improper = None
    if not missing:
        proper = (E_ANGSTROM2 / reference_volume * np.asarray(list(slopes.values())) @ reference_cell).tolist()
        cart = []
        for point in (minus, plus):
            reduced = np.asarray([point["directions"][str(g)]["reduced_charge"] for g in (1, 2, 3)])
            cart.append(E_ANGSTROM2 / point["volume_A3"] * reduced @ np.asarray(point["cell_angstrom"]))
        improper = ((cart[1] - cart[0]) / (2 * h)).tolist()
    return {
        **pair, "amplitude": h, "reduced_slopes_by_gdir": slopes,
        "proper_lattice_contributions_C_per_m2": contributions,
        "proper_e_C_per_m2": proper, "improper_dP_ds_C_per_m2": improper,
        "missing": missing, "status": "calculated_unqualified" if not missing else "unresolved",
        "units": {"strain": "dimensionless engineering Voigt", "reduced_slope": "dimensionless reduced charge per strain",
                  "proper_e_C_per_m2": "C/m^2", "improper_dP_ds_C_per_m2": "C/m^2"},
        "sources": {p["point_id"]: p["directions"] for p in (minus, plus)},
    }


def _study_binding(path, model, expected_id):
    study = _read(path)
    if study["study_id"] != expected_id or study["model"]["model_id"] != model.model_id or study["model"]["version"] != model.version:
        raise ValueError("Study/model identity differs from strain manifest")
    for key in ("path", "model_path"):
        if study["model"].get(key) is not None and not _same_path(Path(path).parent / study["model"][key], model.artifact_dir):
            raise ValueError("Study model path differs from strain model")
    # Parent Study may retain a project-relative import locator. Its selected
    # identity is bound above; the manifest supplies the actual artifact path.
    source_structure = study["model"].get("source_structure")
    if source_structure is not None and Path(source_structure).is_absolute() and not _same_path(
            source_structure, model.artifact_dir / model.metadata["structure_file"]):
        raise ValueError("Study source structure differs from strain model")
    return study


def _binding(record, manifest, point):
    binding = record["berry_strain_response"]
    if binding["schema"] != "mlcc.abacus-berry-strain-response-binding.v1":
        raise ValueError("producer binding schema differs")
    for key, expected in (("response_id", manifest["response_id"]), ("point_id", point["point_id"]),
                          ("parent_study_id", manifest["parent_study"]["study_id"]),
                          ("voigt_component", point["voigt_component"]), ("strain", point["strain"]),
                          ("strain_voigt", point["strain_voigt"]), ("mechanical_boundary", manifest["mechanical_boundary"]), ("charge_state", 0)):
        if binding[key] != expected:
            raise ValueError(f"producer {key} binding differs")
    if binding["parent_model"] != manifest["parent_model"]:
        raise ValueError("producer parent model binding differs")
    if manifest["mechanical_boundary"] in RELAXED_BOUNDARIES:
        for key in ("relaxation_scope", "pre_relax_model", "pre_relax_study", "relaxation_source", "ionic_constraints"):
            if binding[key] != point[key]:
                raise ValueError(f"producer relaxed {key} binding differs")
        if not _same_path(binding["relaxed_structure_bridge"], point["relaxed_structure_bridge"]):
            raise ValueError("producer relaxed bridge binding differs")


def _task_binding(task, task_file, manifest, point, kind, gdir):
    _binding(task, manifest, point)
    binding = task["berry_strain_response"]
    for key, expected in (("task_kind", kind), ("gdir", gdir),
                          ("child_study_id", point["child_study_id"]),
                          ("child_model_id", point["child_model_id"]),
                          ("child_model_version", point["child_model_version"]),
                          ("source_scf_task_id", point["scf_task_id"]), ("task_id", task["task_id"])):
        if binding[key] != expected:
            raise ValueError(f"producer task {key} binding differs")
    for observed, expected in ((binding["manifest_path"], manifest["manifest_path"]),
                               (binding["source_scf_task_path"], point["scf_task_path"]),
                               (binding["task_path"], task_file), (task["study_file"], point["study_path"])):
        if not _same_path(observed, expected):
            raise ValueError("producer task source/Study/manifest path binding differs")


def _relaxed_strain_point(point, manifest):
    # The producer's read-only gate owns root->strain->saved bridge validation.
    # Generic bridge Model/Study records intentionally have no response binding.
    from .berry_strain_response import _validate_relaxed_point

    if point["mechanical_boundary"] != manifest["mechanical_boundary"]:
        raise ValueError("relaxed point mechanical boundary differs from manifest")
    saved = _validate_relaxed_point(manifest, point)
    model, study = saved["model"], saved["study"]
    cell = model.atoms.cell.array
    scope = RELAXED_BOUNDARIES[manifest["mechanical_boundary"]]
    if saved["relaxation_scope"] != scope or point["relaxation_scope"] != scope:
        raise ValueError("relaxed point scope differs from mechanical boundary")
    gdirs = point["gdirs"]
    if len(gdirs) != len(set(gdirs)) or any(type(g) is not int or g not in (1, 2, 3) for g in gdirs):
        raise ValueError("point gdirs must be unique selected directions")
    return {
        "point_id": point["point_id"], "voigt_component": point["voigt_component"], "strain": point["strain"],
        "strain_voigt": point["strain_voigt"], "cell_angstrom": cell.tolist(),
        "volume_A3": abs(float(np.linalg.det(cell))),
        "model_id": model.model_id, "model_version": model.version, "model_path": point["model_path"],
        "study_id": study["study_id"], "study_path": point["study_path"],
        "case": {"case_id": study["case_id"], "case_role": study["case_role"], "fixture": bool(model.metadata["fixture"])},
        "mechanical_boundary": manifest["mechanical_boundary"], "relaxation_scope": scope,
        "pre_relax_model": point["pre_relax_model"], "pre_relax_study": point["pre_relax_study"],
        "relaxed_structure_bridge": point["relaxed_structure_bridge"],
        "relaxation_source": saved["relaxation_source"], "ionic_constraints": saved["ionic_constraints"],
        "directions": {},
    }


def _relaxed_pair_contract(points, manifest):
    from .berry_strain_response import _method_physical_signature

    if len(points) != 2:
        raise ValueError("relaxed strain response requires exactly two saved bridge points")
    first, second = points
    if (first["relaxation_source"]["task_id"] == second["relaxation_source"]["task_id"]
            or _same_path(first["relaxed_structure_bridge"], second["relaxed_structure_bridge"])):
        raise ValueError("relaxed pair requires distinct saved relaxation tasks and bridges")
    if (first["voigt_component"] != second["voigt_component"] or first["strain"] == 0
            or not math.isclose(first["strain"], -second["strain"], rel_tol=0, abs_tol=1e-12)):
        raise ValueError("relaxed points require equal opposite nonzero strain in one Voigt component")
    for key in ("schema", "coordinate_basis", "atom_ids", "move_flags", "relax_new"):
        if first["ionic_constraints"][key] != second["ionic_constraints"][key]:
            raise ValueError(f"relaxed pair ionic constraint {key} differs")
    signatures = []
    for point in points:
        source = point["relaxation_source"]
        method = _read(source["method_file"])
        signature = {key: method[key] for key in (*_METHOD_KEYS, "relax_method", "mixing_type", "symmetry", "ks_solver")}
        signature.update({key: source["relaxation"][key] for key in ("force_metric", "force_threshold_eV_per_A", "relax_new")})
        signatures.append(signature)
    if signatures[0] != signatures[1]:
        raise ValueError("relaxed pair physical method or relaxation controls differ")
    configured = _read(manifest["method_path"])
    if _method_physical_signature(configured) != _method_physical_signature(_read(first["relaxation_source"]["method_file"])):
        raise ValueError("relaxed strain Berry method differs from the saved relaxation physical method")


def _strain_point(point, manifest, parent):
    if manifest["mechanical_boundary"] in RELAXED_BOUNDARIES:
        return _relaxed_strain_point(point, manifest)
    model = read_model_artifacts(point["model_path"])
    if (model.model_id, model.version) != (point["child_model_id"], point["child_model_version"]):
        raise ValueError("child model identity differs from strain point")
    if (parent.model_id, parent.version) not in _parent_identity_records(model.metadata):
        raise ValueError("strain child does not declare common parent")
    if not model.atoms.pbc.all():
        raise ValueError("strain child must remain three-dimensional periodic")
    if not _same_path(model.metadata["parent_model"]["path"], parent.artifact_dir):
        raise ValueError("strain child parent model path differs")
    if _model_charge_state(model.metadata) != 0:
        raise ValueError("strain child charge must be neutral")
    study = _study_binding(point["study_path"], model, point["child_study_id"])
    _binding(model.metadata, manifest, point)
    _binding(study, manifest, point)
    if (study["derived_from"]["study_id"] != manifest["parent_study"]["study_id"]
            or not _same_path(study["derived_from"]["parent_study_file"], manifest["parent_study"]["study_path"])):
        raise ValueError("child Study common parent differs")
    derivation = model.metadata["derivation"]
    if derivation["mechanical_boundary"] != BOUNDARY or derivation["relaxation_status"] != "not_run":
        raise ValueError("child must retain unrelaxed fixed-fractional derivation")
    parent_study = _read(manifest["parent_study"]["study_path"])
    if study["case_id"] != parent_study["case_id"] or study["case_role"] != parent_study["case_role"]:
        raise ValueError("child Study case differs from parent")
    if bool(model.metadata["fixture"]) != bool(parent.metadata["fixture"]) or (study["case_role"] == "engineering_fixture") != bool(model.metadata["fixture"]):
        raise ValueError("Study/model fixture role differs")
    ids, elements, composition, fractions, cell = _model_geometry(model)
    pids, pelements, pcomposition, pfrac, pcell = _model_geometry(parent)
    if ids != pids or elements != pelements or composition != pcomposition:
        raise ValueError("strain child atom mapping/composition differs from parent")
    if any(not _periodic_close(fractions[str(i)], pfrac[str(i)]) for i in ids):
        raise ValueError("clamped-ion strain requires fixed fractional coordinates")
    component = point["voigt_component"]
    strain = _number(point["strain"], name="strain")
    if component not in VOIGT_ORDER or strain == 0:
        raise ValueError("explicit single nonzero Voigt component required")
    vector = np.zeros(6)
    vector[VOIGT_ORDER.index(component)] = strain
    epsilon = np.diag(vector[:3])
    epsilon[1, 2] = epsilon[2, 1] = vector[3] / 2
    epsilon[0, 2] = epsilon[2, 0] = vector[4] / 2
    epsilon[0, 1] = epsilon[1, 0] = vector[5] / 2
    F = np.eye(3) + epsilon
    if np.any(np.linalg.eigvalsh(F) <= 0):
        raise ValueError("strain deformation must preserve a positive cell")
    record = point["strain_record"]
    expected = np.asarray(pcell) @ F.T
    for observed, wanted, label in (
        (point["strain_voigt"], vector, "strain_voigt"),
        (record["strain_voigt"], vector, "record strain_voigt"),
        (record["F"], F, "F"), (record["reference_lattice_angstrom"], pcell, "reference cell"),
        (record["derived_lattice_angstrom"], expected, "derived cell"), (cell, expected, "actual child cell"),
    ):
        if not np.allclose(observed, wanted, atol=1e-8, rtol=0):
            raise ValueError(f"strain {label} differs from engineering-Voigt deformation")
    volume = abs(float(np.linalg.det(cell)))
    if (record["engineering_shear"] is not True or record["fractional_coordinates_fixed"] is not True
            or record["voigt_order"] != VOIGT_ORDER
            or not math.isclose(record["derived_volume_A3"], volume, rel_tol=1e-10, abs_tol=1e-8)
            or not math.isclose(record["reference_volume_A3"], manifest["reference_volume_A3"], rel_tol=1e-10, abs_tol=1e-8)):
        raise ValueError("strain convention/volume differs")
    gdirs = point["gdirs"]
    if len(gdirs) != len(set(gdirs)) or any(type(g) is not int or g not in (1, 2, 3) for g in gdirs):
        raise ValueError("point gdirs must be unique selected directions")
    return {"point_id": point["point_id"], "voigt_component": component, "strain": strain,
            "strain_voigt": vector.tolist(), "cell_angstrom": cell, "volume_A3": volume,
            "model_id": model.model_id, "model_version": model.version, "model_path": point["model_path"],
            "study_id": study["study_id"], "study_path": point["study_path"],
            "case": {"case_id": study["case_id"], "case_role": study["case_role"], "fixture": bool(model.metadata["fixture"])},
            "directions": {}}


def _saved_direction(source, point, manifest, geometry):
    gdir = source["gdir"]
    records = [t for t in point["nscf_tasks"] if t["gdir"] == gdir and _same_path(t["task_path"], source["task_file"])]
    if len(records) != 1 or gdir not in point["gdirs"]:
        raise ValueError("source must match one registered NSCF task/gdir")
    task = _read(source["task_file"])
    if task["task_id"] != records[0]["task_id"] or not _same_path(task["model_path"], point["model_path"]):
        raise ValueError("NSCF source task/model differs from registered point")
    _task_binding(task, source["task_file"], manifest, point, "nscf", gdir)
    single = _point_record(
        {**source, "path_coordinate": point["strain"]},
        request={"study_id": point["child_study_id"], "gdir": gdir}, previous=None,
    )
    if (single["model"]["model_id"], single["model"]["version"]) != (point["child_model_id"], point["child_model_version"]):
        raise ValueError("saved Berry model differs from strain point")
    if not _same_path(single["scf_job"]["task_file"], point["scf_task_path"]):
        raise ValueError("saved Berry SCF source differs from strain producer")
    scf = _read(point["scf_task_path"])
    _task_binding(scf, point["scf_task_path"], manifest, point, "reference_scf", None)
    if scf["task_id"] != point["scf_task_id"] or single["case"] != geometry["case"]:
        raise ValueError("saved SCF identity or Berry case differs from strain point")
    method = _read(single["source"]["method_file"])
    configured = _read(manifest["method_path"])
    for key in ("engine", "basis_type", "method_set", "kpoints", "element_order", "net_charge",
                "pseudopotential_ids", "pseudopotential_metadata", "pseudopotential_treatment"):
        if method[key] != configured[key]:
            raise ValueError(f"saved method {key} differs from manifest method")
    if method["abacus_version_target"] != configured["engine_version"]:
        raise ValueError("saved engine version differs from manifest method")
    for key, expected in configured["science"].items():
        if key != "suffix" and method[key] != expected:
            raise ValueError(f"saved physical method {key} differs from configured science")
    for key, expected in configured["parameters"].items():
        if method["parameters"][key] != expected:
            raise ValueError(f"saved numerical method {key} differs from configured parameters")
    if (method["engine"] != "abacus" or method["abacus_version_target"] != "3.10.1"
            or method["basis_type"] != "pw" or method["nspin"] != 1 or method["occupations"] != "fixed"
            or method["lspinorb"] or method["noncolin"] or method["net_charge"] != 0 or method.get("nelec_delta", 0) != 0):
        raise ValueError("strain response requires neutral PW nspin1 fixed occupations without SOC")
    result = _read(source["result_file"])
    native_valences = result["native_pp_valence_electrons"]
    filenames = {element: method["pseudopotentials"][element]["filename"] for element in method["element_order"]}
    if set(native_valences) != set(filenames.values()):
        raise ValueError("native PP filenames differ from method")
    valences = {element: native_valences[filename] for element, filename in filenames.items()}
    for element, value in valences.items():
        value = _number(value, name="native PP valence")
        if value <= 0 or not math.isclose(value, round(value), abs_tol=1e-8, rel_tol=0):
            raise ValueError("native PP valence must be a positive integer")
        if value != method["pseudopotential_metadata"][element]["valence_electrons_per_atom"]:
            raise ValueError("native PP valence differs from method")
    neutral_electrons = sum(valences[e] * n for e, n in single["geometry"]["composition"].items())
    if method.get("nelec", 0) not in (0, neutral_electrons):
        raise ValueError("explicit electron count is not neutral")
    for input_file in (single["source"]["source_files"]["INPUT"], single["source"]["source_files"]["native_INPUT"]):
        inputs = _read_input(Path(input_file), allow_blank_values=True)
        for flag in ("efield_flag", "dip_cor_flag", "gate_flag"):
            if flag in inputs and _bool_input(inputs[flag], key=flag):
                raise ValueError("strain response requires zero external electric field")
        if float(inputs.get("nelec_delta", 0)) != 0 or float(inputs.get("nelec", 0)) not in (0, neutral_electrons):
            raise ValueError("native INPUT electron count is not neutral")
    M = 1 if any(round(v) % 2 for v in valences.values()) else 2
    check = result["quantum_check"]
    if check["quantum_factor"] != M:
        raise ValueError("native quantum factor differs from PP parity")
    direction = np.asarray(geometry["cell_angstrom"])[gdir - 1]
    if (not math.isclose(check["rmod_bohr"], np.linalg.norm(direction) * BOHR_PER_ANGSTROM, abs_tol=1e-8, rel_tol=1e-9)
            or not math.isclose(check["cell_volume_bohr3"], geometry["volume_A3"] * BOHR_PER_ANGSTROM**3, abs_tol=1e-8, rel_tol=1e-9)):
        raise ValueError("saved quantum direction length/volume differs from strained cell")
    # Validate native Q with ABACUS 3.10.1's own historical conversion constants.
    # The contracted Cartesian/proper reconstruction separately uses SI e.
    expected_Q = (_E_PER_BOHR2_TO_C_PER_M2 / BOHR_PER_ANGSTROM**2
                  * M * np.linalg.norm(direction) / geometry["volume_A3"])
    Q = single["polarization"]["quantum_Q_C_per_m2"]
    # berry._require_fixed_decimal_places enforces seven decimals in 3.10.1.
    # Saved native row therefore has a half interval of 5e-8; the cell-derived
    # quantum_check retains full precision. Do not widen the printed interval.
    if not math.isclose(check["quantum_C_per_m2"], expected_Q, abs_tol=1e-9, rel_tol=1e-9) or not math.isclose(Q, expected_Q, abs_tol=5.1e-8, rel_tol=0):
        raise ValueError("saved quantum differs from strained cell/native modulus")
    reduced = _reduced_charge(single["polarization"]["representative_P_C_per_m2"], Q, M,
                              source.get("branch_integer"), source.get("branch_basis"))
    single["geometry"]["fixed_cell"] = False
    single["geometry"]["cell_constraint"] = manifest["mechanical_boundary"]
    single = {k: v for k, v in single.items() if not k.startswith("_")}
    return {**single["polarization"], "quantum_factor": M, "reduced_charge": reduced,
            "direction_lattice_vector_angstrom": direction.tolist(), "quantum_check": check,
            "source_record": single}, single["common_method"]


def analyze_polarization_strain(request_path):
    """Consume registered saved strained-cell Berry sources and explicit branches."""
    request = _read(request_path)
    if request["schema"] != "mlcc.polarization-strain-request.v1":
        raise ValueError("polarization strain request schema differs")
    manifest = _read(request["manifest_path"])
    if manifest["schema"] != "mlcc.abacus-berry-strain-response.v1" or request["response_id"] != manifest["response_id"]:
        raise ValueError("strain manifest schema/response identity differs")
    if not _same_path(request["manifest_path"], manifest["manifest_path"]):
        raise ValueError("manifest path differs from request")
    boundary = manifest["mechanical_boundary"]
    if boundary not in (BOUNDARY, *RELAXED_BOUNDARIES) or manifest["charge_state"] != 0:
        raise ValueError("neutral clamped or saved fixed-cell relaxed strain boundary required")
    if manifest["voigt_order"] != VOIGT_ORDER or manifest["engineering_shear"] is not True:
        raise ValueError("engineering-Voigt convention differs")
    parent = read_model_artifacts(manifest["parent_model"]["path"])
    if ((parent.model_id, parent.version) != (manifest["parent_model"]["model_id"], manifest["parent_model"]["version"])
            or _model_charge_state(parent.metadata) != 0 or manifest["parent_model"]["charge_state"] != 0):
        raise ValueError("parent model identity/charge differs")
    _study_binding(manifest["parent_study"]["study_path"], parent, manifest["parent_study"]["study_id"])
    cell = parent.atoms.cell.array
    volume = abs(float(np.linalg.det(cell)))
    if not parent.atoms.pbc.all() or not np.isfinite(cell).all() or volume <= 0:
        raise ValueError("strain reference requires finite three-dimensional periodic cell")
    if not np.allclose(cell, manifest["reference_lattice_angstrom"], atol=1e-8, rtol=0) or not math.isclose(volume, manifest["reference_volume_A3"], rel_tol=1e-10, abs_tol=1e-8):
        raise ValueError("manifest reference cell/volume differs from parent")
    originals, points = {}, {}
    model_identities = [(p["child_model_id"], p["child_model_version"]) for p in manifest["points"]]
    if len(model_identities) != len(set(model_identities)):
        raise ValueError("duplicate strain manifest child model identity")
    for field in ("child_study_id", "scf_task_id", "model_path", "study_path", "scf_task_path"):
        values = [str(Path(p[field]).resolve()) if field.endswith("path") else p[field] for p in manifest["points"]]
        if len(values) != len(set(values)):
            raise ValueError(f"duplicate strain manifest {field}")
    for point in manifest["points"]:
        pid = point["point_id"]
        if pid in points:
            raise ValueError("duplicate manifest point_id")
        originals[pid] = point
        points[pid] = _strain_point(point, manifest, parent)
    relaxed = boundary in RELAXED_BOUNDARIES
    if relaxed:
        _relaxed_pair_contract(list(points.values()), manifest)
    seen, signature, jobs = set(), None, []
    if relaxed:
        for point in points.values():
            source = point["relaxation_source"]
            jobs.append({"role": "relax", "point_id": point["point_id"], "runner": "slurm",
                         **{key: source[key] for key in ("task_id", "task_file", "result_file", "scheduler_job_id", "scheduler_state", "exit_code")}})
    for source in request["sources"]:
        pid, gdir = source["point_id"], source["gdir"]
        if pid not in points or type(gdir) is not int or gdir not in (1, 2, 3) or (pid, gdir) in seen:
            raise ValueError("unknown/duplicate strain point direction source")
        seen.add((pid, gdir))
        direction, method = _saved_direction(source, originals[pid], manifest, points[pid])
        if signature is not None and method != signature:
            raise ValueError("strain sources differ in common physical method/kpoints/charge")
        signature = method
        points[pid]["directions"][str(gdir)] = direction
        for role, job in (("nscf", direction["source_record"]["native_job"]), ("reference_scf", direction["source_record"]["scf_job"])):
            if relaxed:
                job = {**job, "role": role, "point_id": pid}
            if job not in jobs:
                jobs.append(job)
    pairs, pair_ids, missing = [], set(), []
    for pair in request["pairs"]:
        if pair["pair_id"] in pair_ids:
            raise ValueError("duplicate pair_id")
        pair_ids.add(pair["pair_id"])
        if pair["minus_point_id"] not in points or pair["plus_point_id"] not in points:
            raise ValueError("pair references unknown strain point")
        result = _pair_response(pair, points[pair["minus_point_id"]], points[pair["plus_point_id"]], cell, volume)
        pairs.append(result)
        missing.extend({"pair_id": pair["pair_id"], **item} for item in result["missing"])
    if not pairs:
        raise ValueError("at least one explicit strain pair required")
    scope = RELAXED_BOUNDARIES[boundary] if relaxed else None
    constraints = next(iter(points.values()))["ionic_constraints"] if relaxed else None
    response_kind = {BOUNDARY: "clamped_ion", "relaxed_ion_fixed_cell": "relaxed_ion",
                     "constrained_ion_fixed_cell": "constrained_ion"}[boundary]
    descriptor = {"relaxation_scope": scope, "status": "unresolved" if missing else "calculated_unqualified",
                  "pair_ids": [pair["pair_id"] for pair in pairs], "scientific_qualification": False}
    return {
        "schema": "mlcc.polarization-strain.v1", "response_id": request["response_id"],
        "parent": {"study_id": manifest["parent_study"]["study_id"], "study_file": manifest["parent_study"]["study_path"],
                   "model_id": parent.model_id, "model_version": parent.version, "model_path": str(parent.artifact_dir)},
        "manifest_path": request["manifest_path"], "mechanical_boundary": boundary,
        "electrical_boundary": "zero_external_field", "response_type": response_kind + "_stress_form_piezoelectric_e",
        "relaxation_scope": scope, "ionic_constraints": constraints,
        "voigt_order": VOIGT_ORDER, "engineering_shear": True,
        "reference_lattice_angstrom": cell.tolist(), "reference_volume_A3": volume,
        "points": list(points.values()), "pairs": pairs, "native_jobs": jobs, "missing": missing,
        "status": "unresolved" if missing else "calculated_unqualified",
        "evidence_kind": ("software_contract_only" if manifest.get("evidence_kind") == "software_contract_only"
                          else "saved_native_sources" if jobs else "unsubmitted_inputs_only"),
        "scientific_qualification": False, "production_qualification": False, "full_tensor_qualified": False,
        "native_strain_response_validated": False, "step_convergence_qualified": False,
        "relaxed_ion_response": descriptor if boundary == "relaxed_ion_fixed_cell" else None,
        "constrained_ion_response": descriptor if boundary == "constrained_ion_fixed_cell" else None,
        "stress_driven_d": None, "electrostriction": None,
        "out_of_scope": (["relaxed_ion"] if not relaxed else ["full_relaxed_ion"] if boundary == "constrained_ion_fixed_cell" else [])
                        + ["stress_driven_d", "electrostriction", "finite_field"],
    }
