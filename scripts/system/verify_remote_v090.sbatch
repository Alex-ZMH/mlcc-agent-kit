#!/bin/bash
#SBATCH --job-name=mlcc-v090-acceptance
#SBATCH --partition=cpu
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=4G
#SBATCH --time=00:15:00
#SBATCH --no-requeue

set -euo pipefail

MLCC_ROOT=/home/v100/projects/mlcc/development/0.9.0/project
MLCC_PYTHON=/home/v100/projects/mlcc/development/0.9.0/venv/bin/python
MLCC_REPORT="$MLCC_ROOT/workspace/reports/system-v090/remote-${SLURM_JOB_ID}"
mkdir "$MLCC_REPORT"
cd "$MLCC_ROOT"
export PYTHONPATH="$MLCC_ROOT/mlcc-agent/src"
export OMP_NUM_THREADS=1
export OPENBLAS_NUM_THREADS=1
export MKL_NUM_THREADS=1
export MPLBACKEND=Agg

hostname > "$MLCC_REPORT/hostname.txt"
scontrol show job "$SLURM_JOB_ID" -o > "$MLCC_REPORT/scheduler-running.txt"
"$MLCC_PYTHON" -m pip list --format=json > "$MLCC_REPORT/python-packages.json"
"$MLCC_PYTHON" -m pytest -q mlcc-agent/tests --junitxml="$MLCC_REPORT/unit-tests.xml" > "$MLCC_REPORT/unit-tests.txt" 2>&1
"$MLCC_PYTHON" scripts/system/verify_phonons.py --bundle-root mlcc-agent --report-dir "$MLCC_REPORT/phonons" > "$MLCC_REPORT/phonons-summary.txt" 2>&1
"$MLCC_PYTHON" scripts/system/verify_lammps_entrypoints.py --bundle-root mlcc-agent --report-dir "$MLCC_REPORT/lammps-entrypoints" > "$MLCC_REPORT/lammps-entrypoints-summary.txt" 2>&1
"$MLCC_PYTHON" scripts/system/verify_system_extensions.py --bundle-root mlcc-agent --report-dir "$MLCC_REPORT/extensions" > "$MLCC_REPORT/extensions-summary.txt" 2>&1
"$MLCC_PYTHON" scripts/system/verify_public_properties.py --bundle-root mlcc-agent --report-dir "$MLCC_REPORT/public-properties" > "$MLCC_REPORT/public-summary.txt" 2>&1
"$MLCC_PYTHON" scripts/system/verify_contracts.py --bundle-root mlcc-agent --report-dir "$MLCC_REPORT/contracts" > "$MLCC_REPORT/contracts-summary.txt" 2>&1
"$MLCC_PYTHON" scripts/system/verify_ca_compatibility.py --bundle-root mlcc-agent --output "$MLCC_REPORT/ca-native-regression.json" > "$MLCC_REPORT/ca-summary.txt" 2>&1
