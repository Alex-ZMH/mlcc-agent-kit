#!/bin/bash
#SBATCH --job-name=mlcc-berry-cpu-input
#SBATCH --partition=cpu
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=4G
#SBATCH --time=00:05:00
#SBATCH --no-requeue
set -euo pipefail
MLCC_ROOT=/home/v100/projects/mlcc/development/0.10.0/project
MLCC_PYTHON=/home/v100/projects/mlcc/development/0.9.0/venv/bin/python
cd "$MLCC_ROOT"
export PYTHONPATH="$MLCC_ROOT/mlcc-agent/src"
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
MLCC_REPORT="$MLCC_ROOT/workspace/reports/berry-v001/cpu-input-${SLURM_JOB_ID}"
mkdir "$MLCC_REPORT"
scontrol show job "$SLURM_JOB_ID" -o > "$MLCC_REPORT/scheduler-running.txt"
"$MLCC_PYTHON" -m mlcc create-berry-nscf \
  --reference-task workspace/tasks/p5-czo-berry-scf-v001/task.json \
  --method workspace/configs/cazro3-berry-cpu-capability-v001.json \
  --site workspace/configs/site.v100-berry-dev-v001.json \
  --request workspace/configs/berry-gdir1-cpu-request-v001.json > "$MLCC_REPORT/create.json"
"$MLCC_PYTHON" -m mlcc prepare \
  --task workspace/tasks/p5-czo-berry-gdir1-cpu-v001/task.json \
  --site workspace/configs/site.v100-berry-dev-v001.json > "$MLCC_REPORT/prepare.json"
