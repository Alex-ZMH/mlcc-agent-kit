#!/usr/bin/env bash
#SBATCH --job-name=mlcc-charged-scf-fix
#SBATCH --partition=cpu
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=4096M
#SBATCH --time=00:05:00
#SBATCH --no-requeue
#SBATCH --output=workspace/reports/charged-scf-v002/check-%j.out
#SBATCH --error=workspace/reports/charged-scf-v002/check-%j.err
set -euo pipefail
# Recheck corrected electronic extraction; run downstream checks not reached in71.
export PYTHONPATH="$PWD/mlcc-agent/src"
python_bin=/home/v100/projects/mlcc/development/0.9.0/venv/bin/python
"$python_bin" -m pytest -q mlcc-agent/tests/test_electronic.py \
  --junitxml=workspace/reports/charged-scf-v002/electrons.xml
"$python_bin" -m pytest -q mlcc-agent/tests/test_elastic.py \
  -k 'native_input or neutral_native_consumers' \
  --junitxml=workspace/reports/charged-scf-v002/neutral-consumers.xml
"$python_bin" -m pytest -q mlcc-agent/tests/test_workflow.py \
  -k charged_scf \
  --junitxml=workspace/reports/charged-scf-v002/charged-workflow.xml
