# ABACUS 3.10.1 GPU Berry Job 53 问题记录

**2026-10-22 18:20更新：已有独立补丁准备，尚未编译或运行。** [精确配方核对](../workspace/reports/berry-gpu-build-v001/recipe-source-audit.md)纠正了源码身份：`4d3cbab83d...`属于conda-forge abacus-feedstock配方提交，不是ABACUS upstream提交。安装配方使用upstream v3.10.1归档，加6760/6772和CUDA12 CCCL修复。此前把运行时commit当源码revision的描述应按此纠正。

主线审阅的[候选补丁](../scripts/system/abacus-berry-gpu/0001-berry-gpu-unkdotp-gpu-context.patch)只处理`unkdotp_G0`的GPU波函数FFT边界，保持CPU原路径；复用现有memory_op别名、GPU上下文及npwk/nrxx缓冲合同，[静态审查记录](../workspace/reports/berry-gpu-build-v001/buffer-and-context-audit.md)和补丁适用性检查已完成。无编译成功或GPU修复成功证据。当前runtime缺CUDA12.9开发工具链；下一步准备独立CUDA12.9/GCC14/MPICH构建前缀，保持已安装引擎不动，预留约20GiB构建空间。仅本站V100，构建时显式CUDAARCHS=70，不编译全架构矩阵。编译是有限资源的软件作业；之后如具备可执行候选，首次DFT验证仍按同53输入、1V100/1MPI/1OMP/8GiB/time=0，只做一次新增功能检查并复用58对照，失败不自动重跑。

0.14已交付CPU既有原生结果的只读消费和显式分支接口，不含GPU故障修复；真实多点极化/Born/介电来源仍待完成。负责人主线，恢复条件为独立构建可用并通过定向原生验证。

**记录日期：** 2026-10-22  
**问题任务：** `p5-czo-berry-gdir1-v001`，Slurm Job 53  
**范围：** v100 上 ABACUS 3.10.1 的 PW、`nspin=1`、NSCF、`gdir=1` Berry 极化 GPU 路径  
**结论性质：** 只读故障定位记录；不构成 GPU Berry 科学或生产资格

**后续定位更新（2026-10-22 11:58）**：已取得 v100 实际二进制的 GDB 调用栈和相关反汇编，见第 9 节。job61 在 5 分钟预算内运行 29 秒后捕获 SIGSEGV。已定位到 GPU 求解器进入 Berry 后，经 `unkdotp_G0 → PW_Basis_K::recip2real → FFT_Bundle::get_auxg_data<double>` 的 CPU 风格 FFT 缓冲访问路径跳转到空地址。此前“无回溯”描述仅是 job53 的原始证据状态；目前仍未修复 GPU 路线，也未得到有效 GPU 极化结果。

## 1. 结论摘要

Job 53 使用 v100 上安装的 ABACUS 3.10.1 CUDA/MPI 二进制运行 CaZrO₃ 的 Berry NSCF
任务。任务成功完成了输入初始化、从文件读取 SCF 电荷、一次 CG 对角化，并进入
`POLARIZATION CALCULATION`；随后以 `ExitCode=139:0`（SIGSEGV）退出。日志中没有
`VALUES OF POLARIZATION`、ionic/electronic phase、三种极化单位行或正常结束标识。

因此 Job 53 的结果是 **GPU Berry 运行失败且没有科学结果**。运行时失败和输入域检查
是两个独立状态：SIGSEGV 不反推这组 PW/NSCF/Berry 输入本身不合格；但在没有完整
Berry 原生输出前，数值、科学和生产资格仍不能建立。CPU 路径的兼容性证据与本故障
分开记录；CPU 任务完成不能把 GPU 路径升级为可用，也不能替代 GPU 原生证据。

公开 v3.10.1 tag 的源码审查支持一个“Berry 边界 overlap 可能发生主机/设备路径不一致”
的源码级假设，但当前没有调试器回溯，而且运行时日志报告的 commit 与公开 tag 不同，
所以不能把该假设写成已证实的崩溃根因。

## 2. 原生日志事实

下表只记录 Job 53 保留副本中的原生或调度器证据。

| 项目 | 原生观察 |
|---|---|
| Slurm 状态 | `FAILED`，`ExitCode=139:0`，运行约 30 s，时间上限 10 min |
| 资源 | 1 个 v100 节点、1 个 MPI rank、1 个可见 GPU；调度记录申请 8 GiB 内存 |
| ABACUS | 日志版本 `v3.10.1`，运行时打印 `Commit: 4d3cbab` |
| 设备 | `RUNNING WITH DEVICE : GPU / Tesla V100-SXM2-16GB` |
| 任务 | `calculation=nscf`、`basis_type=pw`、`nspin=1`、非 SOC、`symmetry=-1`、`berry_phase=1`、`gdir=1` |
| k 点/分布 | native `OUT.CZOBerry/INPUT` 回显 `kpar=1`；日志显示 8 个 k 点、1 个进程、1 个线程 |
| 电荷读取 | 日志依次打印 `try to read charge from file`、`Find the file .//SPIN1_CHG.cube`、`Read in the charge density: .//SPIN1_CHG.cube` |
| 对角化 | 日志出现 `CG1`，本次打印的时间为 21.81 s |
| 失败位置 | 先打印 `<< Start Berry phase polarization.`，之后 MPI 清理信息报告 `Segmentation fault (signal 11)` |
| Berry 输出 | 没有 `VALUES OF POLARIZATION`、`The Ionic Phase`、`Electronic Phase`、`P = ...` 或 `Finish Time`/`Total Time` |

Job 53 的顶层 `INPUT` 与 `OUT.CZOBerry/INPUT` 保留了相同的关键物理设置；后者还
回显了 `kpar=1`。Job 53 使用的 `SPIN1_CHG.cube` 是独立 SCF 任务产生并复制到当前
任务目录的电荷文件。电荷读取成功只证明该输入阶段被走到，不能证明 Berry overlap、
极化量或电子结构科学资格成立。

原始证据：

- [Job 53 调度记录](../workspace/tasks/p5-czo-berry-gdir1-v001/scheduler-latest.txt)
- [Job 53 stdout](../workspace/tasks/p5-czo-berry-gdir1-v001/stdout.log)
- [Job 53 native Berry 日志](../workspace/tasks/p5-czo-berry-gdir1-v001/OUT.CZOBerry/running_nscf.log)
- [Job 53 顶层 INPUT](../workspace/tasks/p5-czo-berry-gdir1-v001/INPUT)
- [Job 53 native INPUT 回显](../workspace/tasks/p5-czo-berry-gdir1-v001/OUT.CZOBerry/INPUT)

## 3. 版本和源码证据边界

### 3.1 安装包不是已证明的公开 tag 工作树

v100 运行时 stdout 记录 `ABACUS v3.10.1` 和 `Commit: 4d3cbab`。conda recipe
元数据只记录公开 `v3.10.1` 源码压缩包来源以及应用的 `6760.patch`、`6772.patch`；
它不是当前运行二进制的逐文件源码证明。既有 package metadata 记录另列出源码压缩包
SHA256 `06873eba8a4e0bc085177a6580455b28e4b62ea8a18f8afe71a02105756d91a0` 和完整
package-source revision `4d3cbab83d661a25770eee61ce9275be0bfebe08`；这两个字段来自
该 package metadata 记录，不应改写成 recipe 本身给出的构建 revision。

公开 `v3.10.1` tag 当前指向 `f71921fe848659deac8db319cd4311b55b5ad480`，与运行时
日志的 `4d3cbab` 不能等同。已检查到的 recipe patch 主要涉及 CUDA 版本设备代码、
CUDA 13 的 C++ 标准和 CUDA 错误枚举保护；这不等于已证明 Berry 相关文件没有其它
构建差异。当前没有安装二进制到公开 tag 的逐文件、逐提交源码映射。

所以以下源码只能作为 **公开 v3.10.1 tag 的基线证据**，不能单独证明 Job 53 使用了
完全相同的 Berry 实现。安装包和版本记录见
[ABACUS package metadata](../workspace/reports/h1/abacus-package-metadata.txt) 和
[ABACUS version record](../workspace/reports/h1/abacus-version.txt)。公开版本入口为
[ABACUS v3.10.1 release/tag](https://github.com/abacusmodeling/abacus-develop/releases/tag/v3.10.1)。

### 3.2 公开 tag 的相关调用路径

固定到公开 `v3.10.1` tag 的源码显示：

1. PW 求解器在 SCF/NSCF 后进入 Berry 计算路径；公开
   [`esolver_ks_pw.cpp`](https://github.com/deepmodeling/abacus-develop/blob/v3.10.1/source/module_esolver/esolver_ks_pw.cpp)
   是设备特化的 KS-PW 调用边界。
2. [`berryphase.cpp`](https://github.com/deepmodeling/abacus-develop/blob/v3.10.1/source/module_io/berryphase.cpp#L238-L273)
   的 `stringPhase()` 对相邻 k 点的波函数做 overlap；边界 link 调用
   `unkdotp_G0()`，其余 link 调用 `unkdotp_G()`。
3. [`unk_overlap_pw.cpp`](https://github.com/deepmodeling/abacus-develop/blob/v3.10.1/source/module_io/unk_overlap_pw.cpp#L60-L112)
   的 `unkdotp_G0()` 会调用 `recip2real()`、在实空间相乘、再调用 `real2recip()`，
   随后在 `POOL_WORLD` 上做复数 overlap 的 MPI reduction。该文件的注释还要求
   Berry 的 k-point pool 使用 `KPAR=1`；Job 53 的 native `OUT/INPUT` 回显了这一点。
4. [`pw_transform_k.cpp`](https://github.com/deepmodeling/abacus-develop/blob/v3.10.1/source/module_basis/module_pw/pw_transform_k.cpp#L155-L199)
   中的普通 `recip2real()` 使用常规 PW FFT/gather 路径；同文件另有带 device
   context 的 `recip_to_real(ctx, ...)` 路径，二者是不同的接口。
5. [`fft_bundle.cpp`](https://github.com/deepmodeling/abacus-develop/blob/v3.10.1/source/module_basis/module_pw/module_fft/fft_bundle.cpp#L53-L95)
   分别创建 CPU FFT 和 CUDA FFT 对象；[`esolver.cpp`](https://github.com/deepmodeling/abacus-develop/blob/v3.10.1/source/module_esolver/esolver.cpp#L120-L142)
   根据 `device` 选择 PW 求解器的设备特化。

这些源码事实说明 Berry 的边界 overlap 需要在波函数系数、实空间 FFT 和 MPI pool
之间切换；公开 tag 中调用者和 device-aware FFT 入口不是同一函数。它们支持“GPU
Berry 边界的 host/device 或 FFT 状态不一致可能触发崩溃”的**来源级假设**，但没有
提供 Job 53 的崩溃地址、调用栈或运行时内存状态，不能定位具体崩溃指令。

## 4. 未证实的原因和排除边界

目前无法从 Job 53 的日志中区分以下可能性：

- 公开 tag 与当前 `4d3cbab` 二进制、conda patch 或编译选项之间的 Berry 实现差异；
- GPU FFT/CUDA 运行时、波函数 buffer 或 device/host 生命周期问题；
- `recip2real`/`real2recip` 所需网格、波函数布局、带数或 communicator 状态不一致；
- 单 rank、k-point pool、GPU 可见设备和 MPI launcher 组合触发的运行时问题。

Job 53 是 1 个 rank；因此这里没有证据支持“多 rank 扩展导致失败”的结论。也没有
证据支持“电荷文件不完整”或“SCF 未完成”是原因，因为 native 日志明确打印了电荷
读取和 CG 对角化阶段已完成。相反，失败发生在 Berry banner 之后，但这个时间顺序
仍不足以证明具体的 overlap 子函数。

此前任何按 `nbands=88` 推导 Berry overlap 数量的估计都不应作为本问题的性能结论。
ABACUS 的 Berry 计算使用 native 占据带数；只有在 native 输出明确记录电子数或
占据带数后，才可给出数量级。`nbands` 是分配的总带数，不是本次 Berry overlap
复杂度中的占据带数。

## 5. 与 CPU 证据的关系

CPU 任务是同一 ABACUS 二进制的另一设备路径。之前的 CPU 串行任务 Job 55 在 10 min
时间上限内只到 Berry 阶段并因超时退出，说明该次资源预算不足；它不是 GPU 崩溃的
失败复现，也不是 GPU 资格证据。随后独立的 CPU4 任务 Job 58 已完成，native 日志
第 192 行记录 `nelec=160`、`occupied bands=80`、`NBANDS=88`，并在第 2018 行打印
`Finish Time : Thu Oct 22 11:43:11 2026`。Job 58 的 scheduler 记录显示实际分配
`NumTasks=4`、`NumCPUs=8`（8 个逻辑 CPU，申请 4 个 CPU）和 8 GiB 内存；native
stdout 回显 4 个 processor、4 个 thread。这些是 CPU 工程兼容性证据，仍不改变
Job 53 的 GPU 状态，也不证明 GPU Berry 可以生产运行。

Job 58 原生证据：[Berry 日志](../workspace/reports/berry-v001/job58/OUT.CZOBerry/running_nscf.log)、
[调度记录](../workspace/reports/berry-v001/job58/scheduler-latest.txt)。

本记录不重复提交或验证 CPU 任务。GPU 和 CPU 的设备状态必须在资格记录中分别保存。

## 6. 最小下一步和资源上限

本节是给主代理排程的最小方案，本文不提交作业。Job 53 在约 30 s 即发生 SIGSEGV，
单纯增加墙钟时间不会增加定位信息，因此禁止按原参数盲跑。

### 6.1 先做控制检查，不启动计算

首先只读检查 Job 53 保留目录和 v100 任务目录是否已有 core/core dump、崩溃报告或
可用的 native backtrace。已有 core 优先，避免再次运行。若没有 core，再检查当前已
安装的 `gdb`/`cuda-gdb` 或等效调试工具、ABACUS/相关库是否带可用符号，以及现有
Slurm 启动方式是否能够在不改二进制、不构建、不改精度的前提下可靠保留调用栈或
core。控制检查应同时记录工具版本、符号可见性、core 生成限制和启动命令；只要不能
确定新运行会增加调用栈或 core 证据，就不提交 GPU 任务。

截至本记录，当前保留的 Job 53 本地副本中没有发现 core 或 backtrace 文件；v100
调试工具/符号/启动能力检查尚未完成，且没有启动新的定位任务。

### 6.2 只有具备回溯能力时才运行一次

只有 6.1 确认已有 core，或确认一次新运行能够新增可读调用栈/core 时，才允许做
**一次新的、受控的 GPU 原生定位运行**。保留 Job 53 目录和 Job ID，不覆盖原始任务，
也不自动重试。保持以下物理与软件条件不变：

- 同一 v100 节点、同一已安装 ABACUS 二进制和环境；
- 同一 CaZrO₃ `STRU`、赝势、`KPT`、方法、SCF `SPIN1_CHG.cube` 和 `gdir=1`；
- `basis_type=pw`、`calculation=nscf`、`nspin=1`、非 SOC、`symmetry=-1`、`kpar=1`；
- 不改带数、截断能、k 网格、电荷来源或精度；只加入已确认能够保存回溯的运行控制，
  并收集 stdout/stderr、native log、`scontrol`、设备/动态库信息和 core/backtrace。

资源上限为：**1 个 V100、1 个 MPI rank、1 个 OpenMP thread、8 GiB 内存、5 min
墙钟时间、最多 1 次新运行**。不进行多 GPU、多 rank、k 网格、带数或二进制矩阵扫描，
不构建新二进制。无 core/backtrace 能力时不跑；若一次受控运行仍未新增可用回溯，
停止扩大资源，由主代理决定是否需要上游/构建层面的新证据。

若该受控运行产生完整 `VALUES OF POLARIZATION`、ionic/electronic phase、极化量子
和正常结束标识，仍需按 Berry 解析器和数值资格合同审查后才能开放 GPU；若再次崩溃，
回溯只能帮助定位故障，不能作为科学结果。

## 7. 资格边界

在 Job 53 之后，GPU Berry 应保持以下状态：

```text
native_gpu_berry: failed_job53
polarization_observation: absent
input_domain_status: verified_for_declared_pw_nscf_berry_route
runtime_status: failed_sigsegv
numerical_qualification: false
scientific_qualification: false
production_qualification: false
```

只有安装二进制在 GPU 上完成一次保留原生证据的 Berry 任务，日志包含全部必需的
phase/unit/quantum 输出，且输入、几何、参考电荷、k 点和方法一致性检查通过，才能
从 `failed_job53` 转入下一阶段。单点极化不能宣称自发极化、铁电性或介电张量。

## 8. 本轮检查范围

- [x] 只读核对 Job 53 调度记录、stdout、stderr 和 native `running_nscf.log`。
- [x] 只读核对顶层 `INPUT`、native `OUT/INPUT`、`KPT`、`STRU` 和实际电荷读取 marker。
- [x] 只读核对 v100 ABACUS 运行时 commit、package metadata、recipe patch 记录和公开 tag 基线，并分开记录来源。
- [x] 只读审查公开 v3.10.1 Berry、overlap、PW transform、FFT 和设备分派路径。
- [x] 明确公开源码只是 tag baseline，未将其当作当前二进制的精确源码映射。
- [x] 纠正 `nbands=88` 等同 occupied bands 的性能估计；当前未给出无 native 依据的带数。
- [x] 只读搜索 Job 53 本地保留副本，未发现 core/backtrace 文件；v100 调试工具/符号能力检查待主代理控制执行。
- [x] 未提交作业、未构建、未运行本地测试、未修改现有代码或已有文档。

## 9. 一次受控 GPU 回溯：job61

执行前控制检查确认：v100 有 GDB 15.1，ABACUS 未 strip，保留 `unkdotp_G0` 与 `Berry_Phase` 等函数符号；无对应保留 core/crash report，core limit 为 0。未修改系统 core 设置、未编译程序。随后在独立诊断目录复制 job53 的 INPUT/STRU/KPT/赝势和 job50 电荷，只增加 GDB 启动控制。

资源：1 V100、1 MPI、1 OMP、8 GiB、最多 5 分钟；实际 Slurm 分配 2 个逻辑 CPU。2026-10-22 11:58:30 开始，11:58:59 结束，29 秒。`JobState=FAILED / ExitCode=1:0` 是诊断启动器状态；被调试 ABACUS 明确收到 SIGSEGV。GDB 已保存调用栈，随后尝试反汇编 `pc=0` 报无法访问内存而退出。不能将该退出码解释成 DFT 收敛或输入失败。

主线程原生调用栈：

```text
0x0
PW_Basis_K::recip2real<double>
unkOverlap_pw::unkdotp_G0(... DEVICE_CPU ...)
berryphase::stringPhase
berryphase::Berry_Phase
berryphase::Macroscopic_polarization
ESolver_KS_PW<..., DEVICE_GPU>::after_scf
```

同一安装二进制的离线反汇编进一步定位：`recip2real` 返回地址前的调用是 `FFT_Bundle::get_auxg_data<double>()`；该访问器读取 FFT 对象的虚函数表并通过 `jmp *0x48(%rax)` 跳转。结合捕获的 `pc=0`，当前证据支持“该调用路径的空函数目标”这一具体失效点。未保存当时 FFT 对象的全部内容，不能进一步断言其构造/初始化原因或宣称已找到正确补丁。

证据：[完整 GDB 栈](../workspace/reports/berry-v001/gpu-debug-61/gdb-backtrace.txt)、[调度终态](../workspace/reports/berry-v001/gpu-debug-61/scheduler-final.txt)、[工具与符号](../workspace/reports/berry-v001/gpu-debug-61/debug-capability.txt)、[调用位置](../workspace/reports/berry-v001/gpu-debug-61/callsite-disassembly.txt)、[FFT 访问器](../workspace/reports/berry-v001/gpu-debug-61/fft-accessor-disassembly.txt)。诊断脚本为 `scripts/system/debug_berry_gpu_v001.sbatch`，GDB 命令为 `scripts/system/berry-gdb.commands`。

本次定位预算已使用，不再次运行相同 GPU/CPU 任务。下一步仅围绕已安装构建的 FFT 访问器及 Berry host/device 边界制定最小修复方案；任何实际引擎修复另行明确构建范围与验证预算。普通已支持 GPU 计算仍优先 GPU，Berry GPU 保持不可用状态。

## 10. 修复位置的只读源码收敛

12:20审查：公开v3.10.1的 [GPU求解器 after_scf](https://github.com/deepmodeling/abacus-develop/blob/v3.10.1/source/module_esolver/esolver_ks_pw.cpp) 已把GPU波函数复制到CPU `psi`，但Berry仍接收原 `pw_wfc`。因此“没有CPU波函数副本”不是当前源码支持的解释。

[unkdotp_G0](https://github.com/deepmodeling/abacus-develop/blob/v3.10.1/source/module_io/unk_overlap_pw.cpp) 使用主机侧 `recip2real/real2recip`；[PW_Basis_K::setuptransform](https://github.com/deepmodeling/abacus-develop/blob/v3.10.1/source/module_basis/module_pw/pw_basis_k.cpp) 按对象device重新配置FFT；[FFT_CUDA接口](https://github.com/deepmodeling/abacus-develop/blob/v3.10.1/source/module_basis/module_pw/module_fft/fft_cuda.h)提供GPU三维FFT接口，没有覆盖上述CPU辅助缓冲接口。结合job61，工作假设收窄为：**Berry主机overlap路径与GPU basis的FFT后端不匹配**。这仍是源码与二进制证据支持的机制判断，不是已保存崩溃对象的完整证明；安装commit与tag差异继续保留。

建议的实际GPU修复边界是 `unkdotp_G0` 的设备分派/缓冲传递：GPU basis 使用已有GPU `recip_to_real/real_to_recip`，CPU basis保留原路径；必须保持FFT网格、G-vector顺序、npwk、k点与MPI/KPAR映射。不要在原GPU basis上临时改device并重建FFT，以免改变求解器对象生命周期。单独造CPU basis只能是显式兼容诊断，不计作GPU生产修复，也不在当前任务中运行。

本次仅定位，没有改上游源码、构建或新作业。若后续实施GPU补丁，先落实实际安装配方与候选独立构建资源；按2026-10-22最新用户要求，修复后的首次DFT功能验证保留1 V100、1 MPI、1 OMP、8GiB与同job53物理输入，但不设墙钟上限，显式time=0且分区须允许。正常结束与原生收敛仍为必要条件，崩溃/未收敛保留失败，不自动重试。成功还须复用job58做原生单位/量子/相位一致性对照；不再计算CPU Berry。该一次功能验证仍不能替代极化路径或生产精度资格。上方历史job61五分钟预算仅保留为已发生事实。

