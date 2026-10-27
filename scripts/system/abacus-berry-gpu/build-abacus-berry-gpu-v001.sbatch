#!/usr/bin/env bash
#SBATCH --job-name=mlcc-abacus-berry-gpu-build-v001
#SBATCH --partition=cpu
#SBATCH --cpus-per-task=4
#SBATCH --mem=16G
#SBATCH --time=04:00:00
#SBATCH --no-requeue
#SBATCH --output=berry-gpu-build-v001-%j.out
#SBATCH --error=berry-gpu-build-v001-%j.err

# Software build only. This job does not run DFT or Berry input.
# Submit only after the parent agent reviews the conda dry-run and source prefix.
# The conda activation hooks may read optional NVCC variables before they are
# defined. Keep nounset disabled during activation, then restore strict mode
# for the isolated build itself.
set -eo pipefail

mlcc_root="/home/v100/projects/mlcc"
tool_root="${mlcc_root}/tools/abacus-berry-gpu-v001"
source /home/v100/miniforge3/etc/profile.d/conda.sh
conda activate mlcc-abacus-berry-gpu-build-v001
set -u

export ABACUS_BUILD_ENV_PREFIX="$CONDA_PREFIX"
export CUDA_TOOLKIT_ROOT="$CONDA_PREFIX"
export CMAKE_C_COMPILER="$CONDA_PREFIX/bin/x86_64-conda-linux-gnu-gcc"
export CMAKE_CXX_COMPILER="$CONDA_PREFIX/bin/x86_64-conda-linux-gnu-g++"
export CMAKE_CUDA_HOST_COMPILER="$CMAKE_CXX_COMPILER"
export MPI_C_COMPILER="$CONDA_PREFIX/bin/mpicc"
export MPI_CXX_COMPILER="$CONDA_PREFIX/bin/mpicxx"
export CUDAARCHS=70
export BUILD_JOBS=4

export ABACUS_SOURCE="$tool_root/src/abacus-develop-3.10.1"
export ABACUS_STAGE="$tool_root/src/candidate"
export ABACUS_RECIPE_PATCH_DIR="$tool_root/recipe-patches"
export ABACUS_BUILD="$tool_root/build"
export ABACUS_INSTALL="$tool_root/install"
# Parent-owned staging must use recipe LibRI commit d4f732011c6c2d115f651c38796cf7ecf823393b.
export ABACUS_LIBRI_DIR="$tool_root/deps/libri"
# Parent-owned staging must use LibComm v0.1.1.
export ABACUS_LIBCOMM_DIR="$tool_root/deps/libcomm"

cd "$mlcc_root"
exec bash scripts/system/abacus-berry-gpu/build-abacus-berry-gpu-v001.sh
