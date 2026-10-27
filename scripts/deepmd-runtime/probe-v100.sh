#!/usr/bin/env bash
# Read-only v100 runtime probe. It does not install packages, write files,
# submit Slurm jobs, or start a numerical program.
set -euo pipefail

SSH_ALIAS=${SSH_ALIAS:-v100}

ssh "$SSH_ALIAS" 'bash -s' <<'REMOTE'
set +e
DEEP_RUNTIME=${DEEP_RUNTIME:-/home/v100/dpa4/current}

section() { printf '\n=== %s ===\n' "$1"; }

section HOST
hostname
uname -a

section GPU
nvidia-smi -L
nvidia-smi --query-gpu=index,name,driver_version,memory.total,compute_cap --format=csv,noheader

section SLURM
sinfo -o '%P|%a|%l|%D|%G|%c|%m'
scontrol show config | sed -n '1,120p'

section CPU_MEMORY_DISK
nproc
lscpu | egrep 'Model name|Socket|Core|Thread|CPU\(s\)'
free -h
df -h /home/v100

section RUNTIME_PATHS
ls -ld "$DEEP_RUNTIME" "$DEEP_RUNTIME/bin" "$DEEP_RUNTIME/lib" 2>&1
readlink -f "$DEEP_RUNTIME" 2>&1
"$DEEP_RUNTIME/bin/python" --version 2>&1
"$DEEP_RUNTIME/bin/dp" --version 2>&1

section PACKAGE_VERSIONS
"$DEEP_RUNTIME/bin/python" -m pip list 2>&1 | egrep -i 'deepmd|dpdata|lammps|torch|cuda|nccl|mpi|horovod|ase|numpy' || true

section TORCH_CUDA
"$DEEP_RUNTIME/bin/python" - <<'PY'
import torch
print("torch", torch.__version__, "cuda", torch.version.cuda)
print("available", torch.cuda.is_available(), "count", torch.cuda.device_count())
print("arch_list", torch.cuda.get_arch_list())
print("distributed", torch.distributed.is_available())
try:
    print("nccl", torch.cuda.nccl.version())
except Exception as exc:
    print("nccl_error", type(exc).__name__, str(exc))
for index in range(torch.cuda.device_count()):
    prop = torch.cuda.get_device_properties(index)
    print(index, prop.name, prop.major, prop.minor, prop.total_memory)
PY

section DEEPMD_LIBS
DEEPMD_LIB="$DEEP_RUNTIME/lib/python3.12/site-packages/deepmd/lib"
ls -lh "$DEEPMD_LIB"/libdeepmd_c.so "$DEEPMD_LIB"/libdeepmd.so \
    "$DEEPMD_LIB"/libdeepmd_backend_pt.so "$DEEPMD_LIB"/libdeepmd_op_cuda.so \
    "$DEEPMD_LIB"/libdeepmd_lmpplugin.so 2>&1
ldd "$DEEPMD_LIB/libdeepmd_lmpplugin.so" 2>&1
readelf -d "$DEEPMD_LIB/libdeepmd_lmpplugin.so" 2>&1 | egrep 'NEEDED|RPATH|RUNPATH'

section LAMMPS_PLUGIN_ENTRYPOINT
"$DEEP_RUNTIME/bin/python" - <<'PY'
import importlib.metadata as metadata
import os
for entry in metadata.entry_points().select(group="lammps.plugins"):
    print(entry.name, entry.value, entry.dist.name, entry.dist.version)
from deepmd.lmp_check_build import get_op_dir
print("DEEPMD_OP_DIR", get_op_dir())
from lammps import executable
print("LAMMPS_PLUGIN_PATH", os.environ.get("LAMMPS_PLUGIN_PATH"))
print("LD_LIBRARY_PATH", os.environ.get("LD_LIBRARY_PATH"))
PY

section LAMMPS_HELP
"$DEEP_RUNTIME/bin/lmp" -h 2>&1 | sed -n '1,100p'

section MPI_AND_EXECUTABLES
command -v "$DEEP_RUNTIME/bin/mpirun"
"$DEEP_RUNTIME/bin/mpirun" --version 2>&1 | head -20
command -v dpdata || true
command -v horovodrun || true
command -v mpi4py || true

section DPA4_SEARCH
find /home/v100/dpa4 -maxdepth 4 -type f \( -name 'libdeepmd*' -o -name '*lammps*' -o -name '*dpdata*' \) -print 2>/dev/null | head -160
REMOTE
