#!/bin/bash
#SBATCH --job-name=mlcc-dp-interface
#SBATCH --partition=gpu
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --gres=gpu:v100:1
#SBATCH --mem=8G
#SBATCH --time=00:10:00
#SBATCH --no-requeue
set -euo pipefail
DP_ROOT=/home/v100/projects/mlcc/development/deepmd-bridge-v001
DP_PROJECT="$DP_ROOT/project"
DP_RUNTIME=/home/v100/dpa4/releases/3.2.0
DP_ANALYSIS=/home/v100/projects/mlcc/development/0.9.0/venv/bin/python
DP_CORE=/home/v100/projects/mlcc/development/0.11.0/project/mlcc-agent/src
DP_EXPERIMENT="$DP_ROOT/engineering-v001"
export PYTHONPATH="$DP_PROJECT/standalone/deepmd_bridge/src:$DP_CORE"
export LD_LIBRARY_PATH="$DP_RUNTIME/lib:$DP_RUNTIME/lib/python3.12/site-packages/torch/lib:$DP_RUNTIME/lib/python3.12/site-packages/deepmd/lib"
export OMP_NUM_THREADS=2 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 NUM_WORKERS=0
export DP_INTRA_OP_PARALLELISM_THREADS=2 DP_INTER_OP_PARALLELISM_THREADS=1
scontrol show job "$SLURM_JOB_ID" -o
"$DP_ANALYSIS" -m mlcc_deepmd interface-prepare "$DP_EXPERIMENT/interface-frame.json" "$DP_EXPERIMENT/train-2gpu/frozen_model.pth" "$DP_EXPERIMENT/interface-2gpu-model" --type-map Ni
cd "$DP_EXPERIMENT/interface-2gpu-model"
"$DP_RUNTIME/bin/python" -m mlcc_deepmd interface-evaluate . > python-evaluation.log
"$DP_RUNTIME/bin/lmp" -in in.lammps > lammps-screen.log 2>&1
"$DP_ANALYSIS" -m mlcc_deepmd interface-compare . > comparison.log
