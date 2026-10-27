"""VASP input preparation and direct output parsing for MLCC H0.

POTCAR assembly is intentionally outside this module.  The authorized remote
site assembles it in the exact element order recorded in the POSCAR map.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from math import ceil
from pathlib import Path
from typing import Any, Literal, Sequence

import numpy as np
from ase import Atoms
from pymatgen.core import Structure
from pymatgen.io.ase import AseAtomsAdaptor
from pymatgen.io.vasp.inputs import Incar, Poscar
from pymatgen.io.vasp.outputs import Outcar, Vasprun

from .modeling import ModelArtifacts, read_model_artifacts


KBAR_TO_GPA = 0.1
STRESS_VOIGT_ORDER = ("xx", "yy", "zz", "yz", "xz", "xy")


def minimum_product_kmesh(atoms: Atoms, target_angstrom: float = 30.0) -> tuple[int, int, int]:
    """Smallest integer mesh meeting the user's a*x, b*y, c*z >= 30 Å rule."""
    return tuple(ceil(target_angstrom / length) for length in atoms.cell.lengths())


def _set_atom_ids(atoms: Atoms, ids: Sequence[int]) -> None:
    values = np.asarray([int(value) for value in ids], dtype=int)
    if len(values) != len(atoms):
        raise ValueError("atom_id count does not match atom count")
    if "atom_id" in atoms.arrays:
        atoms.set_array("atom_id", values)
    else:
        atoms.new_array("atom_id", values)


@dataclass(frozen=True)
class VaspParameters:
    """Explicit physical/numerical values written to INCAR/KPOINTS."""

    encut_eV: float
    kpoints: tuple[int, int, int]
    ismear: int
    sigma_eV: float
    ediff_eV: float
    ediffg_eV_per_A: float
    ispin: int
    initial_magnetic_moments: tuple[float, ...]
    nbands: int
    lwave: bool
    lcharg: bool
    lreal: bool
    istart: int
    icharg: int
    isym: int
    lorbit: int
    nsw: int
    ibrion: int
    isif: int
    prec: str
    algo: str
    nelm: int
    kpar: int = 1

    def incar(self, stage: Literal["scf", "relax"]) -> dict[str, Any]:
        if len(self.kpoints) != 3:
            raise ValueError("kpoints must contain exactly three integers")
        if stage == "relax" and self.nsw <= 0:
            raise ValueError("relax stage requires nsw > 0")
        if stage == "scf" and self.nsw != 0:
            raise ValueError("scf stage requires nsw == 0")
        values: dict[str, Any] = {
            "ENCUT": float(self.encut_eV),
            "ISMEAR": int(self.ismear),
            "SIGMA": float(self.sigma_eV),
            "EDIFF": float(self.ediff_eV),
            "EDIFFG": float(self.ediffg_eV_per_A),
            "ISPIN": int(self.ispin),
            "MAGMOM": " ".join(f"{float(value):.12g}" for value in self.initial_magnetic_moments),
            "NBANDS": int(self.nbands),
            "LWAVE": bool(self.lwave),
            "LCHARG": bool(self.lcharg),
            "LREAL": bool(self.lreal),
            "ISTART": int(self.istart),
            "ICHARG": int(self.icharg),
            "ISYM": int(self.isym),
            "LORBIT": int(self.lorbit),
            "PREC": self.prec,
            "ALGO": self.algo,
            "NELM": int(self.nelm),
            "KPAR": int(self.kpar),
        }
        if stage == "relax":
            values.update({"NSW": int(self.nsw), "IBRION": int(self.ibrion), "ISIF": int(self.isif)})
        else:
            values.update({"NSW": 0, "IBRION": -1, "ISIF": int(self.isif)})
        return values


@dataclass
class VaspPreparation:
    directory: Path
    stage: str
    model_id: str
    version: str
    poscar_atom_ids: list[int]
    element_order: list[str]
    files: dict[str, Path]

    def as_dict(self) -> dict[str, Any]:
        return {
            "directory": str(self.directory),
            "stage": self.stage,
            "model_id": self.model_id,
            "version": self.version,
            "poscar_atom_ids": self.poscar_atom_ids,
            "element_order": self.element_order,
            "files": {key: str(value) for key, value in self.files.items()},
        }


@dataclass
class VaspResult:
    e_fr_energy: float
    e_0_energy: float
    e_wo_entrp: float
    forces_eV_per_A: list[list[float]]
    stress_vasp_compression_positive_GPa: list[list[float]]
    stress_tensile_positive_GPa: list[list[float]]
    stress_voigt_vasp_compression_positive_GPa: list[float]
    stress_voigt_tensile_positive_GPa: list[float]
    atom_ids: list[int]
    final_atoms: Atoms
    electronic_converged: bool | None
    ionic_converged: bool | None
    magnetization: Any
    source_files: dict[str, str]
    stage: str | None

    @property
    def energy_eV(self) -> float:
        """Explicit compatibility alias for the VASP E0 energy."""

        return self.e_0_energy

    def as_dict(self) -> dict[str, Any]:
        return {
            "energy_eV": float(self.e_0_energy),
            "energy_default_definition": "VASP e_0_energy (sigma->0)",
            "e_fr_energy": float(self.e_fr_energy),
            "e_0_energy": float(self.e_0_energy),
            "e_wo_entrp": float(self.e_wo_entrp),
            "energy_unit": "eV",
            "energy_definitions": {
                "e_fr_energy": "VASP free energy TOTEN at the finite smearing",
                "e_wo_entrp": "VASP energy without entropy",
                "e_0_energy": "VASP energy extrapolated to sigma->0",
                "metal_force_stress_derivative": "finite-smearing free energy e_fr_energy",
            },
            "forces_eV_per_A": self.forces_eV_per_A,
            "stress_vasp_compression_positive_GPa": self.stress_vasp_compression_positive_GPa,
            "stress_tensile_positive_GPa": self.stress_tensile_positive_GPa,
            "stress_voigt_vasp_compression_positive_GPa": self.stress_voigt_vasp_compression_positive_GPa,
            "stress_voigt_tensile_positive_GPa": self.stress_voigt_tensile_positive_GPa,
            "stress_GPa": self.stress_vasp_compression_positive_GPa,
            "stress_voigt_GPa": self.stress_voigt_vasp_compression_positive_GPa,
            "stress_unit": "GPa",
            "stress_sign": {
                "vasp": "compression-positive",
                "tensile_positive": "negative of VASP value",
                "conversion": "stress_tensile_positive_GPa = -0.1 * raw VASP kBar",
            },
            "stress_voigt_order": list(STRESS_VOIGT_ORDER),
            "atom_ids": self.atom_ids,
            "final_atoms": {
                "symbols": self.final_atoms.get_chemical_symbols(),
                "positions_angstrom": self.final_atoms.get_positions().tolist(),
                "cell_angstrom": self.final_atoms.cell.array.tolist(),
                "pbc": [bool(value) for value in self.final_atoms.pbc],
            },
            "electronic_converged": self.electronic_converged,
            "ionic_converged": self.ionic_converged,
            "magnetization": self.magnetization,
            "source_files": self.source_files,
            "stage": self.stage,
        }


def _coerce_model(model: ModelArtifacts | Atoms | str | Path) -> tuple[Atoms, str, str]:
    if isinstance(model, ModelArtifacts):
        return model.atoms, model.model_id, model.version
    if isinstance(model, Atoms):
        return model, "unpersisted-model", "v001"
    loaded = read_model_artifacts(model)
    return loaded.atoms, loaded.model_id, loaded.version


def _group_indices(atoms: Atoms, element_order: Sequence[str]) -> list[int]:
    symbols = atoms.get_chemical_symbols()
    requested = [str(value) for value in element_order]
    if len(requested) != len(set(requested)):
        raise ValueError("element_order must not contain duplicates")
    if set(requested) != set(symbols):
        raise ValueError("element_order must list every model element exactly once")
    return [index for element in requested for index, symbol in enumerate(symbols) if symbol == element]


def _grouped_structure(atoms: Atoms, element_order: Sequence[str]) -> tuple[Structure, list[int], list[int]]:
    indices = _group_indices(atoms, element_order)
    ids = [int(value) for value in atoms.arrays["atom_id"][indices]]
    symbols = [atoms.get_chemical_symbols()[index] for index in indices]
    structure = Structure(
        lattice=atoms.cell.array,
        species=symbols,
        coords=atoms.get_scaled_positions(wrap=False)[indices],
        coords_are_cartesian=False,
        to_unit_cell=False,
        site_properties={"atom_id": ids},
    )
    return structure, indices, ids


def _write_kpoints(path: Path, kpoints: Sequence[int]) -> None:
    kx, ky, kz = (int(value) for value in kpoints)
    path.write_text(f"MLCC explicit Gamma mesh\n0\nGamma\n{kx} {ky} {kz}\n0 0 0\n", encoding="utf-8", newline="\n")


def prepare_vasp(
    model: ModelArtifacts | Atoms | str | Path,
    output_dir: str | Path,
    *,
    parameters: VaspParameters,
    stage: Literal["scf", "relax"],
    element_order: Sequence[str],
    comment: str = "MLCC H0 engineering fixture",
) -> VaspPreparation:
    """Write POSCAR/INCAR/KPOINTS and an explicit source-to-VASP map.

    This function never creates POTCAR.  The remote authorized environment
    must assemble POTCAR in ``element_order`` before submitting the task.
    """

    atoms, model_id, version = _coerce_model(model)
    if "atom_id" not in atoms.arrays:
        raise ValueError("prepare_vasp requires model atom_id values")
    if len(parameters.initial_magnetic_moments) != len(atoms):
        raise ValueError("initial_magnetic_moments count does not match atom count")
    structure, source_indices, poscar_ids = _grouped_structure(atoms, element_order)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)

    poscar_path = output / "POSCAR"
    poscar_path.write_text(Poscar(structure, comment=comment).get_str(), encoding="utf-8", newline="\n")
    incar_values = parameters.incar(stage)
    source_magmoms = np.asarray(parameters.initial_magnetic_moments, dtype=float)
    poscar_magmoms = source_magmoms[source_indices]
    incar_values["MAGMOM"] = " ".join(f"{float(value):.12g}" for value in poscar_magmoms)
    incar_path = output / "INCAR"
    incar_path.write_text(Incar(incar_values).get_str(), encoding="utf-8", newline="\n")
    kpoints_path = output / "KPOINTS"
    _write_kpoints(kpoints_path, parameters.kpoints)

    source_ids = [int(value) for value in atoms.arrays["atom_id"]]
    mapping = {
        "schema": "mlcc.vasp-atom-map.v1",
        "model_id": model_id,
        "version": version,
        "source_atom_ids": source_ids,
        "element_order": [str(value) for value in element_order],
        "poscar_order": [
            {
                "poscar_index": poscar_index,
                "source_index": source_index,
                "atom_id": int(atoms.arrays["atom_id"][source_index]),
                "element": atoms.get_chemical_symbols()[source_index],
            }
            for poscar_index, source_index in enumerate(source_indices)
        ],
    }
    map_path = output / "POSCAR.atom-map.json"
    map_path.write_text(json.dumps(mapping, indent=2) + "\n", encoding="utf-8")
    method = {
        "schema": "mlcc.method.v1",
        "engine": "vasp",
        "stage": stage,
        "model_id": model_id,
        "version": version,
        "element_order": [str(value) for value in element_order],
        "parameters": incar_values,
        "kpoints": [int(value) for value in parameters.kpoints],
        "potcar": {
            "assembly": "remote_authorized_site",
            "required_element_order": [str(value) for value in element_order],
            "included_in_bundle": False,
        },
        "stress_convention": {
            "unit_input": "kBar as printed by VASP",
            "unit_output": "GPa",
            "vasp_sign": "compression-positive",
            "tensile_positive": "negative of the VASP value",
            "tensile_conversion": "-0.1 * raw VASP kBar",
            "voigt_order": list(STRESS_VOIGT_ORDER),
        },
    }
    method_path = output / "method.json"
    method_path.write_text(json.dumps(method, indent=2) + "\n", encoding="utf-8")
    files = {
        "POSCAR": poscar_path,
        "INCAR": incar_path,
        "KPOINTS": kpoints_path,
        "POSCAR.atom-map.json": map_path,
        "method.json": method_path,
    }
    return VaspPreparation(output, stage, model_id, version, poscar_ids, [str(v) for v in element_order], files)


def read_poscar_with_mapping(
    poscar_path: str | Path,
    mapping_path: str | Path | None = None,
) -> Atoms:
    """Read a POSCAR and restore source ``atom_id`` values from its map."""

    poscar_file = Path(poscar_path)
    mapping_file = Path(mapping_path) if mapping_path is not None else poscar_file.with_name("POSCAR.atom-map.json")
    mapping = json.loads(mapping_file.read_text(encoding="utf-8"))
    poscar = Poscar.from_file(str(poscar_file), check_for_potcar=False)
    atoms = AseAtomsAdaptor().get_atoms(poscar.structure)
    entries = sorted(mapping["poscar_order"], key=lambda item: int(item["poscar_index"]))
    if len(entries) != len(atoms):
        raise ValueError("POSCAR atom map count does not match POSCAR")
    ids = [int(item["atom_id"]) for item in entries]
    _set_atom_ids(atoms, ids)
    atoms.info["element_order"] = [str(value) for value in mapping["element_order"]]
    return atoms


def _stress_matrix(values: Any) -> np.ndarray:
    raw = np.asarray(values, dtype=float)
    if raw.shape == (3, 3):
        return raw
    if raw.shape == (6,):
        xx, yy, zz, xy, yz, xz = (float(value) for value in raw)
        return np.array([[xx, xy, xz], [xy, yy, yz], [xz, yz, zz]], dtype=float)
    raise ValueError(f"VASP stress must be a 3x3 tensor or six components, got {raw.shape}")


def _stress_outputs(
    values: Any,
) -> tuple[list[list[float]], list[list[float]], list[float], list[float]]:
    """Convert raw VASP kBar stress to both declared sign conventions."""

    compression_positive = _stress_matrix(values) * KBAR_TO_GPA
    tensile_positive = -compression_positive
    compression_voigt = [
        float(compression_positive[0, 0]),
        float(compression_positive[1, 1]),
        float(compression_positive[2, 2]),
        float(compression_positive[1, 2]),
        float(compression_positive[0, 2]),
        float(compression_positive[0, 1]),
    ]
    tensile_voigt = [-value for value in compression_voigt]
    return compression_positive.tolist(), tensile_positive.tolist(), compression_voigt, tensile_voigt


def _ordered_atoms(atoms: Atoms, source_atom_ids: Sequence[int]) -> Atoms:
    current = [int(value) for value in atoms.arrays["atom_id"]]
    positions = [current.index(int(atom_id)) for atom_id in source_atom_ids]
    reordered = atoms[positions]
    _set_atom_ids(reordered, source_atom_ids)
    return reordered


def parse_vasp_outputs(
    task_dir: str | Path,
    *,
    poscar_path: str | Path | None = None,
    mapping_path: str | Path | None = None,
    stage: Literal["scf", "relax"] | None = None,
) -> VaspResult:
    """Parse real VASP output files and return source-order scientific data.

    Energies are the three VASP ionic-step values in eV.  Forces are
    eV/Angstrom.  Stress is returned both in VASP's compression-positive
    convention and as tensile-positive ``-0.1 * raw_kBar`` in GPa.  The
    six-value order is ``xx, yy, zz, yz, xz, xy``.  A static SCF has no ionic
    convergence condition and therefore returns ``ionic_converged=None``.

    This is a direct adapter for the selected pymatgen version.  It does not
    use OUTCAR as an energy/force/stress fallback and does not catch missing
    XML fields; missing fields therefore retain pymatgen's original error.
    """

    directory = Path(task_dir)
    vasprun_path = directory / "vasprun.xml"
    outcar_path = directory / "OUTCAR"
    contcar_path = directory / "CONTCAR"
    for path in (vasprun_path, outcar_path, contcar_path):
        if not path.exists():
            raise FileNotFoundError(path)
    poscar_file = Path(poscar_path) if poscar_path is not None else directory / "POSCAR"
    mapping_file = Path(mapping_path) if mapping_path is not None else directory / "POSCAR.atom-map.json"
    source_atoms_poscar = read_poscar_with_mapping(poscar_file, mapping_file)
    final_atoms_poscar = read_poscar_with_mapping(contcar_path, mapping_file)
    mapping = json.loads(mapping_file.read_text(encoding="utf-8"))
    source_ids = [int(value) for value in mapping["source_atom_ids"]]
    final_atoms = _ordered_atoms(final_atoms_poscar, source_ids)

    vasprun = Vasprun(
        str(vasprun_path),
        parse_dos=False,
        parse_eigen=False,
        parse_potcar_file=False,
    )
    outcar = Outcar(str(outcar_path))
    final_step = vasprun.ionic_steps[-1]
    raw_forces = final_step["forces"]
    forces_array = np.asarray(raw_forces, dtype=float)
    if forces_array.shape != (len(source_ids), 3):
        raise ValueError("VASP force count does not match POSCAR atom count")
    current_ids = [int(value) for value in final_atoms_poscar.arrays["atom_id"]]
    force_by_id = {atom_id: forces_array[index] for index, atom_id in enumerate(current_ids)}
    forces = [force_by_id[atom_id].tolist() for atom_id in source_ids]

    e_fr_energy = float(final_step["e_fr_energy"])
    e_0_energy = float(vasprun.final_energy)
    e_wo_entrp = float(final_step["e_wo_entrp"])
    stress_raw = final_step["stress"]
    (
        stress_compression,
        stress_tensile,
        stress_voigt_compression,
        stress_voigt_tensile,
    ) = _stress_outputs(stress_raw)

    electronic_converged = bool(vasprun.converged_electronic)
    ionic_converged = bool(vasprun.converged_ionic)
    if stage == "scf":
        ionic_converged = None
    if stage is None:
        method_path = directory / "method.json"
        if method_path.exists():
            method = json.loads(method_path.read_text(encoding="utf-8"))
            if method.get("stage") == "scf":
                ionic_converged = None
            stage = method.get("stage")

    # Vasprun's final structure and CONTCAR must describe the same final
    # geometry before the CONTCAR is restored to source atom order.
    xml_atoms = AseAtomsAdaptor().get_atoms(vasprun.final_structure)
    if len(xml_atoms) != len(final_atoms_poscar):
        raise ValueError("vasprun.xml final_structure atom count differs from CONTCAR")
    if xml_atoms.get_chemical_symbols() != final_atoms_poscar.get_chemical_symbols():
        raise ValueError("vasprun.xml final_structure element order differs from CONTCAR")
    if not np.allclose(xml_atoms.cell.array, final_atoms_poscar.cell.array, atol=1e-7, rtol=0.0):
        raise ValueError("vasprun.xml final_structure lattice differs from CONTCAR")
    xml_frac = xml_atoms.get_scaled_positions(wrap=False)
    contcar_frac = final_atoms_poscar.get_scaled_positions(wrap=False)
    periodic_delta = xml_frac - contcar_frac
    periodic_delta -= np.rint(periodic_delta)
    if not np.allclose(periodic_delta, 0.0, atol=1e-7, rtol=0.0):
        raise ValueError("vasprun.xml final_structure coordinates differ from CONTCAR")

    magnetization_poscar = outcar.magnetization
    if len(magnetization_poscar) != len(source_ids):
        raise ValueError("OUTCAR magnetization count does not match POSCAR atom count")
    magnetization_by_id = {
        atom_id: magnetization_poscar[index]
        for index, atom_id in enumerate(current_ids)
    }
    magnetization = [magnetization_by_id[atom_id] for atom_id in source_ids]

    return VaspResult(
        e_fr_energy=e_fr_energy,
        e_0_energy=e_0_energy,
        e_wo_entrp=e_wo_entrp,
        forces_eV_per_A=forces,
        stress_vasp_compression_positive_GPa=stress_compression,
        stress_tensile_positive_GPa=stress_tensile,
        stress_voigt_vasp_compression_positive_GPa=stress_voigt_compression,
        stress_voigt_tensile_positive_GPa=stress_voigt_tensile,
        atom_ids=source_ids,
        final_atoms=final_atoms,
        electronic_converged=electronic_converged,
        ionic_converged=ionic_converged,
        magnetization=magnetization,
        source_files={"vasprun.xml": str(vasprun_path), "OUTCAR": str(outcar_path), "CONTCAR": str(contcar_path)},
        stage=stage,
    )


parse_vasp_result = parse_vasp_outputs

