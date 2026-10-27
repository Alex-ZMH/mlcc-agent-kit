#!/bin/bash
#SBATCH --job-name=mlcc-v0100-acceptance
#SBATCH --partition=cpu
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=4G
#SBATCH --time=00:15:00
#SBATCH --no-requeue
set -euo pipefail
MLCC_ROOT=/home/v100/projects/mlcc/development/0.10.0/project
MLCC_PYTHON=/home/v100/projects/mlcc/development/0.9.0/venv/bin/python
MLCC_REPORT="$MLCC_ROOT/workspace/reports/system-v0100/remote-${SLURM_JOB_ID}"
mkdir "$MLCC_REPORT"
cd "$MLCC_ROOT"
export PYTHONPATH="$MLCC_ROOT/mlcc-agent/src"
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 MPLBACKEND=Agg
export MLCC_BERRY_NATIVE_TASK="$MLCC_ROOT/workspace/tasks/p5-czo-berry-gdir1-cpu-v001"
export MLCC_BERRY_METHOD="$MLCC_ROOT/workspace/configs/cazro3-berry-cpu-capability-v001.json"
export MLCC_BERRY_NSCF_REQUEST="$MLCC_ROOT/workspace/configs/berry-gdir1-cpu-request-v001.json"
hostname > "$MLCC_REPORT/hostname.txt"
scontrol show job "$SLURM_JOB_ID" -o > "$MLCC_REPORT/scheduler-running.txt"
"$MLCC_PYTHON" scripts/system/record_native_job.py --task "$MLCC_BERRY_NATIVE_TASK/task.json" --job-id 55 > "$MLCC_REPORT/native-scheduler.json"
"$MLCC_PYTHON" -m mlcc parse-berry --task "$MLCC_BERRY_NATIVE_TASK/task.json" > "$MLCC_REPORT/native-berry.json"
"$MLCC_PYTHON" -m pytest -q mlcc-agent/tests --junitxml="$MLCC_REPORT/unit-tests.xml" > "$MLCC_REPORT/unit-tests.txt" 2>&1
"$MLCC_PYTHON" scripts/system/verify_berry.py --bundle-root mlcc-agent --nscf-task "$MLCC_BERRY_NATIVE_TASK" --method "$MLCC_BERRY_METHOD" --report-dir "$MLCC_REPORT/berry" > "$MLCC_REPORT/berry-summary.txt" 2>&1
"$MLCC_PYTHON" scripts/system/verify_phonons.py --bundle-root mlcc-agent --report-dir "$MLCC_REPORT/phonons" > "$MLCC_REPORT/phonons-summary.txt" 2>&1
"$MLCC_PYTHON" scripts/system/verify_lammps_entrypoints.py --bundle-root mlcc-agent --report-dir "$MLCC_REPORT/lammps-entrypoints" > "$MLCC_REPORT/lammps-entrypoints-summary.txt" 2>&1
"$MLCC_PYTHON" scripts/system/verify_system_extensions.py --bundle-root mlcc-agent --report-dir "$MLCC_REPORT/extensions" > "$MLCC_REPORT/extensions-summary.txt" 2>&1
"$MLCC_PYTHON" scripts/system/verify_public_properties.py --bundle-root mlcc-agent --report-dir "$MLCC_REPORT/public-properties" > "$MLCC_REPORT/public-summary.txt" 2>&1
"$MLCC_PYTHON" scripts/system/verify_contracts.py --bundle-root mlcc-agent --report-dir "$MLCC_REPORT/contracts" > "$MLCC_REPORT/contracts-summary.txt" 2>&1
"$MLCC_PYTHON" scripts/system/verify_ca_compatibility.py --bundle-root mlcc-agent --output "$MLCC_REPORT/ca-native-regression.json" > "$MLCC_REPORT/ca-summary.txt" 2>&1
