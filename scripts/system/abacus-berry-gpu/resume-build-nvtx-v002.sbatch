#!/bin/bash
#SBATCH --job-name=mlcc-berry-build-nvtx
#SBATCH --partition=cpu
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=04:00:00
#SBATCH --no-requeue
#SBATCH --output=berry-gpu-build-v002-%j.out
#SBATCH --error=berry-gpu-build-v002-%j.err
set -eo pipefail
source /home/v100/miniforge3/etc/profile.d/conda.sh
conda activate mlcc-abacus-berry-gpu-build-v001
set -u
export MPICH_CC="$CONDA_PREFIX/bin/x86_64-conda-linux-gnu-gcc"
export MPICH_CXX="$CONDA_PREFIX/bin/x86_64-conda-linux-gnu-g++"
export CUDAARCHS=70
# job143 stopped at the missing NVTX3 header. The matching header tree is
# already supplied by this private prefix's Nsight Compute package.
# Copy it once into the compiler's existing include path; no shared files change.
test ! -e "$CONDA_PREFIX/include/nvtx3"
cp -a "$CONDA_PREFIX/nsight-compute-2025.2.1/host/target-linux-x64/nvtx/include/nvtx3" "$CONDA_PREFIX/include/nvtx3"
cmake --build /home/v100/projects/mlcc/tools/abacus-berry-gpu-v001/build --parallel 4
cmake --install /home/v100/projects/mlcc/tools/abacus-berry-gpu-v001/build
