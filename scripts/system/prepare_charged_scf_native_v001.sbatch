#!/usr/bin/env bash
#SBATCH --job-name=mlcc-charged-native-prepare
#SBATCH --partition=cpu
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=4G
#SBATCH --time=00:05:00
#SBATCH --no-requeue
#SBATCH --output=workspace/reports/charged-scf-native-v001/prepare-%j.out
#SBATCH --error=workspace/reports/charged-scf-native-v001/prepare-%j.err
set -euo pipefail

MLCC_ROOT=/home/v100/projects/mlcc/development/0.10.0/project
MLCC_PYTHON=/home/v100/projects/mlcc/development/0.9.0/venv/bin/python
cd "$MLCC_ROOT"
mkdir -p "$MLCC_ROOT/workspace/reports/charged-scf-native-v001"
export PYTHONPATH="$MLCC_ROOT/mlcc-agent/src"
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1

exec "$MLCC_PYTHON" "$MLCC_ROOT/scripts/system/prepare_charged_scf_native_v001.py"
