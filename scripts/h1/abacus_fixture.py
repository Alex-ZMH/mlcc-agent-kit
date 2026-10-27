"""Ni engineering convenience entry; scientific inputs come from explicit files."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "mlcc-agent/src"))
from mlcc.abacus_tasks import create_abacus_task, parse_abacus_task
from mlcc.site_runner import runner_for_task

WORKSPACE = ROOT / "workspace"
SITE = WORKSPACE / "configs/site.v100.json"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["create", "prepare", "transfer", "submit", "query", "collect", "parse"])
    parser.add_argument("case", choices=["scf", "cutoff120", "strainminus", "strainplus", "relax", "post-relax"])
    parser.add_argument("--task-version", default="v001")
    for name in ("study", "model", "method", "request"):
        parser.add_argument(f"--{name}", type=Path)
    args = parser.parse_args()
    task_id = f"h1-ni-{args.case}-{args.task_version}"
    task_path = WORKSPACE / "tasks" / task_id / "task.json"
    if args.action == "create":
        for name in ("study", "model", "method", "request"):
            if getattr(args, name) is None:
                parser.error(f"create requires --{name}; no implicit Ni method is selected")
        request = json.loads(args.request.read_text(encoding="utf-8"))
        if request["task_id"] != task_id:
            raise ValueError("request task_id differs from explicit case/version")
        data = create_abacus_task(study_path=args.study, model_path=args.model, method_path=args.method,
                                  site_path=SITE, request_path=args.request)
    elif args.action == "parse":
        data = parse_abacus_task(task_path, SITE)
    else:
        if args.action == "submit":
            acceptance = json.loads((WORKSPACE / "reports/h0/acceptance.json").read_text(encoding="utf-8"))
            assert acceptance["H0_complete"] is True, "P4 submission requires the completed H0 engineering gate"
        runner, task = runner_for_task(SITE, task_path)
        data = getattr(runner, args.action)(task)
    print(json.dumps({key: data.get(key) for key in ["task_id", "status", "scheduler_job_id", "scientific_status"]}))


if __name__ == "__main__":
    main()
