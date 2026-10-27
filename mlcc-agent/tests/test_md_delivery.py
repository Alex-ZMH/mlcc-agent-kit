"""New delivery boundaries against preserved job45; executed only on v100."""
import json
import os
from pathlib import Path

import pytest

from mlcc.property_delivery import deliver_md_properties


NATIVE = Path(os.environ.get("MLCC_MD_TASK", "/home/v100/projects/mlcc/development/0.10.0/lammps-md/project/workspace/tasks/p10-ni-lammps-nve100-v001"))
STUDY = NATIVE.parent.parent / "configs/study.json"


def request(tmp_path, *, window="production_window", rdf=None):
    method = json.loads((NATIVE / "method.json").read_text())
    record = {"window": window, "source": {
        "model_id": method["model_id"], "model_version": method["version"],
        "potential_id": method["potential"]["potential_id"],
        "potential_version": method["potential"]["version"], "elements": ["Ni"],
    }}
    if rdf is not None:
        record["rdf"] = rdf
    path = tmp_path / "request.json"
    path.write_text(json.dumps(record))
    return path


def test_missing_window_delivers_unresolved_without_thermo(tmp_path):
    result = deliver_md_properties(STUDY, NATIVE, request(tmp_path), tmp_path / "delivery")
    assert result["status"] == "unresolved_missing_observation_window"
    assert result["native_job"]["scheduler_job_id"] == "45"
    assert result["observables"] == [] and result["md_thermo"] is None
    assert "thermo" not in result["artifacts"]
    assert result["windows"]["production_window"]["count"] is None
    assert result["design_assessment"] == "not_assessed"
    assert result["dependencies"] == []
    assert "md_rdf" not in result


def test_job45_public_delivery_includes_explicit_rdf_artifact(tmp_path):
    rdf_request = {
        "species_pair": ["Ni", "Ni"],
        "r_edges_angstrom": [0.0, 0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 1.75],
    }
    result = deliver_md_properties(
        STUDY,
        NATIVE,
        request(tmp_path, window="whole_record", rdf=rdf_request),
        tmp_path / "delivery",
    )

    assert result["status"] == "delivered_engineering_observations"
    assert result["md_rdf"]["schema"] == "mlcc.md-rdf.v1"
    assert result["md_rdf"]["native_job"]["scheduler_job_id"] == "45"
    assert result["md_rdf"]["observation"]["request"] == {"kind": "whole_record"}
    assert result["md_rdf"]["first_peak"]["status"] == "unresolved"
    assert result["md_rdf"]["production_qualification"] is False
    assert result["md_rdf"]["grid"]["r_max_angstrom"] == 1.75
    assert "md-rdf" in result["artifacts"]
    rdf_path = Path(result["artifacts"]["md-rdf"])
    assert rdf_path.name == "md-rdf.json"
    assert json.loads(rdf_path.read_text())["schema"] == "mlcc.md-rdf.v1"
    report = Path(result["artifacts"]["report"]).read_text(encoding="utf-8")
    assert "RDF:" in report and "first_peak=unresolved" in report


def test_wrong_study_cannot_relabel_native_results(tmp_path):
    study = json.loads(STUDY.read_text())
    study["study_id"] = "other-study"
    path = tmp_path / "study.json"
    path.write_text(json.dumps(study))
    with pytest.raises(ValueError, match="study_id"):
        deliver_md_properties(path, NATIVE, request(tmp_path), tmp_path / "delivery")
    assert not (tmp_path / "delivery").exists()


def test_wrong_potential_cannot_deliver_native_results(tmp_path):
    path = request(tmp_path)
    record = json.loads(path.read_text())
    record["source"]["potential_id"] = "different-potential"
    path.write_text(json.dumps(record))
    with pytest.raises(ValueError, match="potential identity"):
        deliver_md_properties(STUDY, NATIVE, path, tmp_path / "delivery")
    assert not (tmp_path / "delivery/delivery.json").exists()
