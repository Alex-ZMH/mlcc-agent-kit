"""CLI-bound consumer checks for saved native MD thermal-stress sources."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mlcc.cli import main
from mlcc.property_delivery import deliver_local_stress
from mlcc.thermal_stress_sources import build_md_thermal_sources, build_thermal_stress


COMPONENT_ORDER = ["xx", "yy", "zz", "xy", "xz", "yz", "yx", "zx", "zy"]
CELL = [[2.0, 0.0, 0.0], [0.0, 2.0, 0.0], [0.0, 0.0, 2.0]]


def _write(path: Path, value: object) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path, Path, Path]:
    task_dir = tmp_path / "task"
    task_path = task_dir / "task.json"
    (tmp_path / "model").mkdir()
    protocol = {
        "kind": "md",
        "purpose": "md_native_sampling",
        "units": "metal",
        "boundary": ["p", "p", "p"],
        "ensemble": "nvt",
        "temperature_K": 400.0,
        "seed": 123,
        "timestep_ps": 0.1,
        "native_sampling": {"component_order": COMPONENT_ORDER},
    }
    task = {
        "task_id": "czo-md-test",
        "study_id": "study",
        "case_id": "case",
        "case_role": "engineering_fixture",
        "model_id": "czo",
        "model_version": "v001",
        "model_path": str(tmp_path / "model"),
        "parent_model": None,
        "method": {"schema": "method"},
        "method_set": "deepmd-test",
        "potential": {"potential_id": "deepmd-czo", "version": "v001"},
        "protocol": protocol,
        "runner": "slurm",
        "scheduler_job_id": "901",
        "scheduler_state": "COMPLETED",
        "exit_code": "0:0",
        "status": "COMPLETED",
        "scientific_status": "engineering_sampling_not_equilibrium_qualification",
        "fixture": True,
    }
    _write(task_path, task)
    atom_map = {
        "schema": "mlcc.lammps-atom-map.v1",
        "model_id": "czo",
        "version": "v001",
        "source_atom_ids": [10, 20],
        "source_cell_angstrom": CELL,
    }
    atom_map_path = _write(task_dir / "atom-map.json", atom_map)
    constraint = {
        "cell_angstrom": CELL,
        "boundary": ["p", "p", "p"],
        "fixed_atom_ids": [],
        "loading": {"kind": "none"},
    }
    frames = []
    for step, value, target_temperature in ((0, 1.0, 999.0), (10, 2.0, 998.0), (20, 3.0, 997.0)):
        frames.append(
            {
                "step": step,
                "physical_time_ps": step * 0.1,
                "temperature_K": target_temperature,
                "atom_ids": [10, 20],
                "component_order": COMPONENT_ORDER,
                "stress_volume_components_bar_A3": [
                    [value] * 9,
                    [value] * 9,
                ],
            }
        )
    sampling = {
        "schema": "mlcc.md-native-stress-source.v1",
        "source_cell_angstrom": CELL,
        "component_order": COMPONENT_ORDER,
        "stress_volume_unit": "bar*angstrom^3",
        "tensor_basis": "lammps_prism",
        "contribution": "virial",
        "kinetic_included": False,
        "protocol": protocol,
        "task_id": task["task_id"],
        "study_id": task["study_id"],
        "case_id": task["case_id"],
        "case_role": task["case_role"],
        "model_id": task["model_id"],
        "model_version": task["model_version"],
        "method_set": task["method_set"],
        "model": {"model_id": "czo", "version": "v001"},
        "potential": {"potential_id": "deepmd-czo", "version": "v001"},
        "scheduler_job_id": "901",
        "scheduler_state": "COMPLETED",
        "exit_code": "0:0",
        "native_job": {"scheduler_job_id": "901", "scheduler_state": "COMPLETED", "exit_code": "0:0"},
        "mechanical_constraint": constraint,
        "frames": frames,
        "sampling_windows": {
            "equilibration": {"start_step": 0, "end_step": 0, "closed": True},
            "production": {"start_step": 10, "end_step": 20, "closed": True},
        },
        "source_files": {},
    }
    sampling_path = _write(task_dir / "sampling.json", sampling)
    collection = {
        "schema": "mlcc.md-collection.v1",
        "task_id": task["task_id"],
        "lineage": {
            "study_id": task["study_id"],
            "case_id": task["case_id"],
            "case_role": task["case_role"],
            "method_set": task["method_set"],
        },
        "native_job": {"scheduler_job_id": "901", "scheduler_state": "COMPLETED", "exit_code": "0:0"},
        "protocol": protocol,
        "model": {"model_id": "czo", "version": "v001"},
        "potential": {"potential_id": "deepmd-czo", "version": "v001"},
        "thermo": {
            "rows": [
                {"step": 0, "physical_time_ps": 0.0, "temp": 300.0},
                {"step": 10, "physical_time_ps": 1.0, "temp": 301.0},
                {"step": 20, "physical_time_ps": 2.0, "temp": 402.0},
            ]
        },
        "source_files": {},
    }
    collection_path = _write(task_dir / "md-collection.json", collection)
    analysis = {
        "schema": "mlcc.local-stress-analysis.v1",
        "source_kind": "native_md_sampling",
        "fixture": True,
        "fixture_purpose": "software_contract_only",
        "observation_window": {"kind": "step_range", "start_step": 10, "end_step": 20},
        "regions": [{
            "region_id": "whole_cell",
            "atom_ids": [10, 20],
            "volume_angstrom3": 8.0,
            "volume_definition": "full fixed simulation cell",
        }],
    }
    request_path = _write(
        tmp_path / "request.json",
        {
            "schema": "mlcc.md-thermal-sources-request.v1",
            "task_path": str(task_path),
            "sampling_path": str(sampling_path),
            "collection_path": str(collection_path),
            "analysis": analysis,
            "mechanical_constraint": constraint,
        },
    )
    study_path = _write(
        tmp_path / "study.json",
        {
            "study_id": "study",
            "case_id": "case",
            "case_role": "engineering_fixture",
            "model": {"model_id": "czo", "version": "v001"},
        },
    )
    return request_path, task_path, sampling_path, collection_path, study_path


def test_cli_builds_saved_md_thermal_sources_and_uses_collection_temperature(tmp_path: Path) -> None:
    request_path, _task_path, _sampling_path, _collection_path, study_path = _fixture(tmp_path)
    output_dir = tmp_path / "consumer"

    assert main([
        "md-thermal-sources",
        "--request",
        str(request_path),
        "--output-dir",
        str(output_dir),
    ]) == 0

    manifest = json.loads((output_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["schema"] == "mlcc.md-thermal-sources.v1"
    assert manifest["status"] == "saved"
    assert manifest["selected_frame_count"] == 2
    assert set(manifest["artifacts"]) == {"local_stress", "temperature_history", "mechanical_history", "manifest"}

    local = json.loads(Path(manifest["artifacts"]["local_stress"]).read_text(encoding="utf-8"))
    assert local["local_stress"]["stress_volume_component_order"] == COMPONENT_ORDER
    assert local["local_stress"]["contribution"] == "virial"
    assert local["local_stress"]["kinetic_included"] is False
    assert local["local_stress"]["regions"][0]["conversion"]["tensor_contribution"] == "virial_only"

    temperature = json.loads(Path(manifest["artifacts"]["temperature_history"]).read_text(encoding="utf-8"))
    assert [sample["temperature_K"] for sample in temperature["samples"]] == [301.0, 402.0]
    mechanical = json.loads(Path(manifest["artifacts"]["mechanical_history"]).read_text(encoding="utf-8"))
    assert [sample["step"] for sample in mechanical["samples"]] == [10, 20]
    assert all(sample["constraint"]["fixed_atom_ids"] == [] for sample in mechanical["samples"])

    delivery = deliver_local_stress(study_path, manifest["artifacts"]["local_stress"])
    assert delivery["schema"] == "mlcc.local-stress-delivery.v1"
    assert delivery["status"] == "available"
    assert delivery["native_local_stress"]["schema"] == "mlcc.md-native-stress-source.v1"


def test_rejects_saved_sampling_job_identity_mismatch(tmp_path: Path) -> None:
    request_path, _task_path, sampling_path, _collection_path, _study_path = _fixture(tmp_path)
    sampling = json.loads(sampling_path.read_text(encoding="utf-8"))
    sampling["scheduler_job_id"] = "902"
    _write(sampling_path, sampling)

    with pytest.raises(ValueError, match="MD sampling scheduler_job_id differs"):
        build_md_thermal_sources(request_path, tmp_path / "consumer")


def test_rejects_wrong_whole_cell_volume(tmp_path: Path) -> None:
    request_path, _task_path, _sampling_path, _collection_path, _study_path = _fixture(tmp_path)
    request = json.loads(request_path.read_text(encoding="utf-8"))
    request["analysis"]["regions"][0]["volume_angstrom3"] = 7.0
    _write(request_path, request)

    with pytest.raises(ValueError, match="source cell determinant"):
        build_md_thermal_sources(request_path, tmp_path / "consumer")


@pytest.mark.parametrize(
    ("missing_field", "expected_status"),
    [("volume", "partial"), ("window", "unresolved")],
)
def test_missing_volume_or_window_remains_unresolved_without_zero_fill(
    tmp_path: Path, missing_field: str, expected_status: str
) -> None:
    request_path, _task_path, _sampling_path, _collection_path, _study_path = _fixture(tmp_path)
    request = json.loads(request_path.read_text(encoding="utf-8"))
    if missing_field == "volume":
        request["analysis"]["regions"][0]["volume_angstrom3"] = None
    else:
        request["analysis"]["observation_window"] = None
    _write(request_path, request)

    manifest = build_md_thermal_sources(request_path, tmp_path / "consumer")
    local = json.loads(Path(manifest["artifacts"]["local_stress"]).read_text(encoding="utf-8"))
    response = local["local_stress"]
    region = response["regions"][0]
    assert manifest["status"] == expected_status
    assert response["status"] == expected_status
    assert region["stress_GPa"] is None
    assert region["pressure_tensor_GPa"] is None
    if missing_field == "volume":
        assert region["stress_volume_sum_bar_A3_mean"] != [0.0] * len(COMPONENT_ORDER)
    else:
        assert region["stress_volume_sum_bar_A3_mean"] is None


def test_saved_histories_are_consumed_by_thermal_stress_same_source_pair(tmp_path: Path) -> None:
    request_path, _task_path, _sampling_path, _collection_path, study_path = _fixture(tmp_path)
    manifest = build_md_thermal_sources(request_path, tmp_path / "consumer")
    entry = {
        "region_id": "whole_cell",
        "stress_product_path": manifest["artifacts"]["local_stress"],
        "temperature_history_path": manifest["artifacts"]["temperature_history"],
        "mechanical_history_path": manifest["artifacts"]["mechanical_history"],
        "temperature_product_path": None,
    }
    thermal_request = _write(
        tmp_path / "thermal-request.json",
        {
            "schema": "mlcc.thermal-stress-request.v1",
            "reference": {"state_id": "reference", **entry},
            "states": [{"state_id": "target", **entry}],
        },
    )

    result = build_thermal_stress(study_path, thermal_request)
    state = result["response"]["states"][0]
    assert result["status"] == "available"
    assert state["classification"] == "same_constraint_thermal_stress_change"
    assert state["thermal_stress_change_GPa"] == [[0.0] * 3 for _ in range(3)]
    assert [sample["temperature_K"] for sample in state["temperature_history"]["samples"]] == [301.0, 402.0]
