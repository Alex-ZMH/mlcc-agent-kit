"""Write a same-method ABACUS finite-strain stress-sign report."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "mlcc-agent/src"))
from mlcc.strain import compare_strain_tasks


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--minus-task", type=Path, required=True)
    parser.add_argument("--reference-task", type=Path, required=True)
    parser.add_argument("--plus-task", type=Path, required=True)
    parser.add_argument("--method", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args(argv)

    report = compare_strain_tasks(args.minus_task, args.reference_task, args.plus_task, args.method)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "overall": report["overall"],
                "stress_sign_qualification": report["stress_sign_qualification"],
                "report": str(args.report),
            },
            ensure_ascii=False,
        )
    )
    return 0 if report["overall"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
