#!/usr/bin/env python3
"""Create the explicit Ni fcc H0 engineering fixture."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "mlcc-agent" / "src"))

from mlcc.modeling import build_nickel_fcc_fixture  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--model-id", default="ni-fcc-engineering")
    parser.add_argument("--version", default="v001")
    parser.add_argument("--lattice-constant-angstrom", type=float, default=3.52)
    parser.add_argument("--repeat", type=int, nargs=3, default=(1, 1, 1), metavar=("NX", "NY", "NZ"))
    parser.add_argument("--displaced-atom-id", type=int)
    parser.add_argument("--displacement-angstrom", type=float, default=0.0)
    args = parser.parse_args()
    result = build_nickel_fcc_fixture(
        args.output,
        model_id=args.model_id,
        version=args.version,
        lattice_constant_angstrom=args.lattice_constant_angstrom,
        repeat=tuple(args.repeat),
        displaced_atom_id=args.displaced_atom_id,
        displacement_angstrom=args.displacement_angstrom,
    )
    print(
        json.dumps(
            {
                "model_id": result.model_id,
                "version": result.version,
                "artifact_dir": str(result.artifact_dir),
                "atom_count": len(result.atoms),
                "atom_ids": result.atom_ids,
                "fixture": result.metadata["fixture"],
                "scientific_status": result.metadata["scientific_status"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

