#!/usr/bin/env bash
# Prepare and build an isolated ABACUS v3.10.1 Berry GPU candidate.
# This script is deliberately not run by the MLCC local workflow. It never
# writes to the source checkout named by ABACUS_SOURCE; it stages a copy first.
set -euo pipefail

script_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
patch_file="${script_dir}/0001-berry-gpu-unkdotp-gpu-context.patch"

: "${ABACUS_SOURCE:?Set ABACUS_SOURCE to an extracted official v3.10.1 source tree}"
: "${ABACUS_STAGE:?Set ABACUS_STAGE to a new isolated staging directory}"
: "${ABACUS_RECIPE_PATCH_DIR:?Set ABACUS_RECIPE_PATCH_DIR to the fixed feedstock source-patch directory}"
: "${ABACUS_BUILD:?Set ABACUS_BUILD to a new CMake build directory}"
: "${ABACUS_INSTALL:?Set ABACUS_INSTALL to the candidate install prefix}"
: "${ABACUS_BUILD_ENV_PREFIX:?Set ABACUS_BUILD_ENV_PREFIX to the isolated conda build environment}"
: "${CUDA_TOOLKIT_ROOT:?Set CUDA_TOOLKIT_ROOT to the CUDA 12.9 development prefix}"
: "${ABACUS_LIBRI_DIR:?Set ABACUS_LIBRI_DIR to the staged LibRI source}"
: "${ABACUS_LIBCOMM_DIR:?Set ABACUS_LIBCOMM_DIR to the staged LibComm source}"
: "${CMAKE_C_COMPILER:?Set CMAKE_C_COMPILER to the isolated GCC 14 C compiler}"
: "${CMAKE_CXX_COMPILER:?Set CMAKE_CXX_COMPILER to the isolated GCC 14 C++ compiler}"
: "${CMAKE_CUDA_HOST_COMPILER:?Set CMAKE_CUDA_HOST_COMPILER to the GCC 14 compiler}"
: "${MPI_C_COMPILER:?Set MPI_C_COMPILER to the MPICH C wrapper}"
: "${MPI_CXX_COMPILER:?Set MPI_CXX_COMPILER to the MPICH C++ wrapper}"

for path in "$ABACUS_SOURCE" "$ABACUS_STAGE" "$ABACUS_BUILD" "$ABACUS_INSTALL"; do
    case "$path" in
        ""|/|.) echo "refusing unsafe path: $path" >&2; exit 2 ;;
    esac
done
if [[ ! -d "$ABACUS_SOURCE/source" ]]; then
    echo "ABACUS_SOURCE does not look like a v3.10.1 source tree: $ABACUS_SOURCE" >&2
    exit 2
fi
if [[ -e "$ABACUS_STAGE" ]]; then
    echo "ABACUS_STAGE must be absent; refusing to overwrite: $ABACUS_STAGE" >&2
    exit 2
fi
if [[ ! -f "$patch_file" ]]; then
    echo "candidate patch is missing: $patch_file" >&2
    exit 2
fi
for recipe_patch in 6760.patch 6772.patch; do
    if [[ ! -f "${ABACUS_RECIPE_PATCH_DIR}/${recipe_patch}" ]]; then
        echo "required feedstock source patch is missing: ${ABACUS_RECIPE_PATCH_DIR}/${recipe_patch}" >&2
        exit 2
    fi
done

for compiler in "$CMAKE_C_COMPILER" "$CMAKE_CXX_COMPILER" "$CMAKE_CUDA_HOST_COMPILER" "$MPI_C_COMPILER" "$MPI_CXX_COMPILER"; do
    if [[ ! -x "$compiler" ]]; then
        echo "required isolated compiler/wrapper is not executable: $compiler" >&2
        exit 2
    fi
done

# The C++ compiler used by CMake and NVCC must be the same GCC 14 binary.
if [[ "$(readlink -f -- "$CMAKE_CXX_COMPILER")" != "$(readlink -f -- "$CMAKE_CUDA_HOST_COMPILER")" ]]; then
    echo "CMAKE_CXX_COMPILER and CMAKE_CUDA_HOST_COMPILER must resolve to the same compiler" >&2
    exit 2
fi

if [[ "$(readlink -f -- "$CMAKE_C_COMPILER")" != "$(readlink -f -- "$ABACUS_BUILD_ENV_PREFIX/bin/x86_64-conda-linux-gnu-gcc")" ]]; then
    echo "CMAKE_C_COMPILER is outside the declared isolated GCC 14 prefix" >&2
    exit 2
fi
if [[ "$(readlink -f -- "$CMAKE_CXX_COMPILER")" != "$(readlink -f -- "$ABACUS_BUILD_ENV_PREFIX/bin/x86_64-conda-linux-gnu-g++")" ]]; then
    echo "CMAKE_CXX_COMPILER is outside the declared isolated GCC 14 prefix" >&2
    exit 2
fi

export CC="$CMAKE_C_COMPILER"
export CXX="$CMAKE_CXX_COMPILER"
export MPICH_CC="$CMAKE_C_COMPILER"
export MPICH_CXX="$CMAKE_CXX_COMPILER"
echo "C compiler: $CC"
echo "C++ compiler: $CXX"
echo "CUDA host compiler: $CMAKE_CUDA_HOST_COMPILER"
echo "MPI C wrapper: $MPI_C_COMPILER"
echo "MPI C++ wrapper: $MPI_CXX_COMPILER"
echo "MPI C wrapper command: $($MPI_C_COMPILER -show 2>&1)"
echo "MPI C++ wrapper command: $($MPI_CXX_COMPILER -show 2>&1)"

if [[ "${CUDAARCHS:-70}" != "70" ]]; then
    echo "this V100 candidate build accepts only CUDAARCHS=70" >&2
    exit 2
fi
export CUDAARCHS=70

mkdir -p "$(dirname -- "$ABACUS_STAGE")" "$(dirname -- "$ABACUS_BUILD")" "$(dirname -- "$ABACUS_INSTALL")"
cp -a --reflink=auto "$ABACUS_SOURCE" "$ABACUS_STAGE"
for recipe_patch in 6760.patch 6772.patch; do
    patch --forward -p1 -d "$ABACUS_STAGE" < "${ABACUS_RECIPE_PATCH_DIR}/${recipe_patch}"
done
patch --forward -p1 -d "$ABACUS_STAGE" < "$patch_file"

export CMAKE_PREFIX_PATH="${CUDA_TOOLKIT_ROOT}${CMAKE_PREFIX_PATH:+:${CMAKE_PREFIX_PATH}}"

cmake -S "$ABACUS_STAGE" -B "$ABACUS_BUILD" \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_INSTALL_PREFIX="$ABACUS_INSTALL" \
    -DUSE_CUDA=1 \
    -DCUDA_TOOLKIT_ROOT="$CUDA_TOOLKIT_ROOT" \
    -DENABLE_LIBXC=1 \
    -DENABLE_LIBRI=1 \
    -DGIT_SUBMODULE=0 \
    -DLIBRI_DIR="$ABACUS_LIBRI_DIR" \
    -DLIBCOMM_DIR="$ABACUS_LIBCOMM_DIR" \
    -DBLA_VENDOR=Generic \
    -DCMAKE_CXX_STANDARD=17 \
    -DCMAKE_C_COMPILER="$CMAKE_C_COMPILER" \
    -DCMAKE_CXX_COMPILER="$CMAKE_CXX_COMPILER" \
    -DCMAKE_CUDA_COMPILER="$CUDA_TOOLKIT_ROOT/bin/nvcc" \
    -DCMAKE_CUDA_ARCHITECTURES="$CUDAARCHS" \
    -DCMAKE_CUDA_HOST_COMPILER="$CMAKE_CUDA_HOST_COMPILER" \
    -DMPI_C_COMPILER="$MPI_C_COMPILER" \
    -DMPI_CXX_COMPILER="$MPI_CXX_COMPILER"

cmake --build "$ABACUS_BUILD" --parallel "${BUILD_JOBS:-4}"
cmake --install "$ABACUS_BUILD"
