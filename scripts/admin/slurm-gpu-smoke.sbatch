#!/usr/bin/env bash
#SBATCH --job-name=mlcc-gpu-smoke
#SBATCH --no-requeue
#SBATCH --partition=gpu
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --hint=nomultithread
#SBATCH --gres=gpu:v100:1
#SBATCH --mem=1G
#SBATCH --time=00:02:00
#SBATCH --array=0-3%4
#SBATCH --output=gpu-%A_%a.out

set -euo pipefail
export CUDA_DEVICE_ORDER=PCI_BUS_ID
srun --mpi=none --gres=gpu:v100:1 /home/v100/mlcc-slurm-setup/slurm-gpu-smoke
