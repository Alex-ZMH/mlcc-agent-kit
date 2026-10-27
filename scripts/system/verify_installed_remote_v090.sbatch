#!/bin/bash
#SBATCH --job-name=mlcc-v090-installed
#SBATCH --partition=cpu
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=4G
#SBATCH --time=00:10:00
#SBATCH --no-requeue

set -euo pipefail
MLCC_ROOT=/home/v100/projects/mlcc/development/0.9.0/project
MLCC_PYTHON=/home/v100/projects/mlcc/development/0.9.0/venv/bin/python
MLCC_BUNDLE=/home/v100/projects/mlcc/development/0.9.0/installed/0.9.0
MLCC_REPORT="$MLCC_ROOT/workspace/reports/system-v090/installed-remote-${SLURM_JOB_ID}"
mkdir "$MLCC_REPORT"
cd "$MLCC_ROOT"
export PYTHONPATH="$MLCC_BUNDLE/src"
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 MPLBACKEND=Agg
hostname > "$MLCC_REPORT/hostname.txt"
scontrol show job "$SLURM_JOB_ID" -o > "$MLCC_REPORT/scheduler-running.txt"
"$MLCC_PYTHON" scripts/system/verify_phonons.py --bundle-root "$MLCC_BUNDLE" --report-dir "$MLCC_REPORT/phonons" > "$MLCC_REPORT/phonons-summary.txt" 2>&1
"$MLCC_PYTHON" scripts/system/verify_lammps_entrypoints.py --bundle-root "$MLCC_BUNDLE" --report-dir "$MLCC_REPORT/lammps-entrypoints" > "$MLCC_REPORT/lammps-entrypoints-summary.txt" 2>&1
"$MLCC_PYTHON" scripts/system/verify_system_extensions.py --bundle-root "$MLCC_BUNDLE" --report-dir "$MLCC_REPORT/extensions" > "$MLCC_REPORT/extensions-summary.txt" 2>&1
"$MLCC_PYTHON" scripts/system/verify_public_properties.py --bundle-root "$MLCC_BUNDLE" --report-dir "$MLCC_REPORT/public-properties" > "$MLCC_REPORT/public-summary.txt" 2>&1
"$MLCC_PYTHON" scripts/system/verify_contracts.py --bundle-root "$MLCC_BUNDLE" --report-dir "$MLCC_REPORT/contracts" > "$MLCC_REPORT/contracts-summary.txt" 2>&1
"$MLCC_PYTHON" scripts/system/verify_ca_compatibility.py --bundle-root "$MLCC_BUNDLE" --output "$MLCC_REPORT/ca-native-regression.json" > "$MLCC_REPORT/ca-summary.txt" 2>&1
