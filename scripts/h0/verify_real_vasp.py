"""Verify the MLCC VASP parser against collected real VASP output.

This is a read-only regression check. It reads completed task directories,
calls the real ``parse_vasp_outputs`` adapter, and compares its result with
raw OUTCAR/XML/CONTCAR records. It does not submit work, assemble POTCAR, or
construct synthetic scientific data.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys

import numpy as np
from pymatgen.core import Structure
from pymatgen.io.vasp.outputs import Vasprun


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "mlcc-agent" / "src"))

from mlcc.vasp import parse_vasp_outputs  # noqa: E402


FLOAT = r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[Ee][-+]?\d+)?"
KBAR_TO_GPA = 0.1
VOIGT_ORDER = ("xx", "yy", "zz", "yz", "xz", "xy")
TOTEN_RE = re.compile(
    rf"free\s+energy\s+TOTEN\s*=\s*({FLOAT})\s+eV",
    re.IGNORECASE,
)
SIGMA_RE = re.compile(
    rf"energy\s+without\s+entropy\s*=\s*({FLOAT})\s+"
    rf"energy\(sigma->0\)\s*=\s*({FLOAT})",
    re.IGNORECASE,
)
STRESS_RE = re.compile(r"^\s*in\s+kB\s+(.+)$", re.MULTILINE)


def _last_match(pattern: re.Pattern[str], text: str, label: str) -> tuple[str, ...]:
    matches = pattern.findall(text)
    if not matches:
        raise AssertionError(f"OUTCAR has no {label} record")
    match = matches[-1]
    return (match,) if isinstance(match, str) else tuple(match)


def _periodic_fractional_delta(left: np.ndarray, right: np.ndarray) -> np.ndarray:
    delta = np.asarray(left, dtype=float) - np.asarray(right, dtype=float)
    return delta - np.rint(delta)


def _expected_stress(raw_kbar: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    raw = np.asarray(raw_kbar, dtype=float)
    if raw.shape != (3, 3):
        raise AssertionError(f"expected a 3x3 stress matrix from vasprun.xml, got {raw.shape}")
    compression = raw * KBAR_TO_GPA
    tensile = -compression
    compression_voigt = np.array(
        [compression[0, 0], compression[1, 1], compression[2, 2],
         compression[1, 2], compression[0, 2], compression[0, 1]],
        dtype=float,
    )
    tensile_voigt = -compression_voigt
    return compression, tensile, compression_voigt, tensile_voigt


def verify_task(task_dir: Path) -> dict[str, object]:
    task_dir = task_dir.resolve()
    task = json.loads((task_dir / "task.json").read_text(encoding="utf-8"))
    method = json.loads((task_dir / "method.json").read_text(encoding="utf-8"))
    assert task["status"] == "COMPLETED", task["status"]
    assert task["exit_code"] == "0:0", task["exit_code"]
    assert method["engine"] == "vasp", method["engine"]

    stage = method["stage"]
    parsed = parse_vasp_outputs(task_dir, stage=stage)

    outcar_text = (task_dir / "OUTCAR").read_text(encoding="utf-8")
    toten = float(_last_match(TOTEN_RE, outcar_text, "free-energy TOTEN")[0])
    _, sigma_zero = _last_match(SIGMA_RE, outcar_text, "sigma->0 energy")
    sigma_zero = float(sigma_zero)
    np.testing.assert_allclose(parsed.e_fr_energy, toten, rtol=0.0, atol=1e-8)
    np.testing.assert_allclose(parsed.e_0_energy, sigma_zero, rtol=0.0, atol=1e-8)

    vasprun = Vasprun(
        str(task_dir / "vasprun.xml"),
        parse_dos=False,
        parse_eigen=False,
        parse_potcar_file=False,
    )
    final_step = vasprun.ionic_steps[-1]
    np.testing.assert_allclose(parsed.e_fr_energy, final_step["e_fr_energy"], rtol=0.0, atol=1e-12)
    np.testing.assert_allclose(parsed.e_0_energy, vasprun.final_energy, rtol=0.0, atol=1e-12)
    np.testing.assert_allclose(parsed.e_wo_entrp, final_step["e_wo_entrp"], rtol=0.0, atol=1e-12)

    contcar = Structure.from_file(str(task_dir / "CONTCAR"))
    xml_final = vasprun.final_structure
    assert len(xml_final) == len(contcar), (len(xml_final), len(contcar))
    assert [site.specie.symbol for site in xml_final] == [site.specie.symbol for site in contcar]
    np.testing.assert_allclose(xml_final.lattice.matrix, contcar.lattice.matrix, rtol=0.0, atol=1e-8)
    np.testing.assert_allclose(
        _periodic_fractional_delta(xml_final.frac_coords, contcar.frac_coords),
        0.0,
        rtol=0.0,
        atol=1e-8,
    )
    assert parsed.final_atoms.get_chemical_symbols() == [site.specie.symbol for site in contcar]
    np.testing.assert_allclose(parsed.final_atoms.cell.array, contcar.lattice.matrix, rtol=0.0, atol=1e-8)
    np.testing.assert_allclose(
        _periodic_fractional_delta(parsed.final_atoms.get_scaled_positions(wrap=False), contcar.frac_coords),
        0.0,
        rtol=0.0,
        atol=1e-8,
    )

    raw_stress_kbar = np.asarray(final_step["stress"], dtype=float)
    compression, tensile, compression_voigt, tensile_voigt = _expected_stress(raw_stress_kbar)
    # The printed VASP stress is a physical symmetric tensor. OUTCAR keeps
    # only five decimal places here, so compare it to XML at that precision.
    stress_lines = STRESS_RE.findall(outcar_text)
    if not stress_lines:
        raise AssertionError("OUTCAR has no final in kB stress record")
    printed_stress = [float(value) for value in stress_lines[-1].split()]
    assert len(printed_stress) == 6, printed_stress
    xx, yy, zz, xy, yz, xz = printed_stress
    printed_matrix = np.array([[xx, xy, xz], [xy, yy, yz], [xz, yz, zz]], dtype=float)
    np.testing.assert_allclose(raw_stress_kbar, printed_matrix, rtol=0.0, atol=2e-5)
    np.testing.assert_allclose(raw_stress_kbar, raw_stress_kbar.T, rtol=0.0, atol=2e-5)
    assert VOIGT_ORDER == ("xx", "yy", "zz", "yz", "xz", "xy")
    np.testing.assert_allclose(parsed.stress_vasp_compression_positive_GPa, compression, rtol=0.0, atol=1e-12)
    np.testing.assert_allclose(parsed.stress_tensile_positive_GPa, tensile, rtol=0.0, atol=1e-12)
    np.testing.assert_allclose(parsed.stress_voigt_vasp_compression_positive_GPa, compression_voigt, rtol=0.0, atol=1e-12)
    np.testing.assert_allclose(parsed.stress_voigt_tensile_positive_GPa, tensile_voigt, rtol=0.0, atol=1e-12)

    mapping = json.loads((task_dir / "POSCAR.atom-map.json").read_text(encoding="utf-8"))
    assert parsed.atom_ids == [int(value) for value in mapping["source_atom_ids"]]

    return {
        "task_id": task["task_id"],
        "task_path": str(task_dir),
        "scheduler_job_id": task["scheduler_job_id"],
        "scheduler_status": task["status"],
        "exit_code": task["exit_code"],
        "stage": stage,
        "fixture": bool(task["fixture"]),
        "assertions": {
            "scheduler_completed": True,
            "outcar_toten_matches_e_fr_energy": True,
            "outcar_sigma_zero_matches_e_0_energy": True,
            "xml_energy_fields_match_parser": True,
            "xml_contcar_atoms_and_lattice_match": True,
            "outcar_xml_stress_kbar_match": True,
            "stress_gpa_sign_and_voigt_match": True,
            "source_atom_ids_match": True,
        },
        "raw": {
            "outcar_last_toten_eV": toten,
            "outcar_last_energy_sigma_zero_eV": sigma_zero,
            "vasprun_final_e_fr_energy_eV": float(final_step["e_fr_energy"]),
            "vasprun_final_e_0_energy_eV": float(vasprun.final_energy),
            "vasprun_final_e_wo_entrp_eV": float(final_step["e_wo_entrp"]),
            "stress_kbar": raw_stress_kbar.tolist(),
            "xml_contcar_max_fractional_delta": float(
                np.max(np.abs(_periodic_fractional_delta(xml_final.frac_coords, contcar.frac_coords)))
            ),
        },
        "parsed": {
            "e_fr_energy_eV": parsed.e_fr_energy,
            "e_0_energy_eV": parsed.e_0_energy,
            "e_wo_entrp_eV": parsed.e_wo_entrp,
            "stress_vasp_compression_positive_GPa": parsed.stress_vasp_compression_positive_GPa,
            "stress_tensile_positive_GPa": parsed.stress_tensile_positive_GPa,
            "stress_voigt_order": list(VOIGT_ORDER),
            "stress_voigt_vasp_compression_positive_GPa": parsed.stress_voigt_vasp_compression_positive_GPa,
            "stress_voigt_tensile_positive_GPa": parsed.stress_voigt_tensile_positive_GPa,
            "atom_ids": parsed.atom_ids,
            "electronic_converged": parsed.electronic_converged,
            "ionic_converged": parsed.ionic_converged,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--task",
        action="append",
        type=Path,
        required=True,
        help="completed local VASP task directory; repeat for more than one task",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=ROOT / "workspace" / "reports" / "h0" / "real-vasp-regression.json",
        help="JSON report path (default: workspace/reports/h0/real-vasp-regression.json)",
    )
    args = parser.parse_args()
    tasks = [path if path.is_absolute() else ROOT / path for path in args.task]
    report_path = args.report if args.report.is_absolute() else ROOT / args.report
    results = [verify_task(task) for task in tasks]
    report = {
        "schema": "mlcc.h0.real-vasp-regression.v1",
        "verified_at_utc": datetime.now(timezone.utc).isoformat(),
        "command": [str(value) for value in sys.argv],
        "working_directory": str(Path.cwd().resolve()),
        "python": sys.executable,
        "parser_module": str(Path(sys.modules["mlcc.vasp"].__file__).resolve()),
        "scientific_data_source": "collected real VASP XML/OUTCAR/CONTCAR",
        "synthetic_data": False,
        "potcar_read": False,
        "tasks": results,
        "all_passed": True,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
