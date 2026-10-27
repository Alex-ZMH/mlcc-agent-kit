"""Thin ABACUS 3.10.1 PW and neutral LCAO SCF input/output adapter.

The adapter retains the PW path and the observed GPU/cusolver LCAO SCF path.
It writes the native ``INPUT``,
``STRU`` and ``KPT`` files for SCF, relaxation and explicit Berry NSCF stages,
and parses the native stage log and relaxed ``STRU_ION_D`` file.  It does not
run ABACUS, assemble pseudopotentials, or select an engine.

The source-to-output map is kept beside the input files because ABACUS groups
atoms by element in ``STRU`` while MLCC models retain their source atom order.
All energy and force values are preserved in ABACUS's eV/eV-per-Angstrom
conventions.  ABACUS prints the stress tensor in kBar; this module records the
raw tensor and its direct 0.1 conversion to GPa without assigning a tensile or
compression sign convention.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re
from typing import Any, Literal, Mapping, Sequence

import numpy as np
from ase import Atoms
from ase.data import atomic_masses

from .modeling import ModelArtifacts


BOHR_PER_ANGSTROM = 1.8897261254578281
KBAR_TO_GPA = 0.1
ABACUS_VERSION = "3.10.1"
ABACUS_BASIS_TYPE = "pw"

_ELECTROSTATIC_OUTPUT_CONTROL_FIELDS = frozenset(("out_pot",))
_ELECTROSTATIC_OUTPUT_ARTIFACT = "electrostatic_potential"


def _normalize_output_control(output_control: Mapping[str, Any] | None) -> dict[str, int] | None:
    """Validate the one canonical native electrostatic-output request."""

    if output_control is None:
        return None
    if not isinstance(output_control, Mapping):
        raise ValueError("output_control must be a mapping")
    unknown = set(output_control) - _ELECTROSTATIC_OUTPUT_CONTROL_FIELDS
    if unknown:
        raise ValueError("output_control contains unsupported fields: " + ", ".join(sorted(map(str, unknown))))
    if "out_pot" not in output_control:
        raise ValueError("output_control.out_pot is required when output_control is supplied")
    value = output_control["out_pot"]
    if isinstance(value, bool) or not isinstance(value, (int, np.integer)) or int(value) != 2:
        raise ValueError("output_control.out_pot must be the integer 2")
    return {"out_pot": 2}


def _validate_electrostatic_output_request(
    output_control: Mapping[str, Any] | None,
    *,
    method: "AbacusMethod",
    stage: Literal["scf", "relax", "nscf"],
    input_qualification: Mapping[str, Any] | None,
) -> dict[str, int] | None:
    normalized = _normalize_output_control(output_control)
    if normalized is None:
        return None
    if stage != "scf":
        raise ValueError("electrostatic potential output requires a fixed-cell SCF stage")
    if method.lspinorb is not False or method.noncolin is not False or method.nspin not in (1, 2):
        raise ValueError("electrostatic potential output requires non-SOC collinear nspin=1 or 2")
    if not isinstance(input_qualification, Mapping) or input_qualification.get("input_qualified") is not True:
        raise ValueError("electrostatic potential output requires a passed NC input qualification")
    checks = input_qualification.get("checks")
    norm_conserving = checks.get("norm_conserving") if isinstance(checks, Mapping) else None
    if not isinstance(norm_conserving, Mapping) or norm_conserving.get("passed") is not True:
        raise ValueError("electrostatic potential output requires a passed NC input qualification")
    return normalized


def _electrostatic_potential_artifact(method: "AbacusMethod") -> dict[str, Any]:
    return {
        "schema": "mlcc.abacus-electrostatic-output.v1",
        "relative_path": f"OUT.{method.suffix}/ElecStaticPot.cube",
        "kind": "local_ionic_plus_hartree",
        "value_unit": "Ry",
        "geometry_unit": "Bohr",
        "native_output_observed": False,
        "native_GPU_accepted": False,
    }


@dataclass(frozen=True)
class AbacusMethod:
    """Explicit scientific method selection for ABACUS inputs."""

    suffix: str
    dft_functional: str
    nspin: int
    initial_moments_muB_by_element: Mapping[str, float]
    occupations: Literal["smearing", "fixed"]
    smearing_method: str | None
    mixing_type: str
    relax_method: str
    symmetry: int
    lspinorb: bool = False
    noncolin: bool = False
    # MLCC charge convention: positive q removes q electrons.  The top-level
    # method configuration remains canonical; this field is populated by the
    # configuration adapter and defaults to neutral for direct callers and
    # historical method records.
    net_charge: int = 0
    basis_type: Literal["pw", "lcao"] = "pw"

    def validate(self, element_order: Sequence[str]) -> None:
        if self.basis_type not in ("pw", "lcao"):
            raise ValueError("ABACUS basis_type must be pw or lcao")
        if not self.suffix:
            raise ValueError("ABACUS method suffix must be non-empty")
        if not self.dft_functional:
            raise ValueError("ABACUS method dft_functional must be non-empty")
        if isinstance(self.nspin, bool) or not isinstance(self.nspin, int) or self.nspin not in (1, 2):
            raise ValueError("ABACUS method nspin must be 1 or 2")
        if self.lspinorb is not False or self.noncolin is not False:
            raise ValueError("current ABACUS adapter supports explicit collinear non-SOC methods only")
        if (
            isinstance(self.net_charge, bool)
            or not isinstance(self.net_charge, (int, np.integer))
            or int(self.net_charge) != self.net_charge
        ):
            raise ValueError("ABACUS method net_charge must be an explicit integer")
        if self.occupations not in ("smearing", "fixed"):
            raise ValueError("ABACUS occupations must be smearing or fixed")
        if self.occupations == "smearing" and not self.smearing_method:
            raise ValueError("smearing occupations require smearing_method")
        if self.occupations == "fixed" and self.smearing_method is not None:
            raise ValueError("fixed occupations must not define smearing_method")
        if self.basis_type == "lcao" and (self.net_charge != 0 or self.nspin != 1 or self.occupations != "fixed"):
            raise ValueError("LCAO inputs require neutral nspin=1 fixed occupations")
        if not self.mixing_type or not self.relax_method:
            raise ValueError("ABACUS method mixing_type and relax_method are required")
        requested = [str(value) for value in element_order]
        moments = {str(key): float(value) for key, value in self.initial_moments_muB_by_element.items()}
        if set(moments) != set(requested):
            raise ValueError("initial_moments_muB_by_element must cover element_order exactly")
        if any(not np.isfinite(value) for value in moments.values()):
            raise ValueError("initial magnetic moments must be finite")
        if self.nspin == 1 and any(value != 0.0 for value in moments.values()):
            raise ValueError("nspin=1 requires an explicit zero initial moment for every element")


def abacus_method_from_config(config: Mapping[str, Any]) -> AbacusMethod:
    """Build an :class:`AbacusMethod` from a method configuration.

    ``net_charge`` is canonical at the method-config top level.  Older
    configs omit it and therefore remain neutral.  A nested ``science`` copy
    is tolerated for readable records, but an explicit disagreement is an
    input-contract error instead of being silently selected.
    """

    science = config.get("science")
    if not isinstance(science, Mapping):
        raise ValueError("ABACUS method science mapping is required")
    top_present = "net_charge" in config
    top_charge = config.get("net_charge", 0)
    nested_present = "net_charge" in science
    nested_charge = science.get("net_charge")
    if nested_present:
        if not isinstance(nested_charge, (int, np.integer)) or isinstance(nested_charge, bool):
            raise ValueError("science.net_charge must be an explicit integer when supplied")
        if not top_present and int(nested_charge) != 0:
            raise ValueError("top-level net_charge is required for a non-neutral method")
        if top_present and (
            not isinstance(top_charge, (int, np.integer))
            or isinstance(top_charge, bool)
            or int(top_charge) != int(nested_charge)
        ):
            raise ValueError("science.net_charge disagrees with top-level net_charge")
    payload = dict(science)
    payload.pop("net_charge", None)
    payload["net_charge"] = top_charge
    basis_type = config["basis_type"]
    if "basis_type" in science and science["basis_type"] != basis_type:
        raise ValueError("science.basis_type disagrees with top-level basis_type")
    payload["basis_type"] = basis_type
    return AbacusMethod(**payload)


@dataclass(frozen=True)
class AbacusExecution:
    """Explicit numerical execution selection for ABACUS."""

    device: str
    ks_solver: str

    def validate(self, *, basis_type: str = "pw") -> None:
        if basis_type == "pw":
            if self.device not in ("cpu", "gpu") or self.ks_solver != "cg":
                raise ValueError("current ABACUS PW execution supports device cpu/gpu and ks_solver cg")
        elif basis_type == "lcao":
            if self.device != "gpu" or self.ks_solver != "cusolver":
                raise ValueError("current ABACUS LCAO execution requires GPU/cusolver")
        else:
            raise ValueError("ABACUS basis_type must be pw or lcao")


@dataclass(frozen=True)
class AbacusParameters:
    """Numerical values written to an ABACUS 3.10.1 ``INPUT`` file.

    The numerical values are intentionally explicit.  The adapter supplies
    only the ABACUS defaults that describe the selected PW/spin convention;
    cutoff, SCF thresholds, band count, smearing width and mixing strength
    remain caller-provided method data.
    """

    ecutwfc_Ry: float
    scf_thr: float
    scf_nmax: int
    nbands: int
    smearing_sigma_Ry: float | None
    mixing_beta: float
    force_thr_eV_per_A: float | None = None
    relax_nmax: int | None = None

    def validate(self, stage: Literal["scf", "relax", "nscf"]) -> None:
        """Validate values that have a direct ABACUS domain meaning."""

        for name in ("ecutwfc_Ry", "scf_thr", "mixing_beta", "smearing_sigma_Ry", "force_thr_eV_per_A"):
            value = getattr(self, name)
            if value is not None and not np.isfinite(value):
                raise ValueError(f"{name} must be finite")
        for name in ("scf_nmax", "nbands", "relax_nmax"):
            value = getattr(self, name)
            if value is not None and (isinstance(value, bool) or not isinstance(value, (int, np.integer))):
                raise ValueError(f"{name} must be an integer")
        if self.ecutwfc_Ry <= 0.0:
            raise ValueError("ecutwfc_Ry must be positive")
        if self.scf_thr <= 0.0:
            raise ValueError("scf_thr must be positive")
        if self.scf_nmax <= 0:
            raise ValueError("scf_nmax must be positive")
        if self.nbands <= 0:
            raise ValueError("nbands must be positive")
        if self.smearing_sigma_Ry is not None and self.smearing_sigma_Ry <= 0.0:
            raise ValueError("smearing_sigma_Ry must be positive")
        if self.mixing_beta <= 0.0:
            raise ValueError("mixing_beta must be positive")
        if stage == "relax":
            if self.relax_nmax is None or self.relax_nmax <= 0:
                raise ValueError("relax stage requires relax_nmax > 0")
            if self.force_thr_eV_per_A is None or self.force_thr_eV_per_A <= 0.0:
                raise ValueError("relax stage requires force_thr_eV_per_A > 0")


@dataclass
class AbacusPreparation:
    directory: Path
    stage: str
    model_id: str
    version: str
    abacus_atom_ids: list[int]
    element_order: list[str]
    kpoints: tuple[int, int, int]
    files: dict[str, Path]

    def as_dict(self) -> dict[str, Any]:
        return {
            "directory": str(self.directory),
            "stage": self.stage,
            "model_id": self.model_id,
            "version": self.version,
            "abacus_atom_ids": self.abacus_atom_ids,
            "element_order": self.element_order,
            "kpoints": list(self.kpoints),
            "files": {key: str(value) for key, value in self.files.items()},
        }


@dataclass
class AbacusResult:
    energy_eV: float
    energy_sigma0_eV: float | None
    entropy_minus_TS_eV: float | None
    forces_eV_per_A: list[list[float]]
    stress_kbar: list[list[float]]
    stress_GPa: list[list[float]]
    atom_ids: list[int]
    final_atoms: Atoms
    electronic_converged: bool | None
    ionic_converged: bool | None
    scf_iterations: int | None
    source_files: dict[str, str]
    stage: str | None
    occupations: str
    total_magnetization_muB: float | None = None
    native_completed: bool | None = None
    relaxation: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        energy_definition = _energy_definition(self.occupations)
        energy_default_definition = _energy_default_definition(self.occupations)
        return {
            "energy_eV": float(self.energy_eV),
            "energy_unit": "eV",
            "energy_default_definition": energy_default_definition,
            "energy_definition": energy_definition,
            "energy_definitions": {
                "energy_eV": energy_definition,
                "energy_sigma0_eV": "ABACUS E_KS(sigma->0), when printed",
                "entropy_minus_TS_eV": "ABACUS E_entropy(-TS), when printed",
            },
            "energy_sigma0_eV": self.energy_sigma0_eV,
            "entropy_minus_TS_eV": self.entropy_minus_TS_eV,
            "forces_eV_per_A": self.forces_eV_per_A,
            "stress_kbar": self.stress_kbar,
            "stress_GPa": self.stress_GPa,
            "stress_unit": "GPa",
            "stress_sign": "abacus_printed",
            "stress_sign_calibration": "pending_finite_strain_check",
            "stress_conversion": "0.1 * raw ABACUS kBar",
            "atom_ids": self.atom_ids,
            "final_atoms": {
                "symbols": self.final_atoms.get_chemical_symbols(),
                "positions_angstrom": self.final_atoms.get_positions().tolist(),
                "cell_angstrom": self.final_atoms.cell.array.tolist(),
                "pbc": [bool(value) for value in self.final_atoms.pbc],
            },
            "electronic_converged": self.electronic_converged,
            "ionic_converged": self.ionic_converged,
            "native_completed": self.native_completed,
            "scf_iterations": self.scf_iterations,
            "total_magnetization_muB": self.total_magnetization_muB,
            "magnetization_status": (
                "parsed_native_output"
                if self.total_magnetization_muB is not None
                else "not_parsed_or_not_available"
            ),
            "source_files": self.source_files,
            "stage": self.stage,
            "occupations": self.occupations,
            "relaxation": self.relaxation,
        }


def _coerce_model(model: ModelArtifacts) -> tuple[Atoms, str, str]:
    if not isinstance(model, ModelArtifacts):
        raise TypeError("ABACUS preparation requires a persisted ModelArtifacts value")
    return model.atoms, model.model_id, model.version


def _group_indices(atoms: Atoms, element_order: Sequence[str]) -> list[int]:
    symbols = atoms.get_chemical_symbols()
    requested = [str(value) for value in element_order]
    if len(requested) != len(set(requested)):
        raise ValueError("element_order must not contain duplicates")
    if set(requested) != set(symbols):
        raise ValueError("element_order must list every model element exactly once")
    return [index for element in requested for index, symbol in enumerate(symbols) if symbol == element]


def _validate_kpoints(kpoints: Sequence[int]) -> tuple[int, int, int]:
    values = tuple(kpoints)
    if len(values) != 3 or any(
        isinstance(value, bool)
        or not isinstance(value, (int, np.integer))
        or int(value) <= 0
        for value in values
    ):
        raise ValueError("kpoints must contain exactly three positive integers")
    return tuple(int(value) for value in values)


def _all_free_ionic_constraints(atoms: Atoms, *, origin: str) -> dict[str, Any]:
    """Return the canonical source-order all-free constraint record."""

    if "atom_id" not in atoms.arrays:
        raise ValueError("ionic constraints require model atom_id values")
    atom_ids = [int(value) for value in atoms.arrays["atom_id"]]
    return {
        "schema": "mlcc.ionic-constraints.v1",
        "coordinate_basis": "cartesian",
        "atom_ids": atom_ids,
        "move_flags": [[1, 1, 1] for _ in atom_ids],
        "relax_new": True,
        "origin": origin,
    }


def _is_positive_diagonal_cell(cell: np.ndarray) -> bool:
    return bool(
        cell.shape == (3, 3)
        and np.all(np.isfinite(cell))
        and np.all(np.diag(cell) > 0.0)
        and np.allclose(cell, np.diag(np.diag(cell)), rtol=0.0, atol=1.0e-10)
    )


def _normalize_ionic_constraints(
    atoms: Atoms,
    ionic_constraints: Mapping[str, Any] | None,
    *,
    origin: str,
) -> dict[str, Any]:
    """Validate and normalize the explicit Cartesian ionic-DOF contract.

    ABACUS groups atoms by element, while the public contract is keyed by the
    model's stable source atom IDs.  This helper keeps the source-order record;
    the writer maps the same record to grouped native order.
    """

    if "atom_id" not in atoms.arrays:
        raise ValueError("ionic constraints require model atom_id values")
    source_ids = [int(value) for value in atoms.arrays["atom_id"]]
    if getattr(atoms, "constraints", ()):
        raise ValueError("unsupported ASE constraints require explicit ionic_constraints and are not silently dropped")
    if ionic_constraints is None:
        return _all_free_ionic_constraints(atoms, origin=origin)
    if not isinstance(ionic_constraints, Mapping):
        raise ValueError("ionic_constraints must be an object")
    unknown = set(ionic_constraints) - {
        "schema", "coordinate_basis", "atom_ids", "move_flags", "relax_new", "origin"
    }
    if unknown:
        raise ValueError("ionic_constraints contains unsupported fields: " + ", ".join(sorted(map(str, unknown))))
    if "schema" in ionic_constraints and ionic_constraints["schema"] != "mlcc.ionic-constraints.v1":
        raise ValueError("ionic_constraints.schema is unsupported")
    if "relax_new" in ionic_constraints and ionic_constraints["relax_new"] is not True:
        raise ValueError("ionic_constraints.relax_new must be true")
    if ionic_constraints.get("coordinate_basis") != "cartesian":
        raise ValueError("ionic_constraints.coordinate_basis must be cartesian")
    atom_ids_raw = ionic_constraints.get("atom_ids")
    flags_raw = ionic_constraints.get("move_flags")
    if isinstance(atom_ids_raw, (str, bytes)) or not isinstance(atom_ids_raw, Sequence):
        raise ValueError("ionic_constraints.atom_ids must be a sequence")
    if isinstance(flags_raw, (str, bytes)) or not isinstance(flags_raw, Sequence):
        raise ValueError("ionic_constraints.move_flags must be a sequence")
    atom_ids: list[int] = []
    for value in atom_ids_raw:
        # Do not coerce truthy/fractional/string values into an atom identity.
        # The public contract uses the model's actual integer source IDs.
        if isinstance(value, bool) or not isinstance(value, (int, np.integer)):
            raise ValueError("ionic_constraints.atom_ids must contain integers")
        atom_ids.append(int(value))
    if atom_ids != list(dict.fromkeys(atom_ids)) or sorted(atom_ids) != sorted(source_ids):
        raise ValueError("ionic_constraints.atom_ids must cover every model atom exactly once")
    if len(flags_raw) != len(atom_ids):
        raise ValueError("ionic_constraints.move_flags length must match atom_ids")
    by_id: dict[int, list[int]] = {}
    for atom_id, row in zip(atom_ids, flags_raw):
        if isinstance(row, (str, bytes)) or not isinstance(row, Sequence) or len(row) != 3:
            raise ValueError("each ionic_constraints.move_flags row must contain three values")
        normalized_row: list[int] = []
        for value in row:
            if isinstance(value, bool) or not isinstance(value, (int, np.integer)) or int(value) not in (0, 1):
                raise ValueError("ionic_constraints.move_flags values must be integer 0 or 1")
            normalized_row.append(int(value))
        by_id[atom_id] = normalized_row
    normalized_flags = [by_id[atom_id] for atom_id in source_ids]
    if not any(value for row in normalized_flags for value in row):
        raise ValueError("ionic_constraints must leave at least one movable degree of freedom")
    partial = any(len(set(row)) > 1 for row in normalized_flags)
    cell = np.asarray(atoms.cell.array, dtype=float)
    if partial and not _is_positive_diagonal_cell(cell):
        raise ValueError(
            "partial Cartesian ionic constraints require a positive diagonal axis-aligned orthorhombic cell"
        )
    return {
        "schema": "mlcc.ionic-constraints.v1",
        "coordinate_basis": "cartesian",
        "atom_ids": source_ids,
        "move_flags": normalized_flags,
        "relax_new": True,
        "origin": origin,
    }


def _lcao_output_values(lcao_output: Mapping[str, int] | None) -> dict[str, int] | None:
    """Keep the four explicitly requested native LCAO output switches."""
    if lcao_output is None:
        return None
    fields = ("out_chg", "out_bandgap", "out_mat_hs2", "out_mat_r")
    if set(lcao_output) != set(fields):
        raise ValueError("lcao_output must contain exactly out_chg/out_bandgap/out_mat_hs2/out_mat_r")
    for field in fields:
        value = lcao_output[field]
        if isinstance(value, bool) or not isinstance(value, (int, np.integer)) or value not in (0, 1):
            raise ValueError(f"lcao_output.{field} must be integer 0 or 1")
    return {field: int(lcao_output[field]) for field in fields}


def _input_text(
    parameters: AbacusParameters,
    *,
    method: AbacusMethod,
    execution: AbacusExecution,
    stage: Literal["scf", "relax", "nscf"],
    berry: Mapping[str, Any] | None = None,
    output_control: Mapping[str, Any] | None = None,
    lcao_output: Mapping[str, int] | None = None,
) -> str:
    if method.basis_type == "lcao":
        if stage != "scf" or berry is not None or output_control is not None:
            raise ValueError("LCAO supports SCF only, without Berry or PW output_control")
        if method.net_charge != 0 or method.nspin != 1 or method.occupations != "fixed" or method.lspinorb or method.noncolin:
            raise ValueError("LCAO inputs require neutral non-SOC nspin=1 fixed occupations")
        execution.validate(basis_type="lcao")
    elif method.basis_type == "pw":
        if lcao_output is not None:
            raise ValueError("PW inputs must not carry lcao_output")
    else:
        raise ValueError("ABACUS basis_type must be pw or lcao")
    lcao_output = _lcao_output_values(lcao_output)
    output_control = _normalize_output_control(output_control)
    if output_control is not None and stage != "scf":
        raise ValueError("electrostatic potential output requires a fixed-cell SCF stage")
    charged = int(method.net_charge) != 0
    if charged:
        # The first charged slice is deliberately narrower than the neutral
        # writer: only fixed-cell PW SCF, nspin=1, fixed occupations are
        # supported.  Rejecting here prevents a caller from accidentally
        # emitting charged Berry/relax inputs that have no qualified contract.
        if stage != "scf":
            raise ValueError("charged ABACUS inputs support fixed-cell SCF only")
        if berry is not None:
            raise ValueError("charged ABACUS inputs are unsupported for Berry stages")
        if method.nspin != 1 or method.occupations != "fixed":
            raise ValueError("charged ABACUS inputs require nspin=1 fixed occupations")
        if method.lspinorb is not False or method.noncolin is not False:
            raise ValueError("charged ABACUS inputs require non-SOC collinear settings")
    values = [
        "INPUT_PARAMETERS",
        f"suffix                {method.suffix}",
        "pseudo_dir            ./",
        f"calculation           {stage}",
        f"device               {execution.device}",
        f"dft_functional      {method.dft_functional}",
        f"basis_type           {method.basis_type}",
        f"ks_solver            {execution.ks_solver}",
        f"ecutwfc              {parameters.ecutwfc_Ry:.12g}",
        f"scf_thr              {parameters.scf_thr:.12g}",
        f"scf_nmax             {parameters.scf_nmax}",
        f"nbands               {parameters.nbands}",
        f"nspin                {method.nspin}",
        f"lspinorb             {int(method.lspinorb)}",
        f"noncolin             {int(method.noncolin)}",
        f"mixing_type          {method.mixing_type}",
        f"mixing_beta          {parameters.mixing_beta:.12g}",
        f"symmetry             {method.symmetry}",
    ]
    if method.basis_type == "lcao":
        values.extend(["orbital_dir           ./", "gamma_only           0", "init_chg             auto"])
        if lcao_output is not None:
            values.extend(f"{field:<21}{value}" for field, value in lcao_output.items())
    if charged:
        # ABACUS 3.10.1 computes the neutral UPF valence count when nelec=0,
        # then applies nelec_delta.  MLCC q is an electron deficit, hence
        # nelec_delta=-q.  Keep neutral inputs byte-compatible by omitting the
        # pair when q=0.
        values.extend(["nelec                0", f"nelec_delta          {-int(method.net_charge)}"])
    if stage != "nscf":
        values.extend(["cal_force            1", "cal_stress           1"])
    if output_control is not None:
        # These flags define the restricted 3.10.1 PW/NC electrostatic
        # source contract.  They are emitted only when the caller explicitly
        # requests out_pot=2, preserving historical INPUT text otherwise.
        values.extend(
            [
                "out_pot              2",
                "out_interval         1",
                "efield_flag          0",
                "dip_cor_flag         0",
                "gate_flag            0",
                "imp_sol              0",
                "use_paw              0",
                "vl_in_h              1",
                "vion_in_h            1",
                "vh_in_h              1",
            ]
        )
    if method.occupations == "smearing":
        if parameters.smearing_sigma_Ry is None:
            raise ValueError("smearing occupations require smearing_sigma_Ry")
        values.extend(
            [
                f"smearing_method      {method.smearing_method}",
                f"smearing_sigma       {parameters.smearing_sigma_Ry:.12g}",
            ]
        )
    else:
        if parameters.smearing_sigma_Ry is not None:
            raise ValueError("fixed occupations must not define smearing_sigma_Ry")
        # ABACUS 3.10.1 represents fixed occupations through its native
        # smearing_method value.  ``occupations`` is an MLCC method contract,
        # not an ABACUS INPUT keyword.
        values.append("smearing_method      fixed")
    if stage == "relax":
        if method.relax_method != "cg":
            raise ValueError("fixed-cell relax requires relax_method=cg")
        values.extend(
            [
                f"relax_method        {method.relax_method}",
                "relax_new           1",
                f"relax_nmax          {parameters.relax_nmax}",
                f"force_thr_ev        {parameters.force_thr_eV_per_A:.12g}",
                "out_stru             1",
            ]
        )
    if berry is not None:
        if not isinstance(berry, Mapping):
            raise TypeError("berry must be a mapping when supplied")
        role = str(berry.get("role", ""))
        if role == "reference_scf":
            if stage != "scf":
                raise ValueError("Berry reference_scf requires an SCF stage")
            if int(berry.get("out_chg", 0)) != 1:
                raise ValueError("Berry reference_scf requires out_chg=1")
            values.append("out_chg              1")
        elif role == "nscf":
            if stage != "nscf":
                raise ValueError("Berry nscf requires an NSCF stage")
            if str(berry.get("init_chg", "")).lower() != "file":
                raise ValueError("Berry nscf requires init_chg=file")
            if int(berry.get("berry_phase", 0)) != 1:
                raise ValueError("Berry nscf requires berry_phase=1")
            gdir = berry.get("gdir")
            if isinstance(gdir, bool) or not isinstance(gdir, (int, np.integer)) or int(gdir) not in (1, 2, 3):
                raise ValueError("Berry nscf gdir must be 1, 2, or 3")
            if int(berry.get("symmetry", 0)) != -1:
                raise ValueError("Berry nscf requires symmetry=-1")
            pw_diag_thr = berry.get("pw_diag_thr")
            if pw_diag_thr is None or not np.isfinite(float(pw_diag_thr)) or float(pw_diag_thr) <= 0.0:
                raise ValueError("Berry nscf requires a positive finite pw_diag_thr")
            if float(pw_diag_thr) > 1.0e-3:
                raise ValueError("Berry PW NSCF pw_diag_thr must be <= 1e-3")
            values.extend(
                [
                    "init_chg            file",
                    "read_file_dir      ./",
                    "berry_phase        1",
                    f"gdir                {int(gdir)}",
                    f"pw_diag_thr        {float(pw_diag_thr):.12g}",
                ]
            )
        else:
            raise ValueError("berry role must be reference_scf or nscf")
    return "\n".join(values) + "\n"


def _validate_charged_input_qualification(
    method: AbacusMethod,
    parameters: AbacusParameters,
    stage: Literal["scf", "relax", "nscf"],
    qualification: Mapping[str, Any] | None,
) -> None:
    """Require the input-only electron contract before writing charged INPUT.

    This is intentionally a declared-valence arithmetic check.  It does not
    inspect native output and therefore does not confer scientific or
    production qualification.
    """

    if int(method.net_charge) == 0:
        return
    if stage != "scf":
        raise ValueError("charged ABACUS inputs support fixed-cell SCF only")
    if not isinstance(qualification, Mapping) or qualification.get("input_qualified") is not True:
        raise ValueError("charged ABACUS inputs require a passed input qualification report")
    if qualification.get("scientific_qualification") is not False:
        raise ValueError("charged input qualification must declare scientific_qualification=false")
    if qualification.get("production_qualification") is not False:
        raise ValueError("charged input qualification must declare production_qualification=false")
    counts = qualification.get("electron_count")
    if not isinstance(counts, Mapping):
        raise ValueError("charged input qualification requires electron_count")
    q = int(method.net_charge)
    neutral = counts.get("neutral_valence_electrons")
    target = counts.get("target_electrons")
    declared_q = counts.get("net_charge")
    nelec = counts.get("nelec")
    nelec_delta = counts.get("nelec_delta")
    if (
        neutral is None
        or target is None
        or not np.isfinite(float(neutral))
        or not np.isfinite(float(target))
        or float(neutral) <= 0.0
        or not np.isclose(float(target), float(neutral) - q, rtol=0.0, atol=1e-8)
        or float(target) <= 0.0
        or not np.isclose(float(target), round(float(target)), rtol=0.0, atol=1e-8)
        or int(round(float(target))) % 2 != 0
    ):
        raise ValueError("charged input qualification requires a positive even target electron count")
    if declared_q != q or nelec != 0 or nelec_delta != -q:
        raise ValueError("charged input qualification electron fields disagree with method net_charge")
    declared_nbands = counts.get("nbands")
    if (
        isinstance(declared_nbands, bool)
        or not isinstance(declared_nbands, (int, np.integer))
        or int(declared_nbands) != int(parameters.nbands)
        or int(declared_nbands) < int(round(float(target))) // 2
    ):
        raise ValueError("charged input qualification nbands cannot hold the target electron count")


def _write_stru(
    path: Path,
    atoms: Atoms,
    *,
    element_order: Sequence[str],
    source_indices: Sequence[int],
    pseudopotentials: Mapping[str, str],
    initial_moments_muB_by_element: Mapping[str, float],
    move_flags_by_atom_id: Mapping[int, Sequence[int]] | None = None,
    numerical_orbitals: Mapping[str, str] | None = None,
) -> list[int]:
    cell = np.asarray(atoms.cell.array, dtype=float)
    if cell.shape != (3, 3):
        raise ValueError("ABACUS STRU requires a 3x3 periodic cell")
    if not np.all(atoms.pbc):
        raise ValueError("ABACUS STRU adapter requires periodic atoms")
    symbols = atoms.get_chemical_symbols()
    grouped_ids = [int(atoms.arrays["atom_id"][index]) for index in source_indices]
    lines = ["ATOMIC_SPECIES"]
    for element in element_order:
        if element not in pseudopotentials:
            raise KeyError(f"missing ABACUS pseudopotential for element {element}")
        atomic_number = int(atoms.numbers[[index for index, symbol in enumerate(symbols) if symbol == element][0]])
        mass = float(atomic_masses[atomic_number])
        pseudo_path = str(pseudopotentials[element])
        pseudo_name = Path(pseudo_path).name
        lines.append(f"{element} {mass:.8g} {pseudo_name} upf201")
    if numerical_orbitals is not None:
        if set(numerical_orbitals) != set(element_order):
            raise ValueError("numerical_orbitals must cover element_order exactly")
        lines.extend(["", "NUMERICAL_ORBITAL"])
        lines.extend(Path(numerical_orbitals[element]).name for element in element_order)
    lines.extend(
        [
            "",
            "LATTICE_CONSTANT",
            f"{BOHR_PER_ANGSTROM:.16g}",
            "",
            "LATTICE_VECTORS",
        ]
    )
    # ``LATTICE_CONSTANT`` is written as 1 Angstrom in Bohr (the native
    # ABACUS unit), so vectors retain their numerical Angstrom values.
    for vector in cell:
        lines.append(" ".join(f"{float(value):.16g}" for value in vector))
    lines.extend(["", "ATOMIC_POSITIONS", "Direct"])
    scaled = atoms.get_scaled_positions(wrap=False)
    for element in element_order:
        element_indices = [index for index in source_indices if symbols[index] == element]
        lines.extend([element, f"{float(initial_moments_muB_by_element[element]):.12g}", str(len(element_indices))])
        for index in element_indices:
            coordinates = " ".join(f"{float(value):.16g}" for value in scaled[index])
            if move_flags_by_atom_id is None:
                flags = (1, 1, 1)
            else:
                atom_id = int(atoms.arrays["atom_id"][index])
                flags = tuple(int(value) for value in move_flags_by_atom_id[atom_id])
            lines.append(f"{coordinates} m {' '.join(str(value) for value in flags)}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return grouped_ids


def prepare_abacus(
    model: ModelArtifacts,
    output_dir: str | Path,
    *,
    method: AbacusMethod,
    execution: AbacusExecution,
    parameters: AbacusParameters,
    stage: Literal["scf", "relax", "nscf"],
    pseudopotentials: Mapping[str, str],
    element_order: Sequence[str],
    kpoints: Sequence[int],
    berry: Mapping[str, Any] | None = None,
    input_qualification: Mapping[str, Any] | None = None,
    output_control: Mapping[str, Any] | None = None,
    ionic_constraints: Mapping[str, Any] | None = None,
    numerical_orbitals: Mapping[str, str] | None = None,
    lcao_output: Mapping[str, int] | None = None,
) -> AbacusPreparation:
    """Write native ABACUS inputs and their source atom map.

    ``method`` and ``execution`` are explicit scientific and numerical choices;
    no element, spin, suffix, device or smearing choice is supplied here.
    ``pseudopotentials`` maps an element to a caller-authorized file path or
    filename.  Only its basename is written in ``STRU``; the original mapping
    is recorded in ``method.json`` for the remote staging step.  No pseudopot-
    ential data is copied by this function.  ``kpoints`` is the caller-selected
    Gamma-centered integer mesh and is recorded as an explicit mesh choice.
    LCAO numerical orbitals follow the same source/basename convention;
    their library contents are not copied or qualified by this writer.
    """

    atoms, model_id, version = _coerce_model(model)
    if "atom_id" not in atoms.arrays:
        raise ValueError("prepare_abacus requires model atom_id values")
    requested_elements = [str(value) for value in element_order]
    source_indices = _group_indices(atoms, requested_elements)
    method.validate(requested_elements)
    execution.validate(basis_type=method.basis_type)
    if method.basis_type == "lcao":
        if stage != "scf" or berry is not None or output_control is not None:
            raise ValueError("LCAO supports SCF only, without Berry or PW output_control")
        if numerical_orbitals is None or set(numerical_orbitals) != set(requested_elements):
            raise ValueError("LCAO numerical_orbitals must cover element_order exactly")
        for element in requested_elements:
            if not numerical_orbitals[element]:
                raise ValueError(f"numerical_orbitals.{element} source must be non-empty")
    elif numerical_orbitals is not None or lcao_output is not None:
        raise ValueError("PW inputs must not carry numerical_orbitals or lcao_output")
    lcao_output = _lcao_output_values(lcao_output)
    parameters.validate(stage)
    if stage != "relax" and ionic_constraints is not None:
        raise ValueError("ionic_constraints are supported only for fixed-cell relax")
    normalized_ionic_constraints: dict[str, Any] | None = None
    if stage == "relax":
        normalized_ionic_constraints = _normalize_ionic_constraints(
            atoms,
            ionic_constraints,
            origin="explicit_request" if ionic_constraints is not None else "legacy_all_free",
        )
        if method.relax_method != "cg":
            raise ValueError("fixed-cell relax requires relax_method=cg")
    _validate_charged_input_qualification(method, parameters, stage, input_qualification)
    output_control = _validate_electrostatic_output_request(
        output_control,
        method=method,
        stage=stage,
        input_qualification=input_qualification,
    )
    kpoints = _validate_kpoints(kpoints)
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)

    input_path = output / "INPUT"
    stru_path = output / "STRU"
    kpt_path = output / "KPT"
    map_path = output / "STRU.atom-map.json"
    method_path = output / "method.json"
    input_path.write_text(
        _input_text(
            parameters,
            method=method,
            execution=execution,
            stage=stage,
            berry=berry,
            output_control=output_control,
            lcao_output=lcao_output,
        ),
        encoding="utf-8",
        newline="\n",
    )
    abacus_atom_ids = _write_stru(
        stru_path,
        atoms,
        element_order=requested_elements,
        source_indices=source_indices,
        pseudopotentials=pseudopotentials,
        initial_moments_muB_by_element=method.initial_moments_muB_by_element,
        numerical_orbitals=numerical_orbitals,
        move_flags_by_atom_id=(
            {
                int(atom_id): flags
                for atom_id, flags in zip(
                    normalized_ionic_constraints["atom_ids"],
                    normalized_ionic_constraints["move_flags"],
                )
            }
            if normalized_ionic_constraints is not None
            else None
        ),
    )
    kx, ky, kz = kpoints
    kpt_path.write_text(
        f"K_POINTS\n0\nGamma\n{kx} {ky} {kz} 0 0 0\n",
        encoding="utf-8",
        newline="\n",
    )
    source_ids = [int(value) for value in atoms.arrays["atom_id"]]
    mapping = {
        "schema": "mlcc.abacus-atom-map.v1",
        "abacus_version_target": ABACUS_VERSION,
        "model_id": model_id,
        "version": version,
        "source_atom_ids": source_ids,
        "element_order": requested_elements,
        "abacus_order": [
            {
                "abacus_index": output_index,
                "source_index": source_index,
                "atom_id": int(atoms.arrays["atom_id"][source_index]),
                "element": atoms.get_chemical_symbols()[source_index],
                "label": f"{atoms.get_chemical_symbols()[source_index]}{sum(1 for previous in source_indices[:output_index] if atoms.get_chemical_symbols()[previous] == atoms.get_chemical_symbols()[source_index]) + 1}",
            }
            for output_index, source_index in enumerate(source_indices)
        ],
        "coordinate_unit": "Direct",
        "lattice_constant_bohr": BOHR_PER_ANGSTROM,
    }
    map_path.write_text(json.dumps(mapping, indent=2) + "\n", encoding="utf-8")
    method_record = {
        "schema": "mlcc.method.v1",
        "engine": "abacus",
        "abacus_version_target": ABACUS_VERSION,
        "stage": stage,
        "model_id": model_id,
        "version": version,
        "suffix": method.suffix,
        "device": execution.device,
        "dft_functional": method.dft_functional,
        "basis_type": method.basis_type,
        "ks_solver": execution.ks_solver,
        "nspin": method.nspin,
        "lspinorb": method.lspinorb,
        "noncolin": method.noncolin,
        "initial_moments_muB_by_element": dict(method.initial_moments_muB_by_element),
        "occupations": method.occupations,
        "smearing_method": method.smearing_method,
        "mixing_type": method.mixing_type,
        "relax_method": method.relax_method,
        "symmetry": method.symmetry,
        "net_charge": int(method.net_charge),
        "nelec": 0,
        "nelec_delta": -int(method.net_charge),
        "charge_convention": "positive q removes q electrons",
        "element_order": requested_elements,
        "kpoints": list(kpoints),
        "kpoint_rule": "explicit_mesh",
        "parameters": asdict(parameters),
        "pseudopotentials": {
            element: {"source": str(pseudopotentials[element]), "filename": Path(str(pseudopotentials[element])).name}
            for element in requested_elements
        },
        # Keep the explicit selections grouped for task runners while the
        # top-level fields above remain readable in historical records.
        "science": asdict(method),
        "execution": asdict(execution),
        "scientific_qualification": False,
        "production_qualification": False,
        "stress_convention": {
            "input_output_unit": "raw ABACUS output kBar",
            "converted_unit": "GPa",
            "conversion": "0.1 * raw kBar",
            "sign": "abacus_printed",
            "sign_calibration": "pending_finite_strain_check",
        },
    }
    if numerical_orbitals is not None:
        method_record["numerical_orbitals"] = {
            element: {"source": str(numerical_orbitals[element]), "filename": Path(numerical_orbitals[element]).name}
            for element in requested_elements
        }
        method_record["gamma_only"] = False
        method_record["init_chg"] = "auto"
    if lcao_output is not None:
        method_record["lcao_output"] = lcao_output
    if berry is not None:
        method_record["berry"] = dict(berry)
    if normalized_ionic_constraints is not None:
        method_record["ionic_constraints"] = normalized_ionic_constraints
        method_record["relax_new"] = True
    if input_qualification is not None:
        method_record["input_qualification"] = dict(input_qualification)
    if output_control is not None:
        method_record["output_control"] = dict(output_control)
        method_record["requested_artifacts"] = {
            _ELECTROSTATIC_OUTPUT_ARTIFACT: _electrostatic_potential_artifact(method),
        }
    method_path.write_text(json.dumps(method_record, indent=2) + "\n", encoding="utf-8")
    files = {
        "INPUT": input_path,
        "STRU": stru_path,
        "KPT": kpt_path,
        "STRU.atom-map.json": map_path,
        "method.json": method_path,
    }
    return AbacusPreparation(
        output,
        stage,
        model_id,
        version,
        abacus_atom_ids,
        requested_elements,
        kpoints,
        files,
    )


_NUMBER = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[EeDd][+-]?\d+)?"
_ENERGY_RE = re.compile(r"!FINAL_ETOT_IS\s+(?P<value>" + _NUMBER + r")\s+eV\b")
_ENERGY_SIGMA0_RE = re.compile(
    r"^\s*E_KS\(sigma->0\)\s+(?P<ry>" + _NUMBER + r")\s+(?P<ev>" + _NUMBER + r")\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_ENERGY_ENTROPY_RE = re.compile(
    r"^\s*E_entropy\(-TS\)\s+(?P<ry>" + _NUMBER + r")\s+(?P<ev>" + _NUMBER + r")\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_FORCE_ROW_RE = re.compile(
    r"^\s*(?P<label>[A-Za-z][A-Za-z0-9_#-]*)\s+(?P<x>" + _NUMBER + r")\s+(?P<y>" + _NUMBER + r")\s+(?P<z>" + _NUMBER + r").*$"
)
_STRESS_ROW_RE = re.compile(
    r"^\s*(?P<x>" + _NUMBER + r")\s+(?P<y>" + _NUMBER + r")\s+(?P<z>" + _NUMBER + r")\s*$"
)
_PW_ALGORITHM_RE = re.compile(
    r"^\s*PW ALGORITHM\s+-+\s+ION=\s*(?P<ion>[0-9]+)\s+ELEC=\s*(?P<elec>[0-9]+)",
    re.IGNORECASE | re.MULTILINE,
)
_TOTAL_MAGNETISM_RE = re.compile(
    r"^\s*total magnetism\s+\(Bohr mag/cell\)\s*=\s*(?P<value>" + _NUMBER + r")\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_SMEARING_METHOD_RE = re.compile(
    r"^\s*smearing_method\s+(?P<value>[^\s#]+)(?:\s+#.*)?$",
    re.IGNORECASE | re.MULTILINE,
)
_SMEARING_SIGMA_RE = re.compile(
    r"^\s*smearing_sigma\s+(?P<value>" + _NUMBER + r")(?:\s+#.*)?$",
    re.IGNORECASE | re.MULTILINE,
)
_ABACUS_SMEARING_METHODS = frozenset(("gauss", "fd", "fixed", "mp", "mp2", "mv"))


def _number(value: str) -> float:
    return float(value.replace("D", "E").replace("d", "e"))


def _last_index(lines: Sequence[str], pattern: re.Pattern[str]) -> int:
    matches = [index for index, line in enumerate(lines) if pattern.search(line)]
    if not matches:
        raise ValueError(f"ABACUS output is missing required section: {pattern.pattern}")
    return matches[-1]


def _parse_energy(text: str) -> float:
    matches = list(_ENERGY_RE.finditer(text))
    if not matches:
        raise ValueError("ABACUS 3.10.1 output is missing !FINAL_ETOT_IS energy")
    return _number(matches[-1].group("value"))


def _parse_energy_records(text: str) -> tuple[float | None, float | None]:
    sigma0 = list(_ENERGY_SIGMA0_RE.finditer(text))
    entropy = list(_ENERGY_ENTROPY_RE.finditer(text))
    sigma0_eV = _number(sigma0[-1].group("ev")) if sigma0 else None
    entropy_minus_TS_eV = _number(entropy[-1].group("ev")) if entropy else None
    return sigma0_eV, entropy_minus_TS_eV


def _parse_total_magnetization(text: str) -> float | None:
    matches = list(_TOTAL_MAGNETISM_RE.finditer(text))
    return None if not matches else _number(matches[-1].group("value"))


def _read_method_record(task_dir: Path) -> dict[str, Any]:
    method_path = task_dir / "method.json"
    method = json.loads(method_path.read_text(encoding="utf-8"))
    if method["engine"] != "abacus" or method["abacus_version_target"] != ABACUS_VERSION:
        raise ValueError("ABACUS output method.json does not target ABACUS 3.10.1")
    if not method["suffix"]:
        raise ValueError("ABACUS output method.json has an empty suffix")
    return method


def _native_smearing(task_dir: Path) -> tuple[str, float | None]:
    input_path = task_dir / "INPUT"
    text = input_path.read_text(encoding="utf-8")
    matches = list(_SMEARING_METHOD_RE.finditer(text))
    if not matches:
        raise ValueError("ABACUS INPUT is missing required smearing_method")
    smearing_method = matches[-1].group("value").lower()
    if smearing_method not in _ABACUS_SMEARING_METHODS:
        raise ValueError(f"ABACUS INPUT has unsupported smearing_method: {smearing_method}")
    sigma_matches = list(_SMEARING_SIGMA_RE.finditer(text))
    if smearing_method == "fixed":
        if sigma_matches:
            raise ValueError("ABACUS INPUT fixed smearing_method must not define smearing_sigma")
        return smearing_method, None
    if not sigma_matches:
        raise ValueError(f"ABACUS INPUT smearing_method {smearing_method} is missing smearing_sigma")
    return smearing_method, _number(sigma_matches[-1].group("value"))


def _resolve_occupations(
    task_dir: Path,
    method: Mapping[str, Any],
    explicit: Literal["smearing", "fixed"] | None,
) -> str:
    native_method, native_sigma = _native_smearing(task_dir)
    native_occupations = "fixed" if native_method == "fixed" else "smearing"
    if explicit is not None and explicit not in ("smearing", "fixed"):
        raise ValueError("function argument occupations must be smearing or fixed")
    if explicit is not None and explicit != native_occupations:
        raise ValueError("explicit occupations disagree with native INPUT smearing_method")
    if "occupations" in method:
        method_occupations = str(method["occupations"]).lower()
        if method_occupations not in ("smearing", "fixed"):
            raise ValueError("method.json occupations must be smearing or fixed")
        if method_occupations != native_occupations:
            raise ValueError("method.json occupations disagree with native INPUT smearing_method")
    if "smearing_method" not in method:
        raise ValueError("method.json is missing top-level smearing_method")
    method_smearing = method["smearing_method"]
    parameters = method.get("parameters")
    if not isinstance(parameters, Mapping) or "smearing_sigma_Ry" not in parameters:
        raise ValueError("method.json is missing parameters.smearing_sigma_Ry")
    method_sigma = parameters["smearing_sigma_Ry"]
    if native_method == "fixed":
        if method_smearing is not None:
            raise ValueError("method.json fixed occupations require smearing_method null")
        if method_sigma is not None:
            raise ValueError("method.json fixed occupations require smearing_sigma_Ry null")
        return "fixed"
    if str(method_smearing).lower() != native_method:
        raise ValueError("method.json smearing_method differs from native INPUT")
    if method_sigma is None:
        raise ValueError("method.json smearing occupations require smearing_sigma_Ry")
    if not np.isclose(float(method_sigma), native_sigma, rtol=1e-6, atol=1e-10):
        raise ValueError("method.json smearing_sigma_Ry differs from native INPUT")
    return "smearing"


def _energy_definition(occupations: str) -> str:
    if occupations == "fixed":
        return "ABACUS 3.10.1 !FINAL_ETOT_IS / E_KohnSham at fixed occupations in eV"
    if occupations == "smearing":
        return "ABACUS 3.10.1 !FINAL_ETOT_IS / E_KohnSham at the selected finite smearing"
    raise ValueError(f"unsupported occupations: {occupations}")


def _energy_default_definition(occupations: str) -> str:
    if occupations == "fixed":
        return "ABACUS 3.10.1 !FINAL_ETOT_IS / E_KohnSham at fixed occupations in eV"
    if occupations == "smearing":
        return "ABACUS 3.10.1 !FINAL_ETOT_IS / E_KohnSham finite-smearing free energy in eV"
    raise ValueError(f"unsupported occupations: {occupations}")


def _parse_forces(lines: Sequence[str], atom_map: Mapping[str, Any]) -> list[list[float]]:
    heading = _last_index(lines, re.compile(r"TOTAL-FORCE\s*\(eV/Angstrom\)", re.IGNORECASE))
    entries = sorted(atom_map["abacus_order"], key=lambda item: int(item["abacus_index"]))
    rows: list[list[float]] = []
    labels: list[str] = []
    for line in lines[heading + 1 :]:
        match = _FORCE_ROW_RE.match(line)
        if match is None:
            if rows and ("TOTAL-STRESS" in line or line.strip().startswith("----")):
                break
            continue
        rows.append([_number(match.group(axis)) for axis in ("x", "y", "z")])
        labels.append(match.group("label"))
        if len(rows) == len(entries):
            break
    if len(rows) != len(entries):
        raise ValueError("ABACUS force row count does not match STRU atom map")
    for index, (label, entry) in enumerate(zip(labels, entries)):
        expected_label = str(entry["label"])
        if label != expected_label:
            raise ValueError(f"ABACUS force row {index} label differs from STRU atom map")
    source_ids = [int(value) for value in atom_map["source_atom_ids"]]
    forces_by_id = {
        int(entry["atom_id"]): rows[index]
        for index, entry in enumerate(entries)
    }
    return [forces_by_id[atom_id] for atom_id in source_ids]


def _parse_stress(lines: Sequence[str]) -> tuple[list[list[float]], list[list[float]]]:
    heading = _last_index(lines, re.compile(r"TOTAL-STRESS\s*\(KBAR\)", re.IGNORECASE))
    rows: list[list[float]] = []
    for line in lines[heading + 1 :]:
        match = _STRESS_ROW_RE.match(line)
        if match is None:
            continue
        rows.append([_number(match.group(axis)) for axis in ("x", "y", "z")])
        if len(rows) == 3:
            break
    if len(rows) != 3:
        raise ValueError("ABACUS stress tensor is not a 3x3 KBAR matrix")
    stress = np.asarray(rows, dtype=float)
    return rows, (stress * KBAR_TO_GPA).tolist()


def _source_atoms_from_model(model: ModelArtifacts) -> tuple[Atoms, str, str]:
    atoms, model_id, version = _coerce_model(model)
    if "atom_id" not in atoms.arrays:
        raise ValueError("ABACUS output parsing requires source atom_id values")
    return atoms.copy(), model_id, version


def _read_stru_with_constraints(
    path: Path,
    atom_map: Mapping[str, Any],
    *,
    require_move_flags: bool = False,
) -> tuple[Atoms, list[list[int]] | None]:
    raw_lines = path.read_text(encoding="utf-8").splitlines()
    lines = [line.split("#", 1)[0].split("//", 1)[0].strip() for line in raw_lines]
    lines = [line for line in lines if line]

    try:
        species_start = lines.index("ATOMIC_SPECIES") + 1
        lattice_constant_start = lines.index("LATTICE_CONSTANT")
        vectors_start = lines.index("LATTICE_VECTORS") + 1
        positions_start = lines.index("ATOMIC_POSITIONS") + 1
    except ValueError as error:
        raise ValueError(f"ABACUS STRU is missing a required section: {path}") from error
    species = [line.split()[0] for line in lines[species_start:lattice_constant_start]]
    lattice_constant_bohr = float(lines[lattice_constant_start + 1].split()[0])
    vectors_bohr_scaled = np.asarray(
        [[float(value) for value in lines[vectors_start + offset].split()[:3]] for offset in range(3)],
        dtype=float,
    )
    cell_angstrom = vectors_bohr_scaled * lattice_constant_bohr / BOHR_PER_ANGSTROM
    mode = lines[positions_start].strip()
    cursor = positions_start + 1
    output_symbols: list[str] = []
    coordinates: list[list[float]] = []
    move_flags_by_output_index: list[list[int] | None] = []
    while cursor < len(lines):
        element = lines[cursor].split()[0]
        if element not in species:
            raise ValueError(f"ABACUS STRU contains an unlisted element block: {element}")
        cursor += 1
        float(lines[cursor].split()[0])
        cursor += 1
        count = int(lines[cursor].split()[0])
        cursor += 1
        for _ in range(count):
            tokens = lines[cursor].split()
            coordinates.append([float(tokens[0]), float(tokens[1]), float(tokens[2])])
            output_symbols.append(element)
            flags: list[int] | None = None
            if len(tokens) >= 7 and tokens[3].lower() == "m":
                values = tokens[4:7]
                if any(value not in ("0", "1") for value in values):
                    raise ValueError(f"ABACUS STRU move flags must be integer 0 or 1: {path}")
                flags = [int(value) for value in values]
            elif require_move_flags:
                raise ValueError(f"ABACUS STRU is missing explicit m move flags: {path}")
            move_flags_by_output_index.append(flags)
            cursor += 1
    entries = sorted(atom_map["abacus_order"], key=lambda item: int(item["abacus_index"]))
    if len(entries) != len(output_symbols):
        raise ValueError("ABACUS STRU atom count does not match atom map")
    expected_symbols = [str(entry["element"]) for entry in entries]
    if expected_symbols != output_symbols:
        raise ValueError("ABACUS STRU element order differs from atom map")
    coordinates_array = np.asarray(coordinates, dtype=float)
    if mode.lower() != "direct":
        raise ValueError(f"ABACUS 3.10.1 relaxed STRU must use Direct coordinates: {mode}")
    positions_angstrom = coordinates_array @ cell_angstrom
    output_atoms = Atoms(output_symbols, positions=positions_angstrom, cell=cell_angstrom, pbc=True)
    output_ids = [int(entry["atom_id"]) for entry in entries]
    source_ids = [int(value) for value in atom_map["source_atom_ids"]]
    positions_by_id = {
        atom_id: output_atoms[index].position.copy() for index, atom_id in enumerate(output_ids)
    }
    symbols_by_id = {
        atom_id: output_atoms[index].symbol for index, atom_id in enumerate(output_ids)
    }
    ordered = Atoms(
        [symbols_by_id[atom_id] for atom_id in source_ids],
        positions=[positions_by_id[atom_id] for atom_id in source_ids],
        cell=cell_angstrom,
        pbc=True,
    )
    ordered.new_array("atom_id", np.asarray(source_ids, dtype=int))
    if any(flags is not None for flags in move_flags_by_output_index) and not all(
        flags is not None for flags in move_flags_by_output_index
    ):
        raise ValueError(f"ABACUS STRU has incomplete m move flags: {path}")
    if require_move_flags and not move_flags_by_output_index:
        raise ValueError(f"ABACUS STRU has no atoms with move flags: {path}")
    flags_by_id = {
        atom_id: move_flags_by_output_index[index]
        for index, atom_id in enumerate(output_ids)
    }
    ordered_flags = (
        [list(flags_by_id[atom_id]) for atom_id in source_ids]
        if all(flags is not None for flags in move_flags_by_output_index)
        else None
    )
    return ordered, ordered_flags


def _read_stru(path: Path, atom_map: Mapping[str, Any]) -> Atoms:
    return _read_stru_with_constraints(path, atom_map)[0]


def _convergence_marker(text: str, *, stage: Literal["scf", "relax"]) -> tuple[bool | None, bool | None]:
    electronic_markers = list(
        re.finditer(
            r"(?P<success>charge density convergence is achieved)|"
            r"(?P<failure>!!\s+convergence has not been achieved @_@)",
            text,
            re.IGNORECASE,
        )
    )
    electronic = None if not electronic_markers else electronic_markers[-1].group("success") is not None
    if stage == "scf":
        return electronic, None
    ionic_markers = list(
        re.finditer(
            r"(?P<success>(?:Relaxation|Ion relaxation) is converged!)|"
            r"(?P<failure>(?:Relaxation|Ion relaxation) is not converged yet(?:!|\s*\(threshold is))",
            text,
            re.IGNORECASE,
        )
    )
    ionic = None if not ionic_markers else ionic_markers[-1].group("success") is not None
    return electronic, ionic


def _scf_iterations(text: str) -> int | None:
    # ABACUS 3.10.1 records the active ionic and electronic step in the PW
    # log.  The last native record is the last electronic iteration of the
    # last ionic step; taking the maximum would report an earlier ion step.
    matches = list(_PW_ALGORITHM_RE.finditer(text))
    return None if not matches else int(matches[-1].group("elec"))


_ELECTRONIC_MARKER_RE = re.compile(
    r"charge density convergence is achieved|!!\s+convergence has not been achieved @_@",
    re.IGNORECASE,
)
_IONIC_MARKER_RE = re.compile(
    r"(?:Relaxation|Ion relaxation) is (?:converged!|not converged yet(?:!|\s*\(threshold is)[^\n]*)",
    re.IGNORECASE,
)
_FINISH_MARKER_RE = re.compile(r"^\s*(?:Finish Time|Total Time)\s*:.*$", re.IGNORECASE | re.MULTILINE)


def _native_marker_text(text: str) -> dict[str, str | None]:
    electronic = list(_ELECTRONIC_MARKER_RE.finditer(text))
    ionic = list(_IONIC_MARKER_RE.finditer(text))
    finish = list(_FINISH_MARKER_RE.finditer(text))
    return {
        "electronic": electronic[-1].group(0).strip() if electronic else None,
        "ionic": ionic[-1].group(0).strip() if ionic else None,
        "finish": finish[-1].group(0).strip() if finish else None,
    }


def _native_input_value(path: Path, key: str) -> str | None:
    if not path.is_file():
        return None
    pattern = re.compile(r"^\s*" + re.escape(key) + r"\s+(?P<value>[^\s#]+)", re.IGNORECASE)
    matches = [match for match in (pattern.match(line) for line in path.read_text(encoding="utf-8").splitlines()) if match]
    return None if not matches else matches[-1].group("value")


def _native_relax_controls(
    directory: Path,
    method: Mapping[str, Any],
) -> tuple[bool | None, int | None, float | None, Path | None]:
    suffix = str(method["suffix"])
    echo = directory / f"OUT.{suffix}" / "INPUT"
    # The task INPUT records requested values.  Only the native echoed INPUT
    # records values accepted by the completed ABACUS run.
    candidates = [echo] if echo.is_file() else []
    relax_new: bool | None = None
    relax_nmax: int | None = None
    force_threshold: float | None = None
    for path in candidates:
        value = _native_input_value(path, "relax_new")
        if value is not None:
            if value not in ("0", "1"):
                raise ValueError("native ABACUS relax_new must be 0 or 1")
            relax_new = value == "1"
            break
    for path in candidates:
        value = _native_input_value(path, "relax_nmax")
        if value is not None:
            try:
                relax_nmax = int(value)
            except ValueError as error:
                raise ValueError("native ABACUS relax_nmax must be an integer") from error
            break
    for path in candidates:
        value = _native_input_value(path, "force_thr_ev")
        if value is not None:
            force_threshold = _number(value)
            break
    return relax_new, relax_nmax, force_threshold, echo if echo.is_file() else None


def _atoms_match(left: Atoms, right: Atoms, *, tolerance: float = 1.0e-7) -> bool:
    if left.get_chemical_symbols() != right.get_chemical_symbols():
        return False
    if "atom_id" in left.arrays and "atom_id" in right.arrays:
        if left.arrays["atom_id"].tolist() != right.arrays["atom_id"].tolist():
            return False
    if not np.allclose(left.cell.array, right.cell.array, rtol=0.0, atol=tolerance):
        return False
    delta_frac = right.get_scaled_positions(wrap=False) - left.get_scaled_positions(wrap=False)
    delta_frac -= np.rint(delta_frac)
    delta_cart = delta_frac @ np.asarray(left.cell.array, dtype=float)
    return bool(np.all(np.abs(delta_cart) <= tolerance))


def _frozen_dofs_match(initial: Atoms, final: Atoms, move_flags: Sequence[Sequence[int]]) -> bool:
    if len(move_flags) != len(initial) or len(final) != len(initial):
        return False
    initial_frac = initial.get_scaled_positions(wrap=False)
    final_frac = final.get_scaled_positions(wrap=False)
    delta_frac = final_frac - initial_frac
    delta_frac -= np.rint(delta_frac)
    delta_cart = delta_frac @ np.asarray(initial.cell.array, dtype=float)
    flags = np.asarray(move_flags, dtype=int)
    frozen = flags == 0
    return bool(np.all(np.abs(delta_cart[frozen]) <= 1.0e-7))


def _relaxation_record(
    *,
    directory: Path,
    method: Mapping[str, Any],
    text: str,
    source_atoms: Atoms,
    final_atoms: Atoms,
    forces: Sequence[Sequence[float]],
    move_flags: list[list[int]],
    ionic: bool | None,
    electronic: bool | None,
    source_files: Mapping[str, str],
) -> dict[str, Any]:
    relax_new, native_nmax, native_force_threshold, native_echo = _native_relax_controls(directory, method)
    ionic_steps = [int(match.group("ion")) for match in _PW_ALGORITHM_RE.finditer(text)]
    last_ionic_step = max(ionic_steps) if ionic_steps else None
    markers = _native_marker_text(text)
    native_completed = bool(re.search(r"^\s*Finish Time\s*:", text, re.IGNORECASE | re.MULTILINE))
    method_parameters = method.get("parameters")
    if not isinstance(method_parameters, Mapping):
        raise ValueError("relax method.json is missing parameters")
    threshold_value = method_parameters.get("force_thr_eV_per_A")
    if threshold_value is None or not np.isfinite(float(threshold_value)) or float(threshold_value) <= 0.0:
        raise ValueError("relax method.json requires a positive force_thr_eV_per_A")
    force_threshold = float(threshold_value)
    method_nmax_value = method_parameters.get("relax_nmax")
    if (
        method_nmax_value is None
        or isinstance(method_nmax_value, bool)
        or not isinstance(method_nmax_value, (int, np.integer))
        or int(method_nmax_value) <= 0
    ):
        raise ValueError("relax method.json requires a positive integer relax_nmax")
    method_nmax = int(method_nmax_value)
    native_controls_bound = bool(
        native_echo is not None
        and relax_new is not None
        and native_nmax is not None
        and native_force_threshold is not None
    )
    if native_echo is not None and native_nmax is not None and native_nmax != method_nmax:
        raise ValueError("native relax_nmax differs from method.json relax_nmax")
    if (
        native_echo is not None
        and native_force_threshold is not None
        and not np.isclose(native_force_threshold, force_threshold, rtol=1.0e-8, atol=1.0e-12)
    ):
        raise ValueError("native force threshold differs from method.json force_thr_eV_per_A")
    # The task INPUT is a request, while OUT.<suffix>/INPUT is ABACUS's
    # echoed runtime configuration.  Without the echo, the native controls
    # cannot be promoted as executed values.
    if native_echo is None:
        relax_new = None
        native_nmax = None
        native_force_threshold = None
    force_array = np.asarray(forces, dtype=float)
    flags = np.asarray(move_flags, dtype=bool)
    max_all_force = float(np.max(np.abs(force_array)))
    max_free_force = float(np.max(np.abs(force_array[flags])))
    fixed_cell_verified = bool(np.allclose(source_atoms.cell.array, final_atoms.cell.array, rtol=0.0, atol=1.0e-7))
    frozen_dofs_verified = _frozen_dofs_match(source_atoms, final_atoms, move_flags)
    last_snapshot_path = None
    last_snapshot_atoms = None
    if last_ionic_step is not None:
        candidate = directory / f"OUT.{method['suffix']}" / f"STRU_ION{last_ionic_step}_D"
        if candidate.is_file():
            last_snapshot_path = candidate
            last_snapshot_atoms = _read_stru(candidate, json.loads(Path(source_files["STRU.atom-map.json"]).read_text(encoding="utf-8")))
    # ABACUS writes STRU_ION<n>_D and STRU_ION_D after proposing the next
    # ionic geometry.  That snapshot is an evaluated geometry only for a
    # converged relax_new step whose final geometry is bound to it.
    evaluation_bound = bool(ionic is True and relax_new is True)
    final_geometry_matches = bool(
        evaluation_bound
        and last_snapshot_atoms is not None
        and _atoms_match(final_atoms, last_snapshot_atoms)
    )
    if final_geometry_matches:
        final_geometry_role = "last_evaluated_ionic_step"
    elif ionic is False:
        final_geometry_role = "unevaluated_proposed_next_geometry"
    else:
        final_geometry_role = "native_final_geometry_not_bound_to_last_evaluation"
    if not native_completed:
        stop_reason = "native_completion_unconfirmed"
    elif electronic is False:
        stop_reason = "electronic_not_converged"
    elif electronic is not True or ionic is None:
        stop_reason = "native_completion_unconfirmed"
    elif ionic is True:
        stop_reason = "ionic_converged"
    elif native_nmax is not None and last_ionic_step is not None and last_ionic_step >= native_nmax:
        stop_reason = "ionic_iteration_limit"
    else:
        stop_reason = "not_converged"
    geometry_promotable = bool(
        native_completed
        and relax_new is True
        and electronic is True
        and ionic is True
        and native_controls_bound
        and native_nmax is not None
        and native_force_threshold is not None
        and max_free_force <= force_threshold
        and fixed_cell_verified
        and frozen_dofs_verified
        and final_geometry_matches
    )
    native_markers = dict(markers)
    native_markers["native_echo"] = str(native_echo) if native_echo is not None else None
    native_markers["native_controls_bound"] = native_controls_bound
    native_markers["last_ionic_snapshot"] = str(last_snapshot_path) if last_snapshot_path is not None else None
    native_markers["last_evaluated_structure"] = (
        str(last_snapshot_path) if final_geometry_matches and last_snapshot_path is not None else None
    )
    return {
        "schema": "mlcc.fixed-cell-relaxation-result.v1",
        "cell_constraint": "fixed_cell",
        "ionic_constraints": {
            "schema": "mlcc.ionic-constraints.v1",
            "coordinate_basis": "cartesian",
            "atom_ids": [int(value) for value in source_atoms.arrays["atom_id"]],
            "move_flags": move_flags,
            "relax_new": True,
            "origin": str(method.get("ionic_constraints", {}).get("origin", "legacy_all_free"))
            if isinstance(method.get("ionic_constraints"), Mapping)
            else "legacy_all_free",
        },
        "relax_new": relax_new,
        "ionic_steps": last_ionic_step,
        "relax_nmax": native_nmax,
        "method_relax_nmax": method_nmax,
        "native_stop_reason": stop_reason,
        "native_marker_text": native_markers,
        "electronic_converged": electronic,
        "ionic_converged": ionic,
        "native_completed": native_completed,
        "force_metric": "max_abs_movable_cartesian_component",
        "force_threshold_eV_per_A": force_threshold,
        "native_force_threshold_eV_per_A": native_force_threshold,
        "max_free_force_component_eV_per_A": max_free_force,
        "max_all_force_component_eV_per_A": max_all_force,
        "fixed_cell_verified": fixed_cell_verified,
        "frozen_dofs_verified": frozen_dofs_verified,
        "final_geometry_matches_last_evaluation": final_geometry_matches,
        "final_geometry_role": final_geometry_role,
        "geometry_promotable": geometry_promotable,
    }


def parse_abacus_outputs(
    task_dir: str | Path,
    *,
    source_model: ModelArtifacts,
    stage: Literal["scf", "relax"],
    log_path: str | Path | None = None,
    final_stru_path: str | Path | None = None,
    mapping_path: str | Path | None = None,
    occupations: Literal["smearing", "fixed"] | None = None,
) -> AbacusResult:
    """Parse one ABACUS 3.10.1 result in source atom order.

    The caller supplies the exact log and, for relaxation, the exact final
    structure.  If omitted, paths are derived from the suffix recorded in
    ``method.json``.  Missing energy, force, stress, or relaxed structure data
    raises the direct parser error instead of creating placeholder values.
    """

    directory = Path(task_dir).resolve()
    method = _read_method_record(directory)
    if stage != method["stage"]:
        raise ValueError(f"ABACUS output stage {stage} differs from method.json stage {method['stage']}")
    suffix = str(method["suffix"])
    resolved_occupations = _resolve_occupations(directory, method, occupations)
    source_atoms, _, _ = _source_atoms_from_model(source_model)
    map_file = Path(mapping_path) if mapping_path is not None else directory / "STRU.atom-map.json"
    atom_map = json.loads(map_file.read_text(encoding="utf-8"))
    source_ids = [int(value) for value in atom_map["source_atom_ids"]]
    if source_ids != [int(value) for value in source_atoms.arrays["atom_id"]]:
        raise ValueError("ABACUS atom map source IDs differ from source model")
    log_file = Path(log_path) if log_path is not None else directory / f"OUT.{suffix}" / f"running_{stage}.log"
    text = log_file.read_text(encoding="utf-8")
    lines = text.splitlines()
    energy = _parse_energy(text)
    energy_sigma0_eV, entropy_minus_TS_eV = _parse_energy_records(text)
    forces = _parse_forces(lines, atom_map)
    stress_kbar, stress_GPa = _parse_stress(lines)
    electronic, ionic = _convergence_marker(text, stage=stage)
    iterations = _scf_iterations(text)
    total_magnetization = _parse_total_magnetization(text)
    if stage == "relax":
        structure_file = Path(final_stru_path) if final_stru_path is not None else directory / f"OUT.{suffix}" / "STRU_ION_D"
        final_atoms = _read_stru(structure_file, atom_map)
        source_atoms, source_move_flags = _read_stru_with_constraints(
            directory / "STRU", atom_map, require_move_flags=True
        )
        if source_move_flags is None or not any(value for row in source_move_flags for value in row):
            raise ValueError("ABACUS relax STRU must leave at least one movable degree of freedom")
        actual_normalized = _normalize_ionic_constraints(
            source_atoms,
            {
                "coordinate_basis": "cartesian",
                "atom_ids": [int(value) for value in source_atoms.arrays["atom_id"]],
                "move_flags": source_move_flags,
            },
            origin="native_stru",
        )
        saved_constraints = method.get("ionic_constraints")
        if saved_constraints is not None:
            saved_normalized = _normalize_ionic_constraints(
                source_atoms,
                saved_constraints,
                origin=str(saved_constraints.get("origin", "explicit_request"))
                if isinstance(saved_constraints, Mapping)
                else "explicit_request",
            )
            if (
                saved_normalized["atom_ids"] != actual_normalized["atom_ids"]
                or saved_normalized["move_flags"] != actual_normalized["move_flags"]
            ):
                raise ValueError("saved ionic_constraints differ from original ABACUS STRU move flags")
    else:
        final_atoms = source_atoms.copy()
    source_files = {
        f"running_{stage}.log": str(log_file),
        "STRU.atom-map.json": str(map_file),
        "method.json": str(directory / "method.json"),
        "INPUT": str(directory / "INPUT"),
        "STRU": str(directory / "STRU"),
    }
    if stage == "relax":
        source_files["STRU_ION_D"] = str(
            Path(final_stru_path) if final_stru_path is not None else directory / f"OUT.{suffix}" / "STRU_ION_D"
        )
        native_echo = directory / f"OUT.{suffix}" / "INPUT"
        if native_echo.is_file():
            source_files["native_INPUT"] = str(native_echo)
        relaxation = _relaxation_record(
            directory=directory,
            method=method,
            text=text,
            source_atoms=source_atoms,
            final_atoms=final_atoms,
            forces=forces,
            move_flags=source_move_flags,
            ionic=ionic,
            electronic=electronic,
            source_files=source_files,
        )
    else:
        relaxation = None
    native_completed = bool(
        re.search(r"^\s*Finish Time\s*:", text, re.IGNORECASE | re.MULTILINE)
    )
    return AbacusResult(
        energy_eV=energy,
        energy_sigma0_eV=energy_sigma0_eV,
        entropy_minus_TS_eV=entropy_minus_TS_eV,
        forces_eV_per_A=forces,
        stress_kbar=stress_kbar,
        stress_GPa=stress_GPa,
        atom_ids=source_ids,
        final_atoms=final_atoms,
        electronic_converged=electronic,
        ionic_converged=ionic,
        scf_iterations=iterations,
        source_files=source_files,
        stage=stage,
        occupations=resolved_occupations,
        total_magnetization_muB=total_magnetization,
        native_completed=native_completed,
        relaxation=relaxation,
    )

