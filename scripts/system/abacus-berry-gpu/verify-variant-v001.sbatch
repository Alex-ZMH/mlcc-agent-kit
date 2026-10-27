#!/usr/bin/env bash
#SBATCH --job-name=mlcc-berry-gpu-native-v001-verify
#SBATCH --partition=cpu
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=2G
#SBATCH --time=00:10:00
#SBATCH --no-requeue
set -euo pipefail

# This is a bounded software/input check.  It does not launch ABACUS or any
# other numerical solver.  The actual Berry candidate remains unsubmitted.
MLCC_ROOT=/home/v100/projects/mlcc/development/0.15.0/project
MLCC_PYTHON=/home/v100/projects/mlcc/development/0.9.0/venv/bin/python
MLCC_REPORT="$MLCC_ROOT/workspace/reports/berry-gpu-native-v001/verify-${SLURM_JOB_ID}"
mkdir -p "$MLCC_REPORT"
cd "$MLCC_ROOT"
export PYTHONPATH="$MLCC_ROOT/mlcc-agent/src"
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 MPLBACKEND=Agg

# Historical native CPU Berry evidence (job58) is a parser fixture only.
export MLCC_BERRY_NATIVE_TASK=/home/v100/projects/mlcc/development/0.10.0/project/workspace/tasks/p5-czo-berry-gdir1-cpu4-v001
export MLCC_BERRY_MODEL=/home/v100/projects/mlcc/development/0.10.0/project/workspace/models/cazro3-pnma-pristine/v001

# The negative GPU test must use the original unregistered 0.10 method.  It
# proves that an arbitrary GPU device flag cannot bypass the candidate gate.
export MLCC_BERRY_GPU_METHOD=/home/v100/projects/mlcc/development/0.10.0/project/workspace/configs/cazro3-berry-capability-v001.json
export MLCC_BERRY_REFERENCE_TASK=/home/v100/projects/mlcc/development/0.10.0/project/workspace/tasks/p5-czo-berry-scf-v001
export MLCC_BERRY_SITE=/home/v100/projects/mlcc/development/0.10.0/project/workspace/configs/site.v100-berry-dev-v001.json
export MLCC_BERRY_NSCF_REQUEST=/home/v100/projects/mlcc/development/0.10.0/project/workspace/configs/berry-gdir1-request-v001.json

hostname > "$MLCC_REPORT/hostname.txt"
scontrol show job "$SLURM_JOB_ID" -o > "$MLCC_REPORT/scheduler-running.txt"

"$MLCC_PYTHON" -m pytest -q \
  mlcc-agent/tests/test_berry_tasks.py::test_gpu_candidate_materializes_on_single_rank_and_records_binary \
  mlcc-agent/tests/test_berry_tasks.py::test_official_gpu_scf_reference_remains_materializable_without_candidate \
  mlcc-agent/tests/test_berry_tasks.py::test_gpu_berry_candidate_rejects_unknown_id_or_wrong_resource \
  mlcc-agent/tests/test_berry_tasks.py::test_real_v100_reference_rejects_gpu_berry_nscf \
  mlcc-agent/tests/test_berry.py::test_parse_berry_native_task_preserves_unbranched_record \
  mlcc-agent/tests/test_berry.py::test_parse_berry_rejects_gpu_without_registered_candidate_protocol \
  mlcc-agent/tests/test_berry.py::test_parse_berry_rejects_unknown_gpu_candidate_id \
  --junitxml="$MLCC_REPORT/changed-tests.xml" \
  > "$MLCC_REPORT/changed-tests.txt" 2>&1

# Input-only materialization follows the focused checks.  It writes the
# ordinary task, job.sbatch, and input_acceptance.json under the 0.15
# workspace; it does not transfer or submit them.
"$MLCC_PYTHON" scripts/system/abacus-berry-gpu/prepare-native-v001.py \
  > "$MLCC_REPORT/prepare-native-output.json"
cp "$MLCC_ROOT/workspace/reports/berry-gpu-native-v001/input_acceptance.json" \
  "$MLCC_REPORT/input_acceptance.json"
