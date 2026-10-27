#!/bin/bash
#SBATCH --job-name=mlcc-berry-gpu-gdb
#SBATCH --partition=gpu
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=8G
#SBATCH --time=00:05:00
#SBATCH --gpus-per-task=v100:1
#SBATCH --hint=nomultithread
#SBATCH --no-requeue
set -eu
source /home/v100/projects/mlcc/configs/abacus-mpich-env-v001.sh
export OMP_NUM_THREADS=1
scontrol show job "$SLURM_JOB_ID" -o > scheduler-running.txt
nvidia-smi --query-gpu=index,uuid,name --format=csv > gpu-inventory.csv
# Diagnostic job only. GDB may stop the solver at SIGSEGV; its completion
# status must never be interpreted as a completed scientific calculation.
set +e
/home/v100/miniforge3/envs/abacus_env/bin/mpiexec.hydra -launcher slurm -rmk slurm -n 1 -bind-to core /usr/bin/gdb -nx -q -batch --return-child-result -x gdb.commands --args /home/v100/miniforge3/envs/abacus_env/bin/abacus > gdb-backtrace.txt 2>&1
MLCC_GDB_EXIT=$?
printf '%s\n' "$MLCC_GDB_EXIT" > gdb-launcher-exit.txt
exit "$MLCC_GDB_EXIT"
