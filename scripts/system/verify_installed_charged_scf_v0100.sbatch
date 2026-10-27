#!/usr/bin/env bash
#SBATCH --job-name=mlcc-v0100-charged-installed
#SBATCH --partition=cpu
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=4G
#SBATCH --time=00:05:00
#SBATCH --no-requeue
#SBATCH --output=workspace/reports/system-v0100/installed-charged-%j.out
#SBATCH --error=workspace/reports/system-v0100/installed-charged-%j.err

set -euo pipefail

# Software-only installed-candidate verification.  This wrapper never creates
# or submits a DFT task.  The native charged-SCF verifier reads the three
# already completed tasks declared by its protocol file.
MLCC_ROOT=/home/v100/projects/mlcc/development/0.10.0/project
MLCC_BUNDLE=/home/v100/projects/mlcc/development/0.10.0/installed/0.10.0
MLCC_PYTHON=/home/v100/projects/mlcc/development/0.9.0/venv/bin/python
MLCC_REPORT="$MLCC_ROOT/workspace/reports/system-v0100/installed-charged-${SLURM_JOB_ID}"

mkdir -p "$MLCC_REPORT"
cd "$MLCC_ROOT"
export PYTHONPATH="$MLCC_BUNDLE/src"
export MLCC_BUNDLE
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 MPLBACKEND=Agg

printf '%s\n' "$SLURM_JOB_ID" > "$MLCC_REPORT/scheduler-job-id.txt"
hostname > "$MLCC_REPORT/hostname.txt"
scontrol show job "$SLURM_JOB_ID" -o > "$MLCC_REPORT/scheduler-running.txt"

# Record the package imported by the installed candidate, rather than merely
# trusting the source checkout or a manually selected PYTHONPATH.
"$MLCC_PYTHON" - <<'PY' > "$MLCC_REPORT/bundle-import.json"
import json
import os
from pathlib import Path

import mlcc

bundle_root = Path(os.environ["MLCC_BUNDLE"]).resolve()
manifest = json.loads((bundle_root / "bundle.json").read_text(encoding="utf-8"))
print(json.dumps({
    "bundle_root": str(bundle_root),
    "bundle_name": manifest["name"],
    "bundle_version": manifest["version"],
    "import_file": str(Path(mlcc.__file__).resolve()),
    "import_under_bundle": Path(mlcc.__file__).resolve().is_relative_to(bundle_root / "src"),
}, ensure_ascii=False, indent=2))
PY

# The verifier owns the protocol, the three native task records, convergence
# checks, and installed parse-abacus/electronic evidence.  Invoke it exactly
# once; do not repeat source or 0.9.0 acceptance suites here.
# Only printed-weight consumers changed after job72. Job78 did not reach these
# checks because the real 222-to-333 refinement criterion failed.
"$MLCC_PYTHON" -m pytest -q mlcc-agent/tests/test_electronic.py \
  -k 'native_fixed_levels or ni_native_spin or gaussian_dos_includes or native_gamma_cartesian_product' \
  --junitxml="$MLCC_REPORT/affected-electronic.xml"
"$MLCC_PYTHON" scripts/system/verify_charged_scf_native_v001.py \
  --bundle-root "$MLCC_BUNDLE" \
  --protocol "$MLCC_ROOT/workspace/configs/charged-scf-native-protocol-v002.json" \
  --report-dir "$MLCC_REPORT"

