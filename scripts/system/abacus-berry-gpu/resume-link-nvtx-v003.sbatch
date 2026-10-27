#!/bin/bash
# Diagnosed continuation of job152: CUDA12.9 header-only NVTX3 link selection.
# Private candidate only. No numerical task and no automatic retry.
#SBATCH --job-name=mlcc-berry-link-nvtx
#SBATCH --partition=cpu
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=00:30:00
#SBATCH --no-requeue
#SBATCH --output=berry-gpu-build-v003-%j.out
#SBATCH --error=berry-gpu-build-v003-%j.err
set -eo pipefail
source /home/v100/miniforge3/etc/profile.d/conda.sh
conda activate mlcc-abacus-berry-gpu-build-v001
set -u
export MPICH_CC="$CONDA_PREFIX/bin/x86_64-conda-linux-gnu-gcc"
export MPICH_CXX="$CONDA_PREFIX/bin/x86_64-conda-linux-gnu-g++"
export CUDAARCHS=70
BUILD_ROOT=/home/v100/projects/mlcc/tools/abacus-berry-gpu-v001
patch --forward -p1 -d "$BUILD_ROOT/src/candidate" < /home/v100/projects/mlcc/scripts/system/abacus-berry-gpu/0002-cuda-version-nvtx-link.patch
cmake -S "$BUILD_ROOT/src/candidate" -B "$BUILD_ROOT/build"
grep -- '-lcudart' "$BUILD_ROOT/build/CMakeFiles/abacus.dir/link.txt"
if grep -q -- '-lnvToolsExt' "$BUILD_ROOT/build/CMakeFiles/abacus.dir/link.txt"; then
  echo 'Legacy NVTX link remains after reviewed version-variable correction' >&2
  exit 2
fi
cmake --build "$BUILD_ROOT/build" --parallel 4
cmake --install "$BUILD_ROOT/build"
