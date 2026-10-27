"""MD-06 descriptive thermo contract tests.

Tests consume the accepted job45/job105 collection through the environment
provided by the v100 Slurm acceptance script.  Temporary copies are used only
for input-error cases; no synthetic thermo series or numerical task is
created.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil

import pytest

from mlcc.md_thermo import analyze_md_thermo


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_COLLECTION = ROOT / "workspace" / "reports" / "md-series-v011-v001" / "collection.json"


def _source() -> Path:
    return Path(os.environ.get("MLCC_MD_COLLECTION", str(DEFAULT_COLLECTION)))


def _copy_collection(tmp_path: Path, name: str) -> tuple[Path, dict[str, object]]:
    source = _source()
    assert source.is_file(), f"accepted MD collection unavailable: {source}"
    target = tmp_path / f"{name}.json"
    shutil.copy2(source, target)
    return target, json.loads(target.read_text(encoding="utf-8"))


def _write(path: Path, record: dict[str, object]) -> None:
    path.write_text(json.dumps(record, indent=2, allow_nan=True), encoding="utf-8")


def test_whole_record_reports_native_job45_thermo_observation() -> None:
    source = _source()
    assert source.is_file(), f"accepted MD collection unavailable: {source}"
    before = source.read_text(encoding="utf-8")
    record = json.loads(before)
    rows = record["thermo"]["rows"]

    result = analyze_md_thermo(source, observation_window={"kind": "whole_record"})

    expected_temperatures = [float(row["temp"]) for row in rows]
    expected_energies = [float(row["etotal"]) for row in rows]
    assert source.read_text(encoding="utf-8") == before
    assert result["schema"] == "mlcc.md-thermo-summary.v1"
    assert result["status"] == "described_engineering_observation"
    assert result["task_id"] == "p10-ni-lammps-nve100-v001"
    assert result["native_job"]["scheduler_job_id"] == "45"
    assert result["native_job"]["scheduler_state"] == "COMPLETED"
    assert result["model"]["model_id"] == "ni-abacus-engineering-relaxed"
    assert result["potential"]["potential_id"] == "Ni-u3-Foiles1986"
    assert result["conditions"]["windows"]["production_window"]["status"] == "unresolved_missing"

    observation = result["observation"]
    assert observation["request"] == {"kind": "whole_record"}
    assert observation["indices"] == list(range(len(rows)))
    assert observation["sample_count"] == len(rows)
    assert observation["step_range"] == [rows[0]["step"], rows[-1]["step"]]
    assert observation["physical_time_ps_range"] == [rows[0]["physical_time_ps"], rows[-1]["physical_time_ps"]]
    assert observation["physical_time_fs_range"] == [rows[0]["physical_time_fs"], rows[-1]["physical_time_fs"]]
    assert observation["scope"] == "engineering_observation_not_production"

    assert result["thermo"]["units"] == record["thermo"]["units"]
    assert result["thermo"]["rows"] == rows
    temperature = result["quantities"]["temperature"]
    assert temperature["source_field"] == "temp"
    assert temperature["unit"] == "K"
    assert temperature["normalization"] == "whole_simulation_cell"
    assert temperature["sample_mean"] == pytest.approx(sum(expected_temperatures) / len(rows))
    assert temperature["minimum"] == min(expected_temperatures)
    assert temperature["maximum"] == max(expected_temperatures)

    total_energy = result["quantities"]["total_energy"]
    assert total_energy["source_field"] == "etotal"
    assert total_energy["unit"] == "eV"
    assert total_energy["normalization"] == "whole_simulation_cell"
    assert total_energy["initial"] == expected_energies[0]
    assert total_energy["final"] == expected_energies[-1]
    assert total_energy["final_minus_initial"] == pytest.approx(expected_energies[-1] - expected_energies[0])
    assert result["source_selection"]["source_selection"]["source_count"] == 1
    assert result["production_qualification"] is False
    assert result["sampling_equilibrium_qualified"] is False
    for diagnostic in result["diagnostics"].values():
        assert diagnostic == {
            "status": "unresolved",
            "reason": "not_evaluated_by_descriptive_summary",
        }


def test_step_range_50_to_100_is_inclusive_engineering_observation() -> None:
    source = _source()
    assert source.is_file(), f"accepted MD collection unavailable: {source}"
    record = json.loads(source.read_text(encoding="utf-8"))
    rows = record["thermo"]["rows"]
    selected = rows[5:]

    result = analyze_md_thermo(
        source,
        observation_window={"kind": "step_range", "start_step": 50, "end_step": 100},
    )

    assert result["observation"]["request"] == {
        "kind": "step_range",
        "start_step": 50,
        "end_step": 100,
    }
    assert result["observation"]["indices"] == list(range(5, 11))
    assert result["observation"]["sample_count"] == 6
    assert result["observation"]["step_range"] == [50, 100]
    assert result["thermo"]["rows"] == selected
    assert result["quantities"]["total_energy"]["initial"] == selected[0]["etotal"]
    assert result["quantities"]["total_energy"]["final"] == selected[-1]["etotal"]
    assert result["production_qualification"] is False


@pytest.mark.parametrize("window_request", [None, {}, {"kind": "unsupported"}, {"kind": "step_range"}])
def test_rejects_missing_or_invalid_observation_request(window_request: object) -> None:
    source = _source()
    assert source.is_file(), f"accepted MD collection unavailable: {source}"
    with pytest.raises(ValueError, match="observation_window|step_range|unsupported"):
        analyze_md_thermo(source, observation_window=window_request)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "window_request",
    [
        {"kind": "step_range", "start_step": 50, "end_step": 50},
        {"kind": "step_range", "start_step": 100, "end_step": 50},
        {"kind": "step_range", "start_step": 5, "end_step": 100},
    ],
)
def test_rejects_invalid_or_unobserved_step_range(window_request: dict[str, object]) -> None:
    source = _source()
    assert source.is_file(), f"accepted MD collection unavailable: {source}"
    with pytest.raises(ValueError, match="greater than|endpoints"):
        analyze_md_thermo(source, observation_window=window_request)


def test_rejects_bounds_on_whole_record() -> None:
    with pytest.raises(ValueError, match="whole_record must not contain"):
        analyze_md_thermo(_source(), observation_window={"kind": "whole_record", "start_step": 50})


@pytest.mark.parametrize(
    ("field", "value"),
    [("temp", float("nan")), ("etotal", float("inf"))],
)
def test_rejects_nonfinite_selected_thermo_value(tmp_path: Path, field: str, value: float) -> None:
    path, record = _copy_collection(tmp_path, f"nonfinite-{field}")
    record["thermo"]["rows"][0][field] = value
    _write(path, record)

    with pytest.raises(ValueError, match=f"{field}.*finite"):
        analyze_md_thermo(path, observation_window={"kind": "whole_record"})


@pytest.mark.parametrize("field", ["temp", "etotal"])
def test_preserves_missing_thermo_field_key_error(tmp_path: Path, field: str) -> None:
    path, record = _copy_collection(tmp_path, f"missing-{field}")
    del record["thermo"]["rows"][0][field]
    _write(path, record)

    with pytest.raises(KeyError, match=field):
        analyze_md_thermo(path, observation_window={"kind": "whole_record"})
