#!/usr/bin/env bash
#SBATCH --job-name=mlcc-charged-scf-contract
#SBATCH --partition=cpu
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=4096M
#SBATCH --time=00:10:00
#SBATCH --no-requeue
#SBATCH --output=workspace/reports/charged-scf-v001/check-%j.out
#SBATCH --error=workspace/reports/charged-scf-v001/check-%j.err
set -euo pipefail
# Software and saved-output checks only. No new ABACUS or MD execution.
export PYTHONPATH="$PWD/mlcc-agent/src"
python_bin=/home/v100/projects/mlcc/development/0.9.0/venv/bin/python
"$python_bin" -m pytest -q \
  mlcc-agent/tests/test_abacus.py \
  mlcc-agent/tests/test_method_inputs.py \
  mlcc-agent/tests/test_abacus_tasks.py \
  mlcc-agent/tests/test_electronic.py \
  --junitxml=workspace/reports/charged-scf-v001/input-electrons.xml
"$python_bin" -m pytest -q mlcc-agent/tests/test_elastic.py \
  -k 'native_input or neutral_native_consumers' \
  --junitxml=workspace/reports/charged-scf-v001/neutral-consumers.xml
"$python_bin" -m pytest -q mlcc-agent/tests/test_workflow.py \
  -k charged_scf \
  --junitxml=workspace/reports/charged-scf-v001/charged-workflow.xml
