#!/bin/bash
#SBATCH --job-name=mlcc-berry-reference-input
#SBATCH --partition=cpu
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=3G
#SBATCH --time=00:03:00
#SBATCH --no-requeue
set -euo pipefail
MLCC_ROOT=/home/v100/projects/mlcc/development/0.10.0/project
MLCC_PYTHON=/home/v100/projects/mlcc/development/0.9.0/venv/bin/python
cd "$MLCC_ROOT"
export PYTHONPATH="$MLCC_ROOT/mlcc-agent/src"
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
MLCC_REPORT="$MLCC_ROOT/workspace/reports/berry-v001/prepare-${SLURM_JOB_ID}"
mkdir -p "$MLCC_REPORT"
scontrol show job "$SLURM_JOB_ID" -o > "$MLCC_REPORT/scheduler-running.txt"
"$MLCC_PYTHON" scripts/system/prepare_berry_header_snapshot.py > "$MLCC_REPORT/upf-snapshot.txt"
"$MLCC_PYTHON" -m mlcc create-berry-reference \
  --study workspace/configs/cases/cazro3-firing-v003.json \
  --model workspace/models/cazro3-pnma-pristine/v001 \
  --method workspace/configs/cazro3-berry-capability-v001.json \
  --site workspace/configs/site.v100-berry-dev-v001.json \
  --request workspace/configs/berry-reference-request-v001.json \
  > "$MLCC_REPORT/create.json"
"$MLCC_PYTHON" -m mlcc prepare \
  --task workspace/tasks/p5-czo-berry-scf-v001/task.json \
  --site workspace/configs/site.v100-berry-dev-v001.json \
  > "$MLCC_REPORT/prepare.json"
