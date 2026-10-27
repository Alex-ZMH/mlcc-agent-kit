#!/usr/bin/env bash
# LAMMPS/DeepMD plugin run-0 template.
# The supplied input must contain a real pair_style deepmd invocation and a
# frozen model. This script does not create a synthetic model or run an input
# by itself; the input and its model stay in the MLCC run directory.

#SBATCH --job-name=mlcc-deepmd-lmp
#SBATCH --partition=gpu
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --gres=gpu:v100:1
#SBATCH --mem=4G
#SBATCH --time=00:10:00
#SBATCH --no-requeue
#SBATCH --output=deepmd-lammps-%j.out

set -euo pipefail

DEEP_RUNTIME=${DEEP_RUNTIME:-/home/v100/dpa4/releases/3.2.0}
: "${DEEPMD_LAMMPS_INPUT:?set DEEPMD_LAMMPS_INPUT to an existing absolute LAMMPS input}"
DEEPMD_RUN_DIR=${DEEPMD_RUN_DIR:-$PWD}
DEEPMD_LAMMPS_LOG=${DEEPMD_LAMMPS_LOG:-deepmd-lammps-${SLURM_JOB_ID:-local}.log}

test -x "$DEEP_RUNTIME/bin/python"
test -x "$DEEP_RUNTIME/bin/python"
test -r "$DEEPMD_LAMMPS_INPUT"
test -d "$DEEPMD_RUN_DIR"

cd "$DEEPMD_RUN_DIR"
export CUDA_DEVICE_ORDER=PCI_BUS_ID
export OMP_NUM_THREADS=${OMP_NUM_THREADS:-2}

# The release Python entrypoint loads this entry point and establishes the
# matching MPICH/Torch/DeePMD shared-library paths before native lmp runs.
DEEPMD_PLUGIN_DIR=$("$DEEP_RUNTIME/bin/python" -c 'from deepmd.lmp_check_build import get_op_dir; print(get_op_dir())')
DEEPMD_PLUGIN_SO="$DEEPMD_PLUGIN_DIR/libdeepmd_lmpplugin.so"
test -f "$DEEPMD_PLUGIN_SO"
export LAMMPS_PLUGIN_PATH="$DEEPMD_PLUGIN_DIR${LAMMPS_PLUGIN_PATH:+:$LAMMPS_PLUGIN_PATH}"

printf 'job_id=%s\n' "${SLURM_JOB_ID:-unknown}"
printf 'node_list=%s\n' "${SLURM_JOB_NODELIST:-unknown}"
printf 'runtime=%s\n' "$DEEP_RUNTIME"
printf 'input=%s\n' "$DEEPMD_LAMMPS_INPUT"
printf 'log=%s\n' "$DEEPMD_LAMMPS_LOG"
printf 'deepmd_plugin=%s\n' "$DEEPMD_PLUGIN_SO"
printf 'cuda_visible_devices=%s\n' "${CUDA_VISIBLE_DEVICES:-unset}"

"$DEEP_RUNTIME/bin/dp" --pt --version
command=(
    "$DEEP_RUNTIME/bin/python"
    -c 'from lammps.executable import lmp; lmp()'
    -log "$DEEPMD_LAMMPS_LOG"
    -in "$DEEPMD_LAMMPS_INPUT"
)
printf 'command='
printf '%q ' "${command[@]}"
printf '\n'
"${command[@]}"
