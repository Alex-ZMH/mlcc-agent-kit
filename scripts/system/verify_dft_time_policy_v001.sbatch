#!/usr/bin/env bash
#SBATCH --job-name=mlcc-dft-time-policy
#SBATCH --partition=cpu
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=1024M
#SBATCH --time=00:03:00
#SBATCH --no-requeue
#SBATCH --output=workspace/reports/dft-time-policy-v001/check-%j.out
#SBATCH --error=workspace/reports/dft-time-policy-v001/check-%j.err
set -euo pipefail
# Software-only submission tests; no DFT, numerical model or new material task.
export PYTHONPATH="$PWD/mlcc-agent/src"
/home/v100/projects/mlcc/development/0.9.0/venv/bin/python -m pytest -q mlcc-agent/tests/test_site_runner.py --junitxml=workspace/reports/dft-time-policy-v001/runner.xml
