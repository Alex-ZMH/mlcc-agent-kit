"""Record existing remote verification metadata; performs no scientific calculation."""
import json
from pathlib import Path
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "workspace/reports/system-v090"


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig"))


def main():
    unit = ET.parse(REPORT / "remote-43/unit-tests.xml").getroot().find("testsuite")
    counts = {name: int(unit.attrib[name]) for name in ("tests", "failures", "errors", "skipped")}
    assert counts == {"tests": 296, "failures": 0, "errors": 0, "skipped": 0}
    installed = REPORT / "installed-remote-44"
    check_counts = {}
    for name in ("phonons", "lammps-entrypoints", "extensions", "public-properties", "contracts"):
        result = load(installed / name / "acceptance.json")
        assert result["passed"] is True, name
        if "checks" in result:
            assert all(result["checks"].values()), name
            check_counts[name] = len(result["checks"])
    ca = load(installed / "ca-native-regression.json")
    assert ca["passed"] is True and all(ca["checks"].values())
    check_counts["ca-native"] = len(ca["checks"])
    for folder in ("remote-43", "installed-remote-44"):
        native = (REPORT / folder / "scheduler-final.txt").read_text(encoding="utf-8")
        assert "JobState=COMPLETED" in native and "ExitCode=0:0" in native
        assert "Requeue=0" in native and "Restarts=0" in native
    host = load(REPORT / "matterai-headless-session.json")
    assert host["status"] == "passed"
    mcp = load(REPORT / "mcp-probe.json")
    assert mcp["initialize"]["result"]["serverInfo"]["version"] == "0.9.0"
    assert len(mcp["tools"]["result"]["tools"]) == 7
    assert mcp["call"]["result"]["isError"] is False
    equality = load(REPORT / "direct-file-equality.json")
    assert len(equality) == 44
    assert all(row["source_release_equal"] and row["release_installed_equal"] for row in equality)
    enabled = load(ROOT / "workspace/.zeus/bundles.json")["bundles"]
    assert any(row == {"name": "mlcc-agent", "version": "0.9.0", "enabled": True} for row in enabled)
    report = {
        "schema": "mlcc.system-release-acceptance.v001", "version": "0.9.0", "passed": True,
        "enabled_version": "0.9.0", "numerical_execution_host": "v100", "scheduler": "Slurm",
        "unit_tests": {**counts, "passed": 296, "source": "remote-43/unit-tests.xml", "job_id": "43"},
        "installed_checks": check_counts, "installed_contracts_passed": True,
        "installed_acceptance_job": "44", "installed_remote_root": "/home/v100/projects/mlcc/development/0.9.0/installed/0.9.0",
        "matterai_original_host_passed": True, "MCP_version": "0.9.0", "MCP_tools": 7,
        "source_release_installed_direct_equal_files": 44,
        "new_physical_calculation_jobs": ["41"], "new_DFT_jobs": [], "new_MD_sampling_jobs": [],
        "verification_jobs": {"42": "FAILED_3_test_defects_293_passed", "43": "COMPLETED_0:0", "44": "COMPLETED_0:0"},
        "source_native_jobs": ["20", "32", "33", "34", "35", "37", "38", "39", "40", "41"],
        "software_scope": ["Phonopy displacement plans", "explicit ABACUS phonon child tasks", "native force collection gate", "harmonic q-point math", "LAMMPS explicit input and native parsing", "engineering continuation without scientific dependency qualification"],
        "historical_local_tests_not_counted_as_remote": True,
        "local_operations": ["code editing", "file staging and transfer", "task control", "MatterAI installation and MCP connection check", "reading saved evidence"],
        "complete_native_phonon_force_set": False, "phonon_scientific_qualification": False,
        "MD_sampling_qualification": False, "full_tensor_real_25_task_evidence": False,
        "neutral_defect_native_pair": False, "H1_complete": False, "production_engine_switch": False,
        "temperature_matrix_started": False, "design_assessment": "not_assessed", "entire_P0_P12_complete": False,
        "next_minimum_task": "P5 Berry input/native parser with exact-version capability gate",
    }
    with (REPORT / "acceptance.json").open("x", encoding="utf-8") as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(json.dumps({"passed": True, "version": "0.9.0", "remote_tests": counts, "installed_checks": check_counts}))


if __name__ == "__main__":
    main()
