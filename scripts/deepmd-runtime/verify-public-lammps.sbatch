#!/bin/bash
#SBATCH --job-name=mlcc-dp-public-verify
#SBATCH --partition=gpu
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --gres=gpu:v100:1
#SBATCH --mem=8G
#SBATCH --time=00:05:00
#SBATCH --no-requeue
set -euo pipefail
DP_ROOT=/home/v100/projects/mlcc/development/deepmd-bridge-v001
DP_ANALYSIS=/home/v100/projects/mlcc/development/0.9.0/venv/bin/python
export PYTHONPATH="$DP_ROOT/project/standalone/deepmd_bridge/src:$DP_ROOT/project/mlcc-agent/src"
source "$DP_ROOT/project/workspace/configs/deepmd-lammps-env-v001.sh"
DP_CASE="$DP_ROOT/system/tasks/p9-deepmd-lammps-public-v001"
cp "$DP_ROOT/engineering-v001/interface-frame.json" "$DP_CASE/frame.json"
"$DP_RUNTIME/bin/python" -m mlcc_deepmd interface-evaluate "$DP_CASE" > "$DP_CASE/python-evaluation.log"
"$DP_ANALYSIS" "$DP_ROOT/project/scripts/deepmd-runtime/verify_public_lammps.py" "$DP_ROOT" "$1"
