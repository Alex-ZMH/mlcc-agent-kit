#!/usr/bin/env bash
# DeePMD-kit PyTorch DDP training template for the first 2-GPU engineering run.
# This is a template only; it is never submitted by this repository script.
# The input must already be prepared from ABACUS labels in an MLCC directory.

#SBATCH --job-name=mlcc-deepmd-pt-2g
#SBATCH --partition=gpu
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --gres=gpu:v100:2
#SBATCH --mem=12G
#SBATCH --time=02:00:00
#SBATCH --no-requeue
#SBATCH --output=deepmd-train-2gpu-%j.out

set -euo pipefail

DEEP_RUNTIME=${DEEP_RUNTIME:-/home/v100/dpa4/releases/3.2.0}
: "${DEEPMD_INPUT:?set DEEPMD_INPUT to an existing absolute DeePMD JSON/YAML input}"
DEEPMD_RUN_DIR=${DEEPMD_RUN_DIR:-$PWD}

test -x "$DEEP_RUNTIME/bin/python"
test -x "$DEEP_RUNTIME/bin/dp"
test -x "$DEEP_RUNTIME/bin/torchrun"
test -r "$DEEPMD_INPUT"
test -d "$DEEPMD_RUN_DIR"

cd "$DEEPMD_RUN_DIR"
export CUDA_DEVICE_ORDER=PCI_BUS_ID
export OMP_NUM_THREADS=${OMP_NUM_THREADS:-2}
export DP_INTRA_OP_PARALLELISM_THREADS=${DP_INTRA_OP_PARALLELISM_THREADS:-2}
export DP_INTER_OP_PARALLELISM_THREADS=${DP_INTER_OP_PARALLELISM_THREADS:-2}
export NCCL_DEBUG=${NCCL_DEBUG:-INFO}

visible=${CUDA_VISIBLE_DEVICES:?Slurm did not set CUDA_VISIBLE_DEVICES}
visible_count=$(awk -F, '{print NF}' <<<"$visible")
test "$visible_count" -eq 2

printf 'job_id=%s\n' "${SLURM_JOB_ID:-unknown}"
printf 'node_list=%s\n' "${SLURM_JOB_NODELIST:-unknown}"
printf 'runtime=%s\n' "$DEEP_RUNTIME"
printf 'input=%s\n' "$DEEPMD_INPUT"
printf 'run_dir=%s\n' "$DEEPMD_RUN_DIR"
printf 'cuda_visible_devices=%s\n' "$CUDA_VISIBLE_DEVICES"
printf 'torchrun_nproc_per_node=2\n'

"$DEEP_RUNTIME/bin/dp" --pt --version
"$DEEP_RUNTIME/bin/python" - <<'PY'
import torch
print("torch", torch.__version__)
print("torch_cuda", torch.version.cuda)
print("cuda_available", torch.cuda.is_available())
print("cuda_count", torch.cuda.device_count())
print("distributed", torch.distributed.is_available())
print("nccl", torch.cuda.nccl.version())
PY
nvidia-smi --query-gpu=index,name,driver_version,memory.total,compute_cap --format=csv,noheader

command=(
    "$DEEP_RUNTIME/bin/torchrun"
    --standalone
    --nproc_per_node=2
    --no-python
    "$DEEP_RUNTIME/bin/dp"
    --pt train
    --mpi-log workers
    "$DEEPMD_INPUT"
)
printf 'command='
printf '%q ' "${command[@]}"
printf '\n'
"${command[@]}"
