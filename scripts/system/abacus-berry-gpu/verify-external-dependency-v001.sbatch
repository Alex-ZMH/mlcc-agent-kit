#!/bin/bash
# Source50 read-only dependency binding; no DFT submission.
#SBATCH --job-name=mlcc-external-dependency
#SBATCH --partition=cpu
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=2G
#SBATCH --time=00:05:00
#SBATCH --no-requeue
#SBATCH --output=external-dependency-%j.out
#SBATCH --error=external-dependency-%j.err
set -eu
export PYTHONPATH=/home/v100/projects/mlcc/development/0.15.0/project/mlcc-agent/src
export MLCC_BERRY_REFERENCE_TASK=/home/v100/projects/mlcc/development/0.10.0/project/workspace/tasks/p5-czo-berry-scf-v001
export PYTHONDONTWRITEBYTECODE=1
export OMP_NUM_THREADS=1
/home/v100/projects/mlcc/development/0.9.0/venv/bin/python -m pytest \
 /home/v100/projects/mlcc/development/0.15.0/project/mlcc-agent/tests/test_external_dependencies.py \
 -q -p no:cacheprovider --junitxml=external-dependency-${SLURM_JOB_ID}.xml
