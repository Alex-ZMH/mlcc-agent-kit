#!/bin/bash
#SBATCH --job-name=mlcc-neutral-pair
#SBATCH --partition=cpu
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=4G
#SBATCH --time=00:05:00
#SBATCH --no-requeue
set -euo pipefail
MLCC_ROOT=/home/v100/projects/mlcc/development/0.10.0/project
MLCC_PYTHON=/home/v100/projects/mlcc/development/0.9.0/venv/bin/python
MLCC_REPORT="$MLCC_ROOT/workspace/reports/neutral-defect-pair-v001/job-${SLURM_JOB_ID}"
mkdir -p "$MLCC_REPORT"
cd "$MLCC_ROOT"
export PYTHONPATH="$MLCC_ROOT/mlcc-agent/src"
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
hostname > "$MLCC_REPORT/hostname.txt"
scontrol show job "$SLURM_JOB_ID" -o > "$MLCC_REPORT/scheduler-running.txt"
"$MLCC_PYTHON" -m pytest -q mlcc-agent/tests/test_defect_tasks.py --basetemp="$MLCC_REPORT/task-inputs" --junitxml="$MLCC_REPORT/tests.xml" > "$MLCC_REPORT/tests.txt" 2>&1
