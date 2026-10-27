#!/usr/bin/env bash
#SBATCH --job-name=mlcc-charged-native-accept
#SBATCH --partition=cpu
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=4096M
#SBATCH --time=00:05:00
#SBATCH --no-requeue
#SBATCH --output=workspace/reports/charged-scf-native-v001/verify-%j.out
#SBATCH --error=workspace/reports/charged-scf-native-v001/verify-%j.err
set -euo pipefail
MLCC_ROOT=/home/v100/projects/mlcc/development/0.10.0/project
cd "$MLCC_ROOT"
export PYTHONPATH="$MLCC_ROOT/mlcc-agent/src"
export OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1
/home/v100/projects/mlcc/development/0.9.0/venv/bin/python scripts/system/verify_charged_scf_native_v001.py \
  --bundle-root "$MLCC_ROOT/mlcc-agent" \
  --report-dir "$MLCC_ROOT/workspace/reports/charged-scf-native-v001/native-check-${SLURM_JOB_ID}"
# Only consumers changed by printed-weight handling; no frozen suite rerun.
/home/v100/projects/mlcc/development/0.9.0/venv/bin/python -m pytest -q mlcc-agent/tests/test_electronic.py \
  -k 'native_fixed_levels or ni_native_spin or gaussian_dos_includes or native_gamma_cartesian_product' \
  --junitxml="workspace/reports/charged-scf-native-v001/native-check-${SLURM_JOB_ID}/affected-electronic.xml"
