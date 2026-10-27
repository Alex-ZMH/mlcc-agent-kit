"""New NEMD continuation path only; these fixtures are not scientific evidence."""
import json

from mlcc.tasks import save_task
from mlcc.workflow import inspect_task
from test_bulk_thermal_workflow import _task_with_result


def _saved_bulk_heat(tmp_path):
    task, result_path, result = _task_with_result(tmp_path)
    task.data["protocol"].update(purpose="bulk_thermal_transport", ensemble="nve")
    result["protocol"] = task.data["protocol"]
    result["scientific_status"] = "executed_bulk_heat_protocol"
    result.pop("bulk_thermal_series")
    result["bulk_heat_source"] = {
        "schema": "mlcc.md-bulk-heat-source.v1",
        "energy_rows": [{"step": 10}],
        "profile_frames": [{"step": 10, "bins": []}],
        "missing_evidence": [],
    }
    for name in ("thermal-energy.dat", "thermal-profile.dat"):
        path = result_path.parent / name
        path.write_text("native table fixture\n", encoding="utf-8")
        result["source_files"][name] = str(path)
    save_task(task)
    result_path.write_text(json.dumps(result), encoding="utf-8")
    return task, result_path, result


def test_saved_bulk_heat_completes_without_material_gradient_or_qualification(tmp_path):
    task, _, _ = _saved_bulk_heat(tmp_path)
    decision = inspect_task(task)
    assert decision["action"] == "completed"
    assert decision["scientific_status"] == "executed_bulk_heat_protocol"
    assert decision["scientific_qualification"] is False


def test_missing_native_profile_keeps_bulk_heat_original_error(tmp_path):
    task, result_path, _ = _saved_bulk_heat(tmp_path)
    (result_path.parent / "thermal-profile.dat").unlink()
    assert inspect_task(task)["action"] == "review_original_error"
