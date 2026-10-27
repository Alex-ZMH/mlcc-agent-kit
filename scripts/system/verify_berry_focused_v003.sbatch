#!/bin/bash
#SBATCH --job-name=mlcc-berry-focused
#SBATCH --partition=cpu
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=4G
#SBATCH --time=00:05:00
#SBATCH --no-requeue
set -euo pipefail
MLCC_ROOT=/home/v100/projects/mlcc/development/0.10.0/project
MLCC_PYTHON=/home/v100/projects/mlcc/development/0.9.0/venv/bin/python
MLCC_REPORT="$MLCC_ROOT/workspace/reports/berry-v001/focused-${SLURM_JOB_ID}"
mkdir "$MLCC_REPORT"
cd "$MLCC_ROOT"
export PYTHONPATH="$MLCC_ROOT/mlcc-agent/src"
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 MPLBACKEND=Agg
export MLCC_BERRY_NATIVE_TASK="$MLCC_ROOT/workspace/tasks/p5-czo-berry-gdir1-cpu4-v001"
export MLCC_BERRY_METHOD="$MLCC_ROOT/workspace/configs/cazro3-berry-cpu-capability-v001.json"
export MLCC_BERRY_NSCF_REQUEST="$MLCC_ROOT/workspace/configs/berry-gdir1-cpu4-request-v001.json"
hostname > "$MLCC_REPORT/hostname.txt"
scontrol show job "$SLURM_JOB_ID" -o > "$MLCC_REPORT/scheduler-running.txt"
"$MLCC_PYTHON" -m mlcc parse-berry --task "$MLCC_BERRY_NATIVE_TASK/task.json" > "$MLCC_REPORT/native-berry.json"
"$MLCC_PYTHON" -m pytest -q mlcc-agent/tests/test_berry.py mlcc-agent/tests/test_berry_tasks.py mlcc-agent/tests/test_workflow.py -k berry --junitxml="$MLCC_REPORT/tests.xml" > "$MLCC_REPORT/tests.txt" 2>&1
"$MLCC_PYTHON" scripts/system/verify_berry.py --bundle-root mlcc-agent --nscf-task "$MLCC_BERRY_NATIVE_TASK" --method "$MLCC_BERRY_METHOD" --report-dir "$MLCC_REPORT/entrypoints" > "$MLCC_REPORT/entrypoints.txt" 2>&1
