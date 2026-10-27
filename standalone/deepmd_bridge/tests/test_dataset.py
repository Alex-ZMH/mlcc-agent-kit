import json
from pathlib import Path
import shutil
import sys
import numpy as np
import pytest
SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))
from mlcc_deepmd.dataset import DatasetError, convert_to_deepmd, load_source_manifest  # noqa: E402
ROOT = Path(__file__).resolve().parents[3]
REAL_MANIFEST = ROOT / "standalone" / "deepmd_bridge" / "examples" / "abacus_ni_engineering_sources.json"
def _manifest(*sources: dict) -> dict:
    result = load_source_manifest(REAL_MANIFEST)
    result["sources"] = list(sources)
    return result
def _source(task_id: str, split: str = "train", source_group: str = "scf") -> dict:
    return {"task_id": task_id, "path": f"../../../workspace/tasks/{task_id}", "split": split, "source_group": source_group}
def test_real_abacus_frame_is_reparsed_and_written_as_separate_system(tmp_path: Path) -> None:
    result = convert_to_deepmd(_manifest(_source("h1-ni-scf-v001")), tmp_path / "dataset")
    assert result["training_systems"] == ["train/system-000"]
    assert result["validation_systems"] == []
    assert result["systems"][0]["frames"][0]["model_id"] == "ni-fcc-engineering"
    assert result["systems"][0]["frames"][0]["atom_ids"] == [0, 1, 2, 3]
    assert result["virial"] == {
        "source": "result.stress_GPa",
        "sign": "source_stress_times_volume",
        "source_stress_sign": "abacus_printed",
        "conversion": "stress_GPa * cell_volume / 160.21766208",
        "gpa_per_eV_per_A3": 160.21766208,
    }
    set_dir = tmp_path / "dataset" / "train" / "system-000" / "set.000"
    assert np.load(set_dir / "box.npy").shape == (1, 9)
    assert np.load(set_dir / "coord.npy").shape == (1, 12)
    assert np.load(set_dir / "force.npy").shape == (1, 12)
    assert np.load(set_dir / "virial.npy").shape == (1, 9)
    assert (set_dir.parent / "type.raw").read_text(encoding="utf-8") == "0\n0\n0\n0\n"
    assert (set_dir.parent / "type_map.raw").read_text(encoding="utf-8") == "Ni\n"
def test_negative_virial_sign_is_rejected(tmp_path: Path) -> None:
    manifest = _manifest(_source("h1-ni-scf-v001"))
    manifest["virial"]["sign"] = "negative_source_stress_times_volume"
    with pytest.raises(DatasetError, match="source_stress_times_volume"):
        convert_to_deepmd(manifest, tmp_path / "dataset")
def test_missing_atom_map_is_rejected_before_native_parse(tmp_path: Path) -> None:
    source = _source("h1-ni-scf-v001")
    source["atom_map"] = "missing-map.json"
    with pytest.raises(DatasetError, match="atom_map_path"):
        convert_to_deepmd(_manifest(source), tmp_path / "dataset")
def test_nonconverged_result_is_rejected(tmp_path: Path) -> None:
    task = tmp_path / "task"
    shutil.copytree(ROOT / "workspace" / "tasks" / "h1-ni-scf-v001", task)
    result_path = task / "result.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    result["scientific_status"] = "not_converged"
    result_path.write_text(json.dumps(result), encoding="utf-8")
    manifest = _manifest({"task_id": "h1-ni-scf-v001", "path": "task", "split": "train", "source_group": "scf"})
    manifest["_base_dir"] = str(tmp_path)
    with pytest.raises(DatasetError, match="accepted as converged"):
        convert_to_deepmd(manifest, tmp_path / "dataset")
def test_native_effective_method_difference_is_rejected(tmp_path: Path) -> None:
    manifest = _manifest(_source("h1-ni-scf-v001"), _source("h1-ni-cutoff120-v001", source_group="cutoff120"))
    with pytest.raises(DatasetError, match="mixed effective_method"):
        convert_to_deepmd(manifest, tmp_path / "dataset")
def test_manifest_engine_mismatch_is_rejected_after_native_read(tmp_path: Path) -> None:
    manifest = _manifest(_source("h1-ni-scf-v001"))
    manifest["engine"] = "vasp"
    with pytest.raises(DatasetError, match="engine disagrees"):
        convert_to_deepmd(manifest, tmp_path / "dataset")


def test_atom_map_record_order_may_be_a_valid_permutation(tmp_path: Path) -> None:
    task = tmp_path / "task"
    shutil.copytree(ROOT / "workspace" / "tasks" / "h1-ni-scf-v001", task)
    map_path = task / "STRU.atom-map.json"
    atom_map = json.loads(map_path.read_text(encoding="utf-8"))
    atom_map["abacus_order"] = list(reversed(atom_map["abacus_order"]))
    map_path.write_text(json.dumps(atom_map), encoding="utf-8")
    manifest = _manifest(
        {"task_id": "h1-ni-scf-v001", "path": "task", "split": "train", "source_group": "scf"}
    )
    manifest["_base_dir"] = str(tmp_path)
    result = convert_to_deepmd(manifest, tmp_path / "dataset")
    assert result["systems"][0]["frames"][0]["atom_ids"] == [0, 1, 2, 3]
