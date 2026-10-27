#!/bin/bash
#SBATCH --job-name=mlcc-berry-build-deps
#SBATCH --partition=cpu
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --time=01:00:00
#SBATCH --no-requeue
#SBATCH --output=install-prefix-%j.out
#SBATCH --error=install-prefix-%j.err
set -eu
source /home/v100/miniforge3/etc/profile.d/conda.sh
conda create --yes --copy --strict-channel-priority --solver libmamba \
    --override-channels -c conda-forge \
    --name mlcc-abacus-berry-gpu-build-v001 \
    --file /home/v100/projects/mlcc/scripts/system/abacus-berry-gpu/conda-specs-v001.txt
conda list --name mlcc-abacus-berry-gpu-build-v001 --json > installed-prefix-packages.json
set +u
conda activate mlcc-abacus-berry-gpu-build-v001
set -u
nvcc --version
x86_64-conda-linux-gnu-g++ --version
cmake --version
MPICH_CC="$CONDA_PREFIX/bin/x86_64-conda-linux-gnu-gcc" mpicc -show
MPICH_CXX="$CONDA_PREFIX/bin/x86_64-conda-linux-gnu-g++" mpicxx -show
