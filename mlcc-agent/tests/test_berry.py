"""ABACUS-native Berry parser checks.

These tests never manufacture a positive Berry result.  The positive path and
all negative mutations are applied to the native v100 task copied back to the
workspace.  Until that task exists, pytest reports the missing evidence by
skipping with an explicit message.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil

import pytest

from mlcc.berry import parse_berry_outputs
from mlcc.modeling import read_model_artifacts


_DEFAULT_NATIVE_TASK = Path("D:/project/mlcc/workspace/tasks/p5-czo-berry-gdir1-v001")


def _native_task() -> Path:
    configured = os.environ.get("MLCC_BERRY_NATIVE_TASK")
    path = Path(configured) if configured else _DEFAULT_NATIVE_TASK
    if not path.is_dir():
        pytest.skip(
            "real v100 ABACUS Berry fixture is required: "
            f"{path} (set MLCC_BERRY_NATIVE_TASK to the collected task directory)"
        )
    return path


def _native_context() -> tuple[Path, object, dict[str, object]]:
    directory = _native_task()
    method = json.loads((directory / "method.json").read_text(encoding="utf-8"))
    task = json.loads((directory / "task.json").read_text(encoding="utf-8"))
    model_path = Path(task["model_path"])
    if not model_path.is_dir():
        pytest.skip(f"real Berry fixture model is required: {model_path}")
    model = read_model_artifacts(model_path)
    berry = method["berry"]
    expected = {
        "gdir": berry["gdir"],
        "pw_diag_thr": berry["pw_diag_thr"],
        "reference_task_id": berry["source_reference_task_id"],
        "kpoints": method["kpoints"],
    }
    return directory, model, expected


def _copy_native_task(tmp_path: Path) -> tuple[Path, object, dict[str, object]]:
    directory, model, expected = _native_context()
    copied = tmp_path / directory.name
    shutil.copytree(directory, copied)
    return copied, model, expected


def _replace_input_value(path: Path, key: str, value: str) -> None:
    lines = path.read_text(encoding="utf-8").splitlines()
    pattern = re.compile(rf"^(\s*{re.escape(key)}\s+)\S+(.*)$", re.IGNORECASE)
    for index, line in enumerate(lines):
        if pattern.match(line):
            lines[index] = pattern.sub(rf"\g<1>{value}\g<2>", line)
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")
            return
    raise AssertionError(f"native INPUT key not found: {key}")


def _require_cpu_fixture(directory: Path) -> dict[str, object]:
    method = json.loads((directory / "method.json").read_text(encoding="utf-8"))
    if str(method.get("device", "")).lower() != "cpu":
        pytest.skip("real CPU Berry fixture is required for the device-binding negative tests")
    return method


def test_parse_berry_native_task_preserves_unbranched_record():
    directory, model, expected = _native_context()
    result = parse_berry_outputs(directory, source_model=model, expected=expected)

    assert result["schema"] == "mlcc.abacus-polarization.v1"
    assert result["engine_version"] == "3.10.1"
    assert result["nspin"] == 1
    assert result["nscf_completed"] is True
    assert result["reference_scf_status"] == "not_checked_by_nscf_parser"
    assert result["branch_status"] == "not_unwrapped"
    assert result["branch_unwrapped"] is False
    assert result["scientific_qualification"] is False
    assert result["numerical_qualification"] is False
    assert result["production_qualification"] is False
    assert result["device"] == "cpu"
    assert "implementation_id" not in result
    assert "binary_source" not in result
    assert set(result["native_polarization_rows"]) == {"e_per_omega_bohr", "e_per_bohr2", "c_per_m2"}


def test_parse_berry_accepts_periodic_equivalent_native_direct_coordinate(tmp_path: Path):
    directory, model, expected = _copy_native_task(tmp_path)
    method = json.loads((directory / "method.json").read_text(encoding="utf-8"))
    log = directory / f"OUT.{method['suffix']}" / "running_nscf.log"
    text = log.read_text(encoding="utf-8")
    mutated, count = re.subn(
        r"(?im)^(taud_Zr2\s+0\.5000000000\s+)0\.0000000000(?=\s+0\.0000000000\s+0\.0000)",
        r"\g<1>1.0000000000",
        text,
        count=1,
    )
    assert count == 1
    log.write_text(mutated, encoding="utf-8")
    result = parse_berry_outputs(directory, source_model=model, expected=expected)
    assert result["nscf_completed"] is True


def test_parse_berry_rejects_native_polarization_quantum_mutation(tmp_path: Path):
    directory, model, expected = _copy_native_task(tmp_path)
    method = json.loads((directory / "method.json").read_text(encoding="utf-8"))
    log = directory / f"OUT.{method['suffix']}" / "running_nscf.log"
    text = log.read_text(encoding="utf-8")
    mutated, count = re.subn(
        r"(?im)^(\s*P\s*=\s+0\.0000048\s+\(mod\s+)0\.6943717",
        r"\g<1>0.5000000",
        text,
        count=1,
    )
    assert count == 1
    log.write_text(mutated, encoding="utf-8")
    with pytest.raises(ValueError, match="quantum|modulo"):
        parse_berry_outputs(directory, source_model=model, expected=expected)


def test_parse_berry_rejects_native_print_precision_mutation(tmp_path: Path):
    directory, model, expected = _copy_native_task(tmp_path)
    method = json.loads((directory / "method.json").read_text(encoding="utf-8"))
    log = directory / f"OUT.{method['suffix']}" / "running_nscf.log"
    text = log.read_text(encoding="utf-8")
    mutated, count = re.subn(
        r"(?im)^(\s*P\s*=\s+)0\.0001460(?=\s+\(mod\s+)",
        r"\g<1>0.000146",
        text,
        count=1,
    )
    assert count == 1
    log.write_text(mutated, encoding="utf-8")
    with pytest.raises(ValueError, match="fixed 7-decimal"):
        parse_berry_outputs(directory, source_model=model, expected=expected)


def test_parse_berry_rejects_native_phase_precision_mutation(tmp_path: Path):
    directory, model, expected = _copy_native_task(tmp_path)
    method = json.loads((directory / "method.json").read_text(encoding="utf-8"))
    log = directory / f"OUT.{method['suffix']}" / "running_nscf.log"
    text = log.read_text(encoding="utf-8")
    mutated, count = re.subn(
        r"(?im)^(\s*Electronic Phase:\s+)0\.00001$",
        r"\g<1>0.0000",
        text,
        count=1,
    )
    assert count == 1
    log.write_text(mutated, encoding="utf-8")
    with pytest.raises(ValueError, match="fixed 5-decimal"):
        parse_berry_outputs(directory, source_model=model, expected=expected)


def test_parse_berry_rejects_top_input_threshold_mutation(tmp_path: Path):
    directory, model, expected = _copy_native_task(tmp_path)
    _replace_input_value(directory / "INPUT", "pw_diag_thr", "2e-3")
    with pytest.raises(ValueError):
        parse_berry_outputs(directory, source_model=model, expected=expected)


def test_parse_berry_rejects_native_input_echo_mutation(tmp_path: Path):
    directory, model, expected = _copy_native_task(tmp_path)
    method = json.loads((directory / "method.json").read_text(encoding="utf-8"))
    output_input = directory / f"OUT.{method['suffix']}" / "INPUT"
    _replace_input_value(output_input, "ecutwfc", "999")
    with pytest.raises(ValueError, match="native OUT INPUT"):
        parse_berry_outputs(directory, source_model=model, expected=expected)


def test_parse_berry_rejects_kpoint_pools(tmp_path: Path):
    directory, model, expected = _copy_native_task(tmp_path)
    method = json.loads((directory / "method.json").read_text(encoding="utf-8"))
    _replace_input_value(directory / f"OUT.{method['suffix']}" / "INPUT", "kpar", "2")
    with pytest.raises(ValueError, match="kpar=1"):
        parse_berry_outputs(directory, source_model=model, expected=expected)


def test_parse_berry_rejects_non_cpu_method_device(tmp_path: Path):
    directory, model, expected = _copy_native_task(tmp_path)
    method = _require_cpu_fixture(directory)
    method["device"] = "gpu"
    (directory / "method.json").write_text(json.dumps(method, indent=2) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="device.*cpu|CPU"):
        parse_berry_outputs(directory, source_model=model, expected=expected)


def test_parse_berry_rejects_gpu_without_registered_candidate_protocol(tmp_path: Path):
    directory, model, expected = _copy_native_task(tmp_path)
    method = _require_cpu_fixture(directory)
    method["device"] = "gpu"
    method["berry"]["implementation_id"] = "mlcc-abacus-3.10.1-berry-gpu-v001"
    method["berry"]["gpu_build"] = {
        "implementation_id": "mlcc-abacus-3.10.1-berry-gpu-v001",
        "binary": "/opt/abacus-berry-gpu",
        "scope": "single_mpi_non_soc_nspin1",
    }
    method["berry"]["binary_source"] = "/opt/abacus-berry-gpu"
    (directory / "method.json").write_text(json.dumps(method, indent=2) + "\n", encoding="utf-8")
    _replace_input_value(directory / "INPUT", "device", "gpu")
    output_input = directory / f"OUT.{method['suffix']}" / "INPUT"
    _replace_input_value(output_input, "device", "gpu")
    stdout = directory / "stdout.log"
    text = stdout.read_text(encoding="utf-8")
    mutated, count = re.subn(
        r"(?im)^(\s*RUNNING\s+WITH\s+DEVICE\s*:\s*)CPU\b",
        r"\1GPU",
        text,
        count=1,
    )
    assert count == 1
    stdout.write_text(mutated, encoding="utf-8")
    with pytest.raises(ValueError, match="candidate build protocol"):
        parse_berry_outputs(directory, source_model=model, expected=expected)


def test_parse_berry_rejects_unknown_gpu_candidate_id(tmp_path: Path):
    directory, model, expected = _copy_native_task(tmp_path)
    method = _require_cpu_fixture(directory)
    method["device"] = "gpu"
    method["berry"]["implementation_id"] = "unregistered-berry-build"
    method["berry"]["gpu_build"] = {
        "implementation_id": "unregistered-berry-build",
        "binary": "/opt/abacus-berry-gpu",
        "scope": "single_mpi_non_soc_nspin1",
    }
    method["berry"]["binary_source"] = "/opt/abacus-berry-gpu"
    (directory / "method.json").write_text(json.dumps(method, indent=2) + "\n", encoding="utf-8")
    _replace_input_value(directory / "INPUT", "device", "gpu")
    output_input = directory / f"OUT.{method['suffix']}" / "INPUT"
    _replace_input_value(output_input, "device", "gpu")
    stdout = directory / "stdout.log"
    text = stdout.read_text(encoding="utf-8")
    mutated, count = re.subn(
        r"(?im)^(\s*RUNNING\s+WITH\s+DEVICE\s*:\s*)CPU\b",
        r"\1GPU",
        text,
        count=1,
    )
    assert count == 1
    stdout.write_text(mutated, encoding="utf-8")
    with pytest.raises(ValueError, match="supported candidate"):
        parse_berry_outputs(directory, source_model=model, expected=expected)


def test_parse_berry_rejects_non_cpu_top_input_device(tmp_path: Path):
    directory, model, expected = _copy_native_task(tmp_path)
    _require_cpu_fixture(directory)
    _replace_input_value(directory / "INPUT", "device", "gpu")
    with pytest.raises(ValueError, match="device|CPU"):
        parse_berry_outputs(directory, source_model=model, expected=expected)


def test_parse_berry_rejects_non_cpu_native_input_device(tmp_path: Path):
    directory, model, expected = _copy_native_task(tmp_path)
    method = _require_cpu_fixture(directory)
    output_input = directory / f"OUT.{method['suffix']}" / "INPUT"
    _replace_input_value(output_input, "device", "gpu")
    with pytest.raises(ValueError, match="device|CPU"):
        parse_berry_outputs(directory, source_model=model, expected=expected)


def test_parse_berry_rejects_non_cpu_stdout_marker(tmp_path: Path):
    directory, model, expected = _copy_native_task(tmp_path)
    _require_cpu_fixture(directory)
    stdout = directory / "stdout.log"
    text = stdout.read_text(encoding="utf-8")
    mutated, count = re.subn(
        r"(?im)^(\s*RUNNING\s+WITH\s+DEVICE\s*:\s*)CPU\b",
        r"\1GPU",
        text,
        count=1,
    )
    assert count == 1
    stdout.write_text(mutated, encoding="utf-8")
    with pytest.raises(ValueError, match="stdout|CPU"):
        parse_berry_outputs(directory, source_model=model, expected=expected)


def test_parse_berry_rejects_geometry_mutation(tmp_path: Path):
    directory, model, expected = _copy_native_task(tmp_path)
    stru = directory / "STRU"
    text = stru.read_text(encoding="utf-8")
    mutated, count = re.subn(
        r"(?m)^(\s*)"
        r"([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s+"
        r"([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s+"
        r"([+-]?(?:\d+(?:\.\d*)?|\.\d+))(\s+m\b)",
        lambda match: f"{match.group(1)}{float(match.group(2)) + 0.01:.16g} {match.group(3)} {match.group(4)}{match.group(5)}",
        text,
        count=1,
    )
    assert count == 1
    stru.write_text(mutated, encoding="utf-8")
    with pytest.raises(ValueError, match="geometry|coordinates|lattice"):
        parse_berry_outputs(directory, source_model=model, expected=expected)


def test_parse_berry_rejects_charge_density_removal(tmp_path: Path):
    directory, model, expected = _copy_native_task(tmp_path)
    method = json.loads((directory / "method.json").read_text(encoding="utf-8"))
    charge_file = directory / method["berry"]["charge_density"]["files"][0]
    charge_file.unlink()
    with pytest.raises(ValueError, match="charge-density"):
        parse_berry_outputs(directory, source_model=model, expected=expected)


def test_parse_berry_rejects_native_charge_read_path_mutation(tmp_path: Path):
    directory, model, expected = _copy_native_task(tmp_path)
    method = _require_cpu_fixture(directory)
    log = directory / f"OUT.{method['suffix']}" / "running_nscf.log"
    text = log.read_text(encoding="utf-8")
    mutated, count = re.subn(
        r"(?im)^(\s*Read\s+in\s+the\s+charge\s+density\s*:\s*)\S+",
        r"\1./WRONG_CHG.cube",
        text,
        count=1,
    )
    assert count == 1
    log.write_text(mutated, encoding="utf-8")
    with pytest.raises(ValueError, match="charge-density|charge density|declared"):
        parse_berry_outputs(directory, source_model=model, expected=expected)


def test_parse_berry_rejects_missing_native_charge_read_marker(tmp_path: Path):
    directory, model, expected = _copy_native_task(tmp_path)
    method = _require_cpu_fixture(directory)
    log = directory / f"OUT.{method['suffix']}" / "running_nscf.log"
    text = log.read_text(encoding="utf-8")
    mutated, count = re.subn(
        r"(?im)^\s*Read\s+in\s+the\s+charge\s+density\s*:\s*\S+\s*$\r?\n?",
        "",
        text,
        count=1,
    )
    assert count == 1
    log.write_text(mutated, encoding="utf-8")
    with pytest.raises(ValueError, match="charge-density|charge density"):
        parse_berry_outputs(directory, source_model=model, expected=expected)


def test_parse_berry_rejects_pseudopotential_stru_mutation(tmp_path: Path):
    directory, model, expected = _copy_native_task(tmp_path)
    method = json.loads((directory / "method.json").read_text(encoding="utf-8"))
    element = method["element_order"][0]
    lines = (directory / "STRU").read_text(encoding="utf-8").splitlines()
    for index, line in enumerate(lines):
        if line.split() and line.split()[0] == element:
            tokens = line.split()
            tokens[2] = "tampered.upf"
            lines[index] = " ".join(tokens)
            break
    else:
        raise AssertionError(f"native STRU species not found: {element}")
    (directory / "STRU").write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="pseudopotential"):
        parse_berry_outputs(directory, source_model=model, expected=expected)


def test_parse_berry_rejects_truncated_native_log(tmp_path: Path):
    directory, model, expected = _copy_native_task(tmp_path)
    method = json.loads((directory / "method.json").read_text(encoding="utf-8"))
    log = directory / f"OUT.{method['suffix']}" / "running_nscf.log"
    text = log.read_text(encoding="utf-8")
    mutated, count = re.subn(r"(?im)^\s*Finish\s+Time\s*:.*$", "unfinished:", text, count=1)
    assert count == 1
    log.write_text(mutated, encoding="utf-8")
    with pytest.raises(ValueError, match="Finish Time"):
        parse_berry_outputs(directory, source_model=model, expected=expected)
