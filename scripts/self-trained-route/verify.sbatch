#!/bin/bash
#SBATCH --job-name=mlcc-explicit-potential-route
#SBATCH --account=v100
#SBATCH --partition=cpu
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --hint=nomultithread
#SBATCH --mem=4096M
#SBATCH --time=00:05:00
#SBATCH --no-requeue
set -euo pipefail
DP_ROUTE_ROOT=/home/v100/projects/mlcc/development/self-trained-potential-route-v001
export PYTHONPATH="$DP_ROUTE_ROOT/project/mlcc-agent/src:$DP_ROUTE_ROOT/project/standalone/deepmd_bridge/src"
export PYTHONDONTWRITEBYTECODE=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
cd "$DP_ROUTE_ROOT/project"
/home/v100/projects/mlcc/development/0.9.0/venv/bin/python scripts/self-trained-route/verify.py workspace/configs/self-trained-potential-route-v001.json
