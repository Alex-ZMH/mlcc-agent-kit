#!/bin/bash
#SBATCH --job-name=mlcc-dp-handoff
#SBATCH --partition=cpu
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=4G
#SBATCH --time=00:05:00
#SBATCH --no-requeue
set -euo pipefail
DP_ROOT=/home/v100/projects/mlcc/development/deepmd-bridge-v001
DP_PROJECT="$DP_ROOT/project"
DP_ANALYSIS=/home/v100/projects/mlcc/development/0.9.0/venv/bin/python
export PYTHONPATH="$DP_PROJECT/standalone/deepmd_bridge/src:$DP_PROJECT/mlcc-agent/src"
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
cd "$DP_PROJECT"
"$DP_ANALYSIS" scripts/deepmd-runtime/collect_engineering.py --site workspace/configs/deepmd-runtime-v001.json "$@"
"$DP_ANALYSIS" -m pytest -q standalone/deepmd_bridge/tests mlcc-agent/tests/test_site_runner.py --junitxml="$DP_ROOT/reports/handoff-tests-$SLURM_JOB_ID.xml"
