#!/bin/bash
#SBATCH --job-name=mlcc-dp-lmp-create
#SBATCH --partition=cpu
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=4G
#SBATCH --time=00:05:00
#SBATCH --no-requeue
set -euo pipefail
DP_ROOT=/home/v100/projects/mlcc/development/deepmd-bridge-v001
export PYTHONPATH="$DP_ROOT/project/standalone/deepmd_bridge/src:$DP_ROOT/project/mlcc-agent/src"
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
/home/v100/projects/mlcc/development/0.9.0/venv/bin/python "$DP_ROOT/project/scripts/deepmd-runtime/prepare_public_lammps.py" "$DP_ROOT"
