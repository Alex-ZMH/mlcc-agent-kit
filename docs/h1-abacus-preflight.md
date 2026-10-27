# H1 ABACUS/Ni 工程预检

执行后更新（2026-10-21）：以下是数值执行前的只读预检快照。现已由Slurm jobs32/33/34完成Ni PW工程小闭环；最新事实见 [执行台账](h1-execution-ledger.md) 与 [能力矩阵](../workspace/reports/h1/capability-matrix-v001.json)。未测试能力保持未测试，未做生产切换。
日期：2026-10-20。本文是 P4/H1 的只读预检，不是 ABACUS 科学任务验收，
也不把 Ni 工程 fixture 当成已确认的生产材料结果。

## 范围与本地基线

本次只核对 Ni 工程迁移准备。`workspace/configs/study.json` 已记录用户确认的
生产材料为 CaZrO3 正交 `Pnma`、先做无掺杂母体；研究温度仍待用户提供，压力和
源结构也尚未定义/核验。因此本次没有创建 CaZrO3 生产任务，也没有更新
`plans/stages.json`。本地配置和旧记录为：

- 站点合同：[workspace/configs/site.v100.json](../workspace/configs/site.v100.json)：
  SSH alias `v100`，远端根目录 `/home/v100/projects/mlcc`，调度器为 Slurm
  23.11.4，ABACUS 路径记录为
  `/home/v100/miniforge3/envs/abacus_env/bin/abacus`，MPI 记录为同环境的
  `mpiexec`。
- 旧环境调查：[docs/v100-environment.md](v100-environment.md) 只记录过包版本和
  文件名，没有把 ABACUS 功能或势质量标为已验证。
- VASP 工程基线：[workspace/configs/h0-vasp-method-v002.json](../workspace/configs/h0-vasp-method-v002.json)：
  Ni PAW PBE 52、10 个价电子、PBE、`ISPIN=2`、初始磁矩 `0.6 μB`、
  `9x9x9` Gamma-centered k 点，固定胞离子弛豫和同几何 SCF 为工程参考。
- `study.json` 的选择记录：`CaZrO3`、`orthorhombic_Pnma`、
  `undoped_parent_reference` 已确认；`temperature_K` 为空，状态为等待用户指定温度，
  `pressure_GPa` 和源结构也为空。
- 几何基线：`ni-fcc-engineering/v001`，4 原子、常规晶格参数 3.52 Å，工程位移
  0.03 Å；对应 VASP 任务是 fixture，生产标记为 false。VASP 任务和输出保存在
  `workspace/tasks/h0-ni-single-v004/`、`workspace/tasks/h0-ni-relax-v004/`。

上述 VASP 数据只定义同几何对照输入。ABACUS 不能因为文件名相同而继承 VASP
标签或总能量；两套原始标签和结果必须继续分开。

## 远端只读证据

以下命令均通过 `ssh v100` 执行，仅读取文件、ELF 依赖和版本信息；没有运行
ABACUS 计算、没有进入 Slurm 提交、没有改写远端文件。此次没有新的 Slurm job ID。

本次实际使用的只读检查包括：

```text
file <abacus> <mpiexec.hydra>
readelf -d <abacus>
ldd <abacus>
ldd <mpiexec.hydra> | grep "not found"
grep name/version/build <abacus conda-meta> <mpich conda-meta> ...
find <pseudopotentials> -maxdepth 2 -type f -iname "*Ni*"
find <orbitals-efficiency> -maxdepth 2 -type f -iname "*Ni*"
sed -n '1,100p' <Ni.upf>
sed -n '1,30p' <Ni.orb>
```

尖括号只表示本节前后列出的实际路径；没有扫描其它用户目录，也没有计算哈希。

### 可执行文件和环境

```text
ls -ld /home/v100/miniforge3/envs/abacus_env/bin/abacus \
  /home/v100/miniforge3/envs/abacus_env/bin/mpiexec \
  /home/v100/abacus-work/PPORBs/pseudopotentials \
  /home/v100/abacus-work/PPORBs/orbitals-efficiency
```

实测：`abacus` 为 140,466,736 字节的 x86-64 ELF 可执行文件，
`mpiexec` 是指向 `mpiexec.hydra` 的符号链接；两者路径存在且可执行。

```text
/home/v100/miniforge3/envs/abacus_env/bin/abacus --version
ABACUS version v3.10.1

/home/v100/miniforge3/envs/abacus_env/bin/mpiexec.hydra -version
Version: 4.3.2
Process Manager: pmi
Launchers available: ssh rsh fork slurm ll lsf sge manual persist
Resource management kernels available: user slurm ll lsf sge pbs cobalt
```

`conda-meta` 的本机记录进一步显示：

| 包 | 实际版本/构建 | 证据含义 |
|---|---|---|
| `abacus` | 3.10.1 / `cuda_mpi_mpich_hb252b04_303` | CUDA、MPI 构建标签已实证 |
| `cuda-version` | 12.9 | ABACUS 环境的 CUDA 版本 |
| `mpich` | 4.3.2 / `h23078de_105` | 与 `mpiexec.hydra` 一致 |
| `elpa` | 2025.06.001 | 包依赖中的 ELPA |
| `fftw` | 3.3.10，`mpi_mpich` 构建 | 包依赖中的 FFTW |
| `libxc-c` | 7.1.2，`cpu` 构建 | 包依赖中的 LibXC |
| `scalapack` | 2.2.0 | 包依赖中的 ScaLAPACK |

对 `abacus` 和 `mpiexec.hydra` 的 `ldd` 检查没有输出 `not found`。ABACUS 的
ELF RPATH 是 `$ORIGIN/../lib`，实际解析到了该 conda 环境中的 CUDA runtime、
CUDA BLAS/FFT/Solver、MPICH、ELPA、FFTW、LibXC 和 ScaLAPACK 库。这证明动态
链接关系目前可解析，不证明 GPU、MPI 或任何 ABACUS 输入功能已经通过数值验收。

ABACUS 环境中没有 `/home/v100/miniforge3/envs/abacus_env/bin/python`；远端 Python
后处理仍是单独问题。直接把该环境的 `bin` 加到 PATH 时可以找到 `abacus` 和
`mpiexec`，但没有 `python` 命令。

### VASP 环境不能直接复用

现有 `/home/v100/projects/mlcc/configs/vasp-nvhpc-env-v002.sh` 设置 NVHPC/HPC-X
MPI，并把 NVHPC CUDA 12.3 库放入 `LD_LIBRARY_PATH`。ABACUS conda 包则是 CUDA
12.9、MPICH 4.3.2 构建，并带自己的 `$ORIGIN/../lib` RPATH。下一任务必须使用
ABACUS 专用环境和 `mpiexec`，不能 source VASP NVHPC 环境后再调用 ABACUS，不能
把两套 MPI 或 CUDA 库混在同一个 batch script 中。

## Ni UPF/ORB 候选（只记录，不自动选择）

聚焦目录中实际找到一个 Ni UPF 和一个 Ni ORB。发现数量不等于科学选择；本节
没有把候选写入生产方法集，也没有复制或修改文件。

### UPF

文件：`/home/v100/abacus-work/PPORBs/pseudopotentials/Ni_ONCV_PBE-1.2.upf`

头部实测：

```xml
<UPF version="2.0.1">
...
scalar-relativistic version 2.1.1, 03/26/2014 by D. R. Hamann
...
<PP_HEADER ... element="Ni" pseudo_type="NC" relativistic="scalar"
  is_ultrasoft="F" is_paw="F" has_so="F" functional="PBE"
  z_valence="18.00" l_max="2" number_of_proj="6"/>
```

可实证信息：Ni、PBE、ONCV norm-conserving、标量相对论、18 个价电子、无
spin-orbit 项、6 个投影子、UPF 2.0.1；可读文本还标出了 ONCVPSP 2.1.1 和
Schlipf–Gygi 库来源。它与 VASP PAW PBE 52 的 10 个价电子并不相同，不能比较
裸总能量，也不能直接宣称两套方法已经对齐。

### ORB

文件：`/home/v100/abacus-work/PPORBs/orbitals-efficiency/Ni_gga_8au_100Ry_4s2p2d1f.orb`

头部实测：

```text
Element                     Ni
Energy Cutoff(Ry)           100
Radius Cutoff(a.u.)         8
Lmax                        3
Number of Sorbital-->       4
Number of Porbital-->       2
Number of Dorbital-->       2
Number of Forbital-->       1
Mesh                        801
dr                          0.01
```

文件名含 `gga`，头部给出 100 Ry、8 a.u. 和 `4s2p2d1f`，但头部没有明确的 PBE
版本、生成器版本、相对论/SOC 状态或与上述 UPF 的配对声明。因此它只能作为
候选记录，不能由元素名或目录顺序自动选入下一任务。下一步需要显式确认
UPF/ORB 配对、磁性/SOC 适用性和基组/截断收敛。

## 已实证与未测

已实证：

1. 远端实际存在并可执行 ABACUS v3.10.1 CUDA/MPICH 构建及 MPICH 4.3.2 Hydra
   launcher。
2. ABACUS 运行库由其 conda 环境解析，当前 `ldd` 没有缺库。
3. Ni UPF/ORB 候选的实际路径和头部字段如上，未混入 VASP 原始标签。
4. ABACUS 工具链应与 VASP NVHPC/CUDA 环境分离。

未测：

1. 没有在 Slurm 中运行 ABACUS，也没有测 `mpiexec` 在 batch allocation 内的
   单 rank/GPU 启动、CUDA 可见性或 MPICH 网络 provider。
2. 没有验证 STRU、INPUT、KPT、赝势/轨道配对，也没有测 SCF、力、应力、离子
   弛豫、磁性、SOC、Berry/Born/介电等功能。
3. 没有做 cutoff、k 点、基组、磁态或 VASP/ABACUS 同几何相对量收敛比较。
4. 没有把候选 UPF/ORB 标记为合格生产势，也没有完成 H1/G4。

## 下一最小 Slurm 任务

下一步建议只建 Ni 工程 fixture 的同几何 ABACUS 单点任务：一台 GPU、一个
MPICH rank、一个 CPU 核，使用 ABACUS 专用环境和显式记录的候选文件；命令在
`sbatch` 脚本内通过该环境的 `mpiexec -n 1 abacus` 启动。资源和命令应写入新的
task JSON，经现有 `prepare → transfer → sbatch → scontrol → collect`，不能从
SSH 直接启动 ABACUS。第一项任务只验证输入装载、启动、SCF 收敛和能量/力输出，
不宣称方法或势已合格。

单点真实通过后，再按依赖建立两个小任务：

1. 同一 ABACUS 方法集的独立固定胞离子弛豫；
2. 读取 ABACUS 弛豫产物的后续 SCF，并与同一几何的 VASP 工程结果做相对能、
   力、应力和磁态对照。

这三个任务仍属于 Ni 工程迁移准备。只有方法、势、数值收敛和物理对照达到
阶段门后，才可讨论把生产 DFT/标注切换到 ABACUS；期间不回退 VASP，也不把
VASP 标签混进 ABACUS 数据。
