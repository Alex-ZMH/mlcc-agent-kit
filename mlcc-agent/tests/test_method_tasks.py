"""Integration regressions for the explicit CZO ABACUS method gate."""

from __future__ import annotations

import json
from pathlib import Path
import shutil

import pytest

from mlcc.abacus_tasks import create_abacus_task
from mlcc.method_tasks import check_method_configuration
from mlcc.modeling import read_model_artifacts


ROOT = Path(__file__).resolve().parents[2]
MODEL_PATH = ROOT / "workspace" / "models" / "cazro3-pnma-pristine" / "v001"
METHOD_SOURCE = ROOT / "workspace" / "configs" / "cazro3-abacus-capability-v002.json"
STUDY_SOURCE = ROOT / "workspace" / "configs" / "cases" / "cazro3-firing-v003.json"
REQUEST_SOURCE = ROOT / "workspace" / "configs" / "czo-compatibility-request-v001.json"
SITE_SOURCE = ROOT / "workspace" / "configs" / "site.v100.json"
SNAPSHOT_SOURCE = ROOT / "workspace" / "reports" / "method-qualification" / "czo-upf-headers-v002.json"


def _json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def _case(tmp_path: Path) -> dict[str, Path]:
    """Copy the formal CZO configuration graph into an isolated workspace."""

    root = tmp_path / "czo-method-task"
    configs = root / "configs"
    reports = root / "reports" / "method-qualification"
    tasks = root / "workspace" / "tasks"
    configs.mkdir(parents=True)
    (configs / "cases").mkdir()
    reports.mkdir(parents=True)
    tasks.mkdir(parents=True)
    method_path = configs / METHOD_SOURCE.name
    study_path = configs / "cases" / STUDY_SOURCE.name
    request_path = configs / REQUEST_SOURCE.name
    site_path = configs / SITE_SOURCE.name
    snapshot_path = reports / SNAPSHOT_SOURCE.name
    shutil.copy2(METHOD_SOURCE, method_path)
    shutil.copy2(STUDY_SOURCE, study_path)
    shutil.copy2(REQUEST_SOURCE, request_path)
    shutil.copy2(SNAPSHOT_SOURCE, snapshot_path)
    site = _json(SITE_SOURCE)
    site["workspace"]["local"] = str(root / "workspace")
    _write_json(site_path, site)
    return {
        "root": root,
        "method": method_path,
        "study": study_path,
        "request": request_path,
        "site": site_path,
        "snapshot": snapshot_path,
        "tasks": tasks,
    }


def _model():
    return read_model_artifacts(MODEL_PATH)


def _create(paths: dict[str, Path]):
    return create_abacus_task(
        study_path=paths["study"],
        model_path=MODEL_PATH,
        method_path=paths["method"],
        site_path=paths["site"],
        request_path=paths["request"],
    )


def test_nonfixture_without_input_qualification_is_rejected_before_task_directory(tmp_path):
    paths = _case(tmp_path)
    method = _json(paths["method"])
    method.pop("input_qualification")
    _write_json(paths["method"], method)

    with pytest.raises(ValueError, match="explicit method input qualification"):
        _create(paths)
    assert not (paths["tasks"] / "p4-czo-compatibility-scf-v001").exists()


@pytest.mark.parametrize("mutation", ["method_set", "site"])
def test_snapshot_method_or_site_identity_is_rejected_before_task_creation(tmp_path, mutation):
    paths = _case(tmp_path)
    snapshot = _json(paths["snapshot"])
    site = _json(paths["site"])
    if mutation == "method_set":
        snapshot["method_set"] = "unrelated-method-set"
    else:
        snapshot["ssh_alias"] = "different-site"
    _write_json(paths["snapshot"], snapshot)
    _write_json(paths["site"], site)

    with pytest.raises(ValueError, match="snapshot belongs to a different"):
        _create(paths)
    assert not (paths["tasks"] / "p4-czo-compatibility-scf-v001").exists()


def test_derived_snapshot_headers_and_passed_flag_are_ignored_in_favor_of_native_excerpts(tmp_path):
    paths = _case(tmp_path)
    snapshot = _json(paths["snapshot"])
    snapshot["headers"]["Ca"]["element"] = "tampered-derived-value"
    snapshot["headers"]["Ca"]["source_path"] = "/tampered/derived/path.upf"
    snapshot["passed"] = False
    _write_json(paths["snapshot"], snapshot)

    report = check_method_configuration(_model(), _json(paths["method"]), _json(paths["site"]), paths["method"])
    assert report["input_qualified"] is True
    assert report["passed"] is True
    assert report["issues"] == []


@pytest.mark.parametrize("mutation", ["native_element", "resource_path"])
def test_native_excerpt_or_selected_site_resource_mismatch_rejects_without_task(tmp_path, mutation):
    paths = _case(tmp_path)
    snapshot = _json(paths["snapshot"])
    site = _json(paths["site"])
    if mutation == "native_element":
        snapshot["native_excerpts"]["Ca"]["native_excerpt"] = snapshot["native_excerpts"]["Ca"]["native_excerpt"].replace(
            'element="Ca"', 'element="Zr"', 1
        )
        _write_json(paths["snapshot"], snapshot)
    else:
        site["abacus"]["pseudopotential_files"]["Ca_ONCV_PBE_10e_FR"] = "/home/v100/abacus-work/PPORBs/pseudopotentials/Other-Ca.upf"
        _write_json(paths["site"], site)

    with pytest.raises(ValueError, match="ABACUS method input qualification failed"):
        _create(paths)
    assert not (paths["tasks"] / "p4-czo-compatibility-scf-v001").exists()


def test_normal_czo_creation_retains_average_j_non_soc_and_nonproduction_labels(tmp_path):
    paths = _case(tmp_path)
    task = _create(paths)
    task_dir = paths["tasks"] / "p4-czo-compatibility-scf-v001"
    assert task["method_input_qualified"] is True
    assert task["production_label"] is False
    assert task_dir.exists()

    method = _json(task_dir / "method.json")
    assert method["pseudopotential_treatment"]["Ca"] == "abacus_3.10.1_average_j"
    assert method["input_qualification"]["input_qualified"] is True
    assert method["input_qualification"]["production_qualification"] is False
    assert method["lspinorb"] is False
    assert method["noncolin"] is False
    input_text = (task_dir / "INPUT").read_text(encoding="utf-8")
    assert "lspinorb             0" in input_text
    assert "noncolin             0" in input_text
    assert len(list(paths["tasks"].iterdir())) == 1


def test_inspect_site_upf_headers_reads_local_transport_without_ssh(tmp_path, monkeypatch):
    from mlcc.method_tasks import inspect_site_upf_headers

    upf_path = tmp_path / "O.upf"
    upf_path.write_text(
        '<UPF version="2.0.1"><PP_HEADER element="O" pseudo_type="NC" '
        'relativistic="scalar" is_ultrasoft="F" is_paw="F" has_so="F" '
        'functional="SLA PW PBX PBC" z_valence="6"/></UPF>',
        encoding="utf-8",
    )
    method_path = tmp_path / "method.json"
    method_path.write_text(
        json.dumps({
            "method_set": "local-upf",
            "element_order": ["O"],
            "pseudopotential_ids": {"O": "O-local"},
        }),
        encoding="utf-8",
    )
    site_path = tmp_path / "site.json"
    site_path.write_text(
        json.dumps({
            "ssh": {"alias": "local-site", "transport": "local"},
            "abacus": {"pseudopotential_files": {"O-local": str(upf_path)}},
        }),
        encoding="utf-8",
    )

    def fail_if_called(*args, **kwargs):
        raise AssertionError("local UPF inspection must not invoke subprocess.run")

    monkeypatch.setattr("mlcc.method_tasks.subprocess.run", fail_if_called)
    snapshot = inspect_site_upf_headers(method_path, site_path)

    assert snapshot["transport"] == "local"
    assert snapshot["command"][0] == "local-read"
    assert snapshot["headers"]["O"]["functional"] == "SLA PW PBX PBC"
    assert snapshot["headers"]["O"]["functional_normalized"] == "PBE"

