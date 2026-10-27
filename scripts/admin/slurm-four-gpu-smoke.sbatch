#!/usr/bin/env bash
#SBATCH --job-name=mlcc-four-gpu-smoke
#SBATCH --no-requeue
#SBATCH --partition=gpu
#SBATCH --nodes=1
#SBATCH --ntasks=4
#SBATCH --cpus-per-task=1
#SBATCH --hint=nomultithread
#SBATCH --gpus-per-task=v100:1
#SBATCH --mem=4G
#SBATCH --time=00:02:00
#SBATCH --output=four-gpu-%j.out

set -euo pipefail
export CUDA_DEVICE_ORDER=PCI_BUS_ID
srun --mpi=none --gpu-bind=single:1 /home/v100/mlcc-slurm-setup/slurm-gpu-smoke
