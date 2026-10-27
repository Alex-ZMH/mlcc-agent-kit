#!/usr/bin/env bash
# Postprocess a completed Berry GPU DFT task.  This job never submits DFT.
#SBATCH --job-name=mlcc-berry-gpu-native-accept
#SBATCH --partition=cpu
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=2G
#SBATCH --time=00:05:00
#SBATCH --no-requeue
#SBATCH --output=workspace/reports/berry-gpu-native-v001/native-accept-%j.out
#SBATCH --error=workspace/reports/berry-gpu-native-v001/native-accept-%j.err

set -euo pipefail

MLCC_ROOT=/home/v100/projects/mlcc/development/0.15.0/project
MLCC_PYTHON=/home/v100/projects/mlcc/development/0.9.0/venv/bin/python
MLCC_BUNDLE="$MLCC_ROOT/mlcc-agent"
MLCC_REPORT="$MLCC_ROOT/workspace/reports/berry-gpu-native-v001/native-acceptance-${SLURM_JOB_ID}"

cd "$MLCC_ROOT"
export PYTHONPATH="$MLCC_BUNDLE/src"
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1

"$MLCC_PYTHON" scripts/system/abacus-berry-gpu/accept-native-v001.py \
  --bundle-root "$MLCC_BUNDLE" \
  --report-dir "$MLCC_REPORT"
