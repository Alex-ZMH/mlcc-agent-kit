#!/usr/bin/env bash
#SBATCH --job-name=mlcc-cpu-smoke
#SBATCH --no-requeue
#SBATCH --partition=cpu
#SBATCH --nodes=1
#SBATCH --ntasks=2
#SBATCH --cpus-per-task=1
#SBATCH --hint=nomultithread
#SBATCH --mem=512M
#SBATCH --time=00:02:00
#SBATCH --output=cpu-%j.out

set -euo pipefail
srun --mpi=none --cpu-bind=cores /usr/bin/python3 -c 'import os; total = sum(value * value for value in range(1000000)); print("PASS CPU", "job=" + os.environ["SLURM_JOB_ID"], "rank=" + os.environ["SLURM_PROCID"], "affinity=" + str(sorted(os.sched_getaffinity(0))), "sum=" + str(total), flush=True)'
