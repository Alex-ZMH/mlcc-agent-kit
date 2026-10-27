# ABACUS Berry GPU link-fix proposal v001

**Date:** 2026-10-22  
**Scope:** CUDA 12.9 Berry GPU candidate build only  
**Status:** proposal for primary-agent review; not applied and not submitted

## Observed failure

Slurm job 152 (`mlcc-berry-build-nvtx`) built the ABACUS objects and failed at
the final executable link. The native linker reported:

```text
x86_64-conda-linux-gnu-ld: cannot find -lnvToolsExt: No such file or directory
collect2: error: ld returned 1 exit status
```

The generated `CMakeFiles/abacus.dir/link.txt` contains `-lnvToolsExt`, but
neither `libnvToolsExt.so` nor `libnvToolsExt.a` is present in either CUDA
library directory used by the isolated CUDA 12.9 environment.

## Root cause

The staged ABACUS 3.10.1 `CMakeLists.txt` has this sequence:

```cmake
if(NOT DEFINED CMAKE_CUDA_ARCHITECTURES)
  find_package(CUDAToolkit REQUIRED)
  ...
endif()
enable_language(CUDA)
if (CUDAToolkit_VERSION VERSION_GREATER_EQUAL 12.9)
  target_link_libraries(${ABACUS_BIN_NAME} cudart)
else ()
  target_link_libraries(${ABACUS_BIN_NAME} cudart nvToolsExt)
endif ()
```

The build configuration explicitly supplies `-DCMAKE_CUDA_ARCHITECTURES=70`.
Consequently, the guarded `find_package(CUDAToolkit REQUIRED)` is skipped and
`CUDAToolkit_VERSION` is not populated. After CUDA language enablement, the
empty version comparison selects the legacy `nvToolsExt` branch even though
the compiler/toolkit is CUDA 12.9.86.

The source CUDA header already selects the CUDA 12.9 NVTX3 header:

```cpp
#if CUDA_VERSION < 12090
#include "nvToolsExt.h"
#else
#include "nvtx3/nvToolsExt.h"
#endif
```

The installed `nvtx3/nvToolsExt.h` is the CUDA 12.9 header-only API. Normal
NVTX3 use supplies inline implementations and does not require a separate
`libnvToolsExt` link target.

## Minimal source fix

In the private staged candidate's CUDA link condition, replace the undefined
package version variable with the compiler version that is guaranteed to be
available after `enable_language(CUDA)`:

```diff
-  if (CUDAToolkit_VERSION VERSION_GREATER_EQUAL 12.9)
+  if (CMAKE_CUDA_COMPILER_VERSION VERSION_GREATER_EQUAL 12.9)
```

This keeps the existing CUDA 12.9 behavior (`cudart` only), keeps the legacy
`nvToolsExt` link for genuinely older CUDA toolkits, and does not alter the
Berry input or runtime route.

## Required continuation steps

1. Apply the one-line change only to the private candidate source tree used by
   the Berry GPU build.
2. Re-run the existing CMake configure command for that build directory. The
   generated `link.txt` must be regenerated; editing the generated link file
   alone is not a source-level fix.
3. Inspect the regenerated link command before building. It must contain
   `-lcudart` and must not contain `-lnvToolsExt`.
4. Let the primary agent decide whether to submit the reviewed build. This
   proposal does not submit, install, or claim GPU acceptance.

## Rejected workarounds

- Do not create a fake `libnvToolsExt.so` or a symlink to an unrelated NVTX
  library. CUDA 12.9 uses the header-only NVTX3 route, and the found
  `libnvtx3interop.so.1.0.0` is not the legacy `nvToolsExt` library.
- Do not remove the NVTX include. CUDA 12.9 source compilation requires the
  existing `nvtx3/nvToolsExt.h` include.
- Do not rely on manually setting `CUDAToolkit_VERSION` in the configure
  command as the canonical fix. It masks the CMake variable-scope defect and
  makes future toolchain selection less reliable.

## Boundary and risk

This is a build-system diagnosis only. It does not establish that the patched
ABACUS executable runs a Berry GPU task, that GPU polarization is scientifically
valid, or that the candidate should be enabled. Those require the parent's
reviewed build and the separately declared native GPU acceptance task.
