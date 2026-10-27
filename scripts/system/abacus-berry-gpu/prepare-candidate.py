from pathlib import Path
from difflib import unified_diff

ROOT = Path(__file__).resolve().parents[3]
report = ROOT / "workspace" / "reports" / "berry-gpu-build-v001"
source = report / "source-audit" / "source-tree" / "abacus-develop-3.10.1" / "source" / "module_io" / "unk_overlap_pw.cpp"
candidate = report / "candidate-source" / "module_io" / "unk_overlap_pw.cpp"
patch = ROOT / "scripts" / "system" / "abacus-berry-gpu" / "0001-berry-gpu-unkdotp-gpu-context.patch"

text = source.read_text(encoding="utf-8")
include_old = '''#include "module_parameter/parameter.h"\n#include "module_hamilt_pw/hamilt_pwdft/global.h"'''
include_new = '''#include "module_parameter/parameter.h"\n#include "module_hamilt_pw/hamilt_pwdft/global.h"\n\n#if defined(__CUDA)\n#include "module_base/module_device/memory_op.h"\n#endif'''
if include_old not in text:
    raise SystemExit("include anchor not found")
text = text.replace(include_old, include_new, 1)
old = '''\t// (2) fft and get value\n\trhopw->recip2real(phase, phase);\n    wfcpw->recip2real(&evc[0](ik_L, iband_L, 0), psi_r, ik_L);\n\n    for (int ir = 0; ir < rhopw->nrxx; ir++)\n    {\n        psi_r[ir] = psi_r[ir] * phase[ir];\n    }\n\n    // (3) calculate the overlap in ik_L and ik_R\n    wfcpw->real2recip(psi_r, psi_r, ik_R);'''
new = '''\t// (2) fft and get value\n\trhopw->recip2real(phase, phase);\n#if defined(__CUDA)\n    if (PARAM.inp.device == "gpu")\n    {\n        // Berry's boundary link receives host-side wavefunction coefficients.\n        // The GPU PW transforms require device pointers, so make the boundary\n        // explicit instead of passing a host pointer into the GPU FFT path.\n        const int npw_L = wfcpw->npwk[ik_L];\n        const int npw_R = wfcpw->npwk[ik_R];\n        std::complex<double>* psi_k_d = nullptr;\n        std::complex<double>* psi_r_d = nullptr;\n        resmem_zd_op()(gpu_ctx, psi_k_d, npw_L);\n        resmem_zd_op()(gpu_ctx, psi_r_d, wfcpw->nrxx);\n        syncmem_z2z_h2d_op()(gpu_ctx, cpu_ctx, psi_k_d,\n                             &evc[0](ik_L, iband_L, 0), npw_L);\n        wfcpw->recip_to_real(gpu_ctx, psi_k_d, psi_r_d, ik_L);\n        syncmem_z2z_d2h_op()(cpu_ctx, gpu_ctx, psi_r, psi_r_d, wfcpw->nrxx);\n        delmem_zd_op()(gpu_ctx, psi_k_d);\n        delmem_zd_op()(gpu_ctx, psi_r_d);\n\n        for (int ir = 0; ir < rhopw->nrxx; ir++)\n        {\n            psi_r[ir] = psi_r[ir] * phase[ir];\n        }\n\n        // (3) calculate the overlap in ik_L and ik_R\n        std::complex<double>* psi_real_d = nullptr;\n        std::complex<double>* psi_recip_d = nullptr;\n        resmem_zd_op()(gpu_ctx, psi_real_d, wfcpw->nrxx);\n        resmem_zd_op()(gpu_ctx, psi_recip_d, npw_R);\n        syncmem_z2z_h2d_op()(gpu_ctx, cpu_ctx, psi_real_d, psi_r, wfcpw->nrxx);\n        wfcpw->real_to_recip(gpu_ctx, psi_real_d, psi_recip_d, ik_R);\n        syncmem_z2z_d2h_op()(cpu_ctx, gpu_ctx, psi_r, psi_recip_d, npw_R);\n        delmem_zd_op()(gpu_ctx, psi_real_d);\n        delmem_zd_op()(gpu_ctx, psi_recip_d);\n    }\n    else\n#endif\n    {\n        wfcpw->recip2real(&evc[0](ik_L, iband_L, 0), psi_r, ik_L);\n\n        for (int ir = 0; ir < rhopw->nrxx; ir++)\n        {\n            psi_r[ir] = psi_r[ir] * phase[ir];\n        }\n\n        // (3) calculate the overlap in ik_L and ik_R\n        wfcpw->real2recip(psi_r, psi_r, ik_R);\n    }'''
if old not in text:
    raise SystemExit("FFT anchor not found")
text = text.replace(old, new, 1)
candidate.parent.mkdir(parents=True, exist_ok=True)
candidate.write_text(text, encoding="utf-8", newline="")
old_lines = source.read_text(encoding="utf-8").splitlines(keepends=True)
new_lines = text.splitlines(keepends=True)
diff = unified_diff(old_lines, new_lines,
                    fromfile="a/source/module_io/unk_overlap_pw.cpp",
                    tofile="b/source/module_io/unk_overlap_pw.cpp",
                    n=5)
patch.write_text("".join(diff), encoding="utf-8", newline="")
print(f"candidate={candidate}")
print(f"patch={patch}")
