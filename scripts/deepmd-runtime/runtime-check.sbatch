#!/usr/bin/env bash
# Slurm-only, non-scientific runtime and plugin availability check.
# This does not train, evaluate a model, or run a LAMMPS simulation.
# The release path is intentionally pinned; do not replace it with `current`.
#
# Submit after copying this script to the v100 project directory, for example:
#   sbatch runtime-check.sbatch

#SBATCH --job-name=mlcc-dp-runtime
#SBATCH --partition=gpu
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --gres=gpu:v100:1
#SBATCH --mem=4G
#SBATCH --time=00:05:00
#SBATCH --no-requeue
#SBATCH --output=runtime-check-%j.out

set -euo pipefail

DEEP_RUNTIME=${DEEP_RUNTIME:-/home/v100/dpa4/releases/3.2.0}
test -x "$DEEP_RUNTIME/bin/python"
test -x "$DEEP_RUNTIME/bin/dp"
test -x "$DEEP_RUNTIME/bin/lmp"

export CUDA_DEVICE_ORDER=PCI_BUS_ID
export OMP_NUM_THREADS=${OMP_NUM_THREADS:-2}

printf 'job_id=%s\n' "${SLURM_JOB_ID:-unknown}"
printf 'node_list=%s\n' "${SLURM_JOB_NODELIST:-unknown}"
printf 'runtime=%s\n' "$DEEP_RUNTIME"
printf 'cuda_visible_devices=%s\n' "${CUDA_VISIBLE_DEVICES:-unset}"
printf 'slurm_gres=%s\n' "${SLURM_JOB_GRES:-${SLURM_TRES_PER_NODE:-unset}}"
printf 'cpu_count=%s\n' "${SLURM_CPUS_PER_TASK:-unset}"

nvidia-smi --query-gpu=index,name,driver_version,memory.total,compute_cap --format=csv,noheader

"$DEEP_RUNTIME/bin/dp" --pt --version
"$DEEP_RUNTIME/bin/dp" --pt -h | sed -n '1,80p'

PLUGIN_DIR=$("$DEEP_RUNTIME/bin/python" -c 'from deepmd.lmp_check_build import get_op_dir; print(get_op_dir())')
PLUGIN_SO="$PLUGIN_DIR/libdeepmd_lmpplugin.so"
test -f "$PLUGIN_SO"
TORCH_LIB=$("$DEEP_RUNTIME/bin/python" -c 'import os, torch; print(os.path.join(os.path.dirname(torch.__file__), "lib"))')
# Native liblammps loads libmpi/libtorch before Python can alter its process
# environment, so establish these paths in the Slurm shell first.
export LD_LIBRARY_PATH="$DEEP_RUNTIME/lib:$TORCH_LIB:$PLUGIN_DIR${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
printf 'deepmd_plugin_dir=%s\n' "$PLUGIN_DIR"
printf 'deepmd_plugin=%s\n' "$PLUGIN_SO"
printf 'torch_lib=%s\n' "$TORCH_LIB"

"$DEEP_RUNTIME/bin/python" - "$PLUGIN_SO" <<'PY'
import importlib.metadata as metadata
import os
import sys

from lammps import lammps

plugin_so = sys.argv[1]
print("lammps_plugin_path", os.environ.get("LAMMPS_PLUGIN_PATH", "unset"))
print("lammps_entrypoints")
for entry in metadata.entry_points().select(group="lammps.plugins"):
    print(entry.name, entry.value, entry.dist.name, entry.dist.version)

engine = lammps(cmdargs=["-log", "none", "-screen", "none"])
try:
    print("plugins_before", engine.available_plugins())
    if not engine.has_style("pair", "deepmd"):
        engine.command(f"plugin load {plugin_so}")
    print("plugins_after", engine.available_plugins())
    print("pair_deepmd", engine.has_style("pair", "deepmd"))
    print("pair_deepspin", engine.has_style("pair", "deepspin"))
    if not engine.has_style("pair", "deepmd"):
        raise RuntimeError("LAMMPS pair_style deepmd is unavailable after plugin load")
finally:
    engine.close()
PY

"$DEEP_RUNTIME/bin/python" -c 'from lammps.executable import lmp; lmp()' -h | sed -n '1,80p'
