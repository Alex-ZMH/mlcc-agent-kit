"""New saved-collection identity boundaries; run only in v100 Slurm."""

import json
import os
from pathlib import Path

import pytest

from mlcc.property_delivery import deliver_md_properties


@pytest.mark.parametrize(
    ("section", "field", "value", "message"),
    [
        ("native_job", "scheduler_job_id", "another-job", "task/job identity"),
        ("model", "version", "another-model-version", "model version"),
        ("potential", "version", "another-potential-version", "potential version"),
    ],
)
def test_saved_collection_cannot_rebind_native_source(tmp_path, monkeypatch, section, field, value, message):
    collection = json.loads(Path(os.environ["MLCC_MD_COLLECTION"]).read_text())
    task = Path(os.environ["MLCC_MD_TASK"])
    study = task.parent.parent.parent / "configs/study.json"
    request = {
        "window": "whole_record",
        "source": {
            "model_id": collection["model"]["model_id"],
            "model_version": collection["model"]["version"],
            "potential_id": collection["potential"]["potential_id"],
            "potential_version": collection["potential"]["version"],
            "elements": ["Ni"],
        },
        "thermo_diagnostics": {"fields": {"temp": {}}},
    }
    request_path = tmp_path / "request.json"
    request_path.write_text(json.dumps(request))
    collection[section][field] = value
    collection_path = tmp_path / "wrong-collection.json"
    collection_path.write_text(json.dumps(collection))

    def forbidden_parse(*args, **kwargs):
        raise AssertionError("saved-collection delivery must not reparse native logs")

    monkeypatch.setattr("mlcc.md_trajectory.read_md_collection", forbidden_parse)
    with pytest.raises(ValueError, match=message):
        deliver_md_properties(
            study, task, request_path, tmp_path / "delivery",
            collection_path=collection_path,
        )
    assert not (tmp_path / "delivery/delivery.json").exists()
