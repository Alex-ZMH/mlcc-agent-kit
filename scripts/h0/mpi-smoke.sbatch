#!/bin/bash
#SBATCH --job-name=mlcc-mpi-cuda
#SBATCH --partition=gpu
#SBATCH --nodes=1
#SBATCH --cpus-per-task=1
#SBATCH --gpus-per-task=v100:1
#SBATCH --hint=nomultithread
#SBATCH --mem=4096M
#SBATCH --time=00:03:00
#SBATCH --no-requeue
set -e
source /home/v100/projects/mlcc/configs/vasp-nvhpc-env.sh
date --iso-8601=seconds
printf 'job=%s ntasks=%s visible=%s\n' "$SLURM_JOB_ID" "$SLURM_NTASKS" "$CUDA_VISIBLE_DEVICES"
mpirun --map-by slot --bind-to core --report-bindings /home/v100/projects/mlcc/bin/mpi_cuda_reduction
