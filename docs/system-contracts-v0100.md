# MLCC 0.10.0 开发合同

状态：0.10.0 已完成本轮软件范围验收、启用并冻结；当前实际启用版本为 0.10.0。0.9.0 原目录保留，未重测。

历史基线（2026-10-22 13:10，保留）：带电SCF输入与原生电子数绑定已实现为候选软件切片，job71/72检查证据及未验收边界见[带电合同](charged-scf-next-slice.md)。当时实际带电原生实验未执行，VBM/势对齐/FNV/介电仍未完成；不以软件检查宣布生产资格。站点cpu/gpu现为MaxTime=UNLIMITED，DFT显式time=0。

最终更新：job75/76/77/80 的带电原生 GPU SCF 已完成，job86 完成安装副本验收，MatterAI 原版宿主与七工具 MCP 直连均通过。0.10.0 已启用并冻结；本轮验收仅覆盖原始带电固定几何 SCF、电子数/收敛和局部能量/力加密。

## 本轮范围

1. ABACUS 3.10.1 PW 的显式 SCF 电荷输出与 NSCF Berry 输入、任务谱系和原生极化解析。
2. 将原生解析结果接入 CLI 和工程续接；保留极化量子与未解缠分支状态，不将单点极化升级为自发极化或介电资格。
3. LAMMPS 现有 MD 接口的一次真实 Ni NVE 100 步工程验证，由另一执行窗口负责。
4. 后续按用户优先级补中性缺陷任务对，以及材料势静态张量/同几何对照；不加入磁性、热电或新 MD 工程演示。

数值输入生成、科学后处理及测试均在 v100 的 Slurm 作业内运行。本地负责编辑、传输控制、安装/连接检查与查看证据。私有站点配置已将建模/解析位置从历史 local 改为 v100_via_slurm，并指向已经验收的远端开发 Python。

## Berry 最小证据链

使用已确认的 CaZrO3 Pnma 无掺杂源模型作为系统接口案例。保留 2×2×2 k 点、scf_thr=1e-4、100 Ry 和原 Ca/Zr/O 赝势/非 SOC 处理。新方法版本显式选 symmetry=-1、fixed 占据；不修改旧 job40。

先生成 `out_chg=1` 的新 SCF 参考；由真实原生收敛、电子数/占据和采样带隙检查约束后继任务。随后只做一个 `gdir=1` 的 NSCF：`init_chg=file`、`berry_phase=1`、`pw_diag_thr=1e-6`。电荷文件必须来自该 SCF，结构、晶胞、原子顺序、赝势与方法必须绑定。同一次验收不展开方向、路径或温度矩阵。

该精度和单方向仅用于系统接线，不能作为极化收敛或绝缘性的全布里渊区证明。若原生计算不满足前置条件，保留原始失败，不自动改精度、重试或换引擎。

精确版本复核进一步收紧当前接口为 `nspin=1`。3.10.1 Berry 源码对两自旋通道复用 `ceil(nelec/2)` 占据带数，不能据文档中的 nspin=2 支持说明就放行不等自旋占据的磁性绝缘体。当前拒绝 `nspin=2`；普通 SCF/relax 的自旋能力不受影响。原生 modulo 还受赝势价电子数奇偶性影响，必须保留并核对，不能假定所有输入都是相同极化量子。依据：[v3.10.1 Berry 源码](https://github.com/deepmodeling/abacus-develop/blob/v3.10.1/source/module_io/berryphase.cpp)。

解析保留 ionic/electronic phase、各原生单位的 P 与 modulo quantum、晶格方向、Cartesian reprojection、原生输入和日志。单点结果保持 `branch_status=not_unwrapped`、数值/科学/生产资格 false。SCF 电子收敛和 NSCF 正常结束是不同证据，不把 NSCF 标记成自洽收敛。

Born、体相有限场、DFPT、电子/离子/静态介电和路径分支解缠不属于本轮交付。BaTiO3 相/结构未选择，不自动代选。烧制温区仅保留为 Study 上下文，静态任务不代表高温响应。

## LAMMPS 工程正例

沿用 job41 的 Ni 工程模型与显式 Ni_u3.eam 势，新任务选 NVE、初速度 300 K、seed 20261022、步长 0.001 ps、100 步、每 10 步输出。原生 log、最终 dump、完整轨迹和 task/method/model 绑定必须同时通过。

该 0.1 ps 任务仅验证 MD 软件链。报告初末能量变化、有限值和原子映射，不以一个短轨迹证明采样收敛、势适用域或热物性。

## 验收与版本

仅检查新模块与受影响集成，复用已有原生任务和冻结版本证据，不重复整套 0.9 验收；全部数值验收保留 Slurm ID、终态、退出码和日志。0.10.0 软件发布已完成实际解析、安装和宿主接线证据并启用冻结，但不得据此宣称完整生产计算能力完成；计算功能的验收以声明生产协议的真实实验任务及科学标准为准。不因输入文件生成或单任务完成而宣布 P5/P9/P10 全阶段完成。

历史状态（12:22更新，保留）：CPU job58 COMPLETED/0:0（7分44秒/20分钟预算）；job59/60/62 的目录、周期等价坐标、打印舍入问题均记录原错并修复。job65 COMPLETED/0:0（6秒），复用job50/58通过30项受影响测试及11项入口检查，原生极化仍为 `evaluated_polarization_unqualified`。没有新增CPU Berry计算。该时点源码专项通过不等于安装验收，0.10.0 尚未启用；随后完成的安装和启用证据见下文。证据：[job65报告](../workspace/reports/berry-v001/focused-65/entrypoints/acceptance.json)。

中性缺陷任务对新增 `create-neutral-defect-pair` CLI，job64 COMPLETED/0:0（1秒）通过4项输入检查：真实创建器生成 host/defect INPUT/STRU，并拒绝非SCF、带电与化学势能量定义不匹配。测试中的缺陷位点和μ只验证输入合同，未产生材料能量或选择生产缺陷。证据：[job64测试](../workspace/reports/neutral-defect-pair-v001/job-64/tests.txt)、[接口说明](neutral-defect-chain-implementation.md)。

材料势静态张量/相对能/力/应力比较由另一窗口实现，job63通过70项软件检查。真实材料静态资格用途经job66的13项检查通过；主窗口job67通过7项续接门检查。复用既有create-lammps与compare-potential，不要求把真实模型标为fixture，不自动放行MD；仍缺完整张量原生任务、ABACUS应力标定及合格参照，不授予材料势资格。证据见 [用途检查](../workspace/reports/potential-qualification-v002/execution-ledger.md) 与 [续接检查](../workspace/reports/potential-workflow-v001/execution-ledger.md)。

## 本轮带电 SCF 真实任务与最终发布状态

### v100 原生任务

CaZrO₃ Pnma O 空位、(q=+2) 的固定胞 `nspin=1`、fixed occupation 任务经 v100 GPU Slurm 完成：

| 任务 | Slurm | 电子步数 | 最终密度残差 | 原生电子数核对 |
|---|---:|---:|---:|---|
| `ecut=100 Ry, k=2×2×2` | 75 | 16 | `7.2575875e-9` | `N=154 -> 152` |
| `ecut=120 Ry, k=2×2×2` | 76 | 16 | `6.4908591e-9` | `N=154 -> 152` |
| `ecut=120 Ry, k=3×3×3` | 77 | 16 | `3.5370092e-9` | `N=154 -> 152` |

三项原生任务均为 `COMPLETED/0:0`，请求 `time=0`，使用 GPU；原生日志中的电子总数、目标电子数和固定占据检查均通过。这个结果证明带电 SCF 的真实输入、GPU 执行、电子收敛和原生电子数绑定链路可用，不证明缺陷形成能、费米能级参考、势对齐、介电屏蔽或 FNV/eFNV 修正资格。

job78 是解析验收作业，状态为 `FAILED/1:0`，不是 DFT 作业失败。其余原生任务检查通过，但原 protocol v001 的 k 点细化不满足声明阈值：

| 对照 | ΔE (eV/atom) | 阈值 | 最大力变化 (eV/Å) | 阈值 | 结果 |
|---|---:|---:|---:|---:|---|
| `100 Ry/2³ -> 120 Ry/2³` | `0.0001877931076` | `0.001` | `0.002627238189` | `0.02` | 通过 |
| `120 Ry/2³ -> 120 Ry/3³` | `0.003716245583` | `0.001` | `0.02627837463` | `0.02` | 未通过 |
| `120 Ry/3³ -> 120 Ry/4³` | `0.00016947937834438083` | `0.001` | `0.003098109684903484` | `0.02` | 通过 |

解析器已修正原生日志中额外 `=` 和四位权重打印造成的原生打印区间解析；使用真实 `3×3×3` 权重的负例也会被拒绝。相关完整记录为 [job78 acceptance](../workspace/reports/charged-scf-native-v001/native-check-78/acceptance.json)，失败原因保留在 [job78 stderr](../workspace/reports/charged-scf-native-v001/verify-78.err)。

根审查后的 protocol v002 单独增加 `120 Ry/4×4×4` 细化点，不改写 v001 的失败证据。准备作业 job79 为 `COMPLETED/0:0`。DFT job80 为 `COMPLETED/0:0`，Slurm 运行 7 分 16 秒，`TimeLimit=UNLIMITED`、GPU 分区，15 步达到原生电子收敛，最终 `drho=4.48699871134e-9`，目标电子数为 152。job80 与 `120 Ry/3×3×3` 的能量差 `0.00016947937834438083 eV/atom`、最大力差 `0.003098109684903484 eV/Å` 均在原 protocol 阈值内。

job86 是安装副本验收作业，`COMPLETED/0:0`，运行 8 秒。四个真实带电任务、原生电子数、公开 CLI 结果、真实权重破坏负例和五项受影响检查全部通过；最终报告为 [installed-charged-86](../workspace/reports/system-v0100/installed-charged-86/acceptance.json)。这项证据证明 0.10.0 安装入口复用同一真实原生结果并正确拒绝破坏的权重，不扩大科学资格范围。

因此，本轮带电验收 scope 固定为：原始带电固定几何 SCF、原生电子数和电子收敛、以及局部能量/力加密。缺陷形成能、化学势/费米能级参考、VBM 对齐、介电屏蔽、FNV/eFNV 修正、尺寸收敛和全材料生产资格均不在已通过范围内。

### MatterAI 安装、启用与 MCP

原版 MatterAI 安装器已把当前源 Bundle `mlcc-agent@0.10.0` 安装到：

```text
workspace/.zeus/bundles/mlcc-agent/0.10.0
```

历史安装步骤中该版本尚未 `enable`，`.zeus/bundles.json` 的主启用版本仍为 `mlcc-agent@0.9.0`；该中间状态保留。随后 0.10.0 已完成启用并冻结，0.9.0 原目录保留且未重测。相同的 0.10.0 安装副本已传到 v100：

```text
/home/v100/projects/mlcc/development/0.10.0/installed/0.10.0
```

已安装 launcher 的直接 MCP stdio 证据为 [mcp-installed-v0100](../workspace/reports/system-v0100/mcp-installed-v0100.json)：initialize 成功，server version 为 `0.10.0`，`tools/list` 返回现有 7 个 MLCC 工具，`mlcc_list_tasks` 调用 `isError=false`。原版 MatterAI 宿主报告 [matterai-headless-session-v0100](../workspace/reports/system-v0100/matterai-headless-session-v0100.json) 为 `passed`，Bundle 为 `0.10.0`，child exit code 为 0，并通过真实的一次 `mlcc_list_tasks` 调用。发布 workspace 为 `workspace/releases/mlcc-agent-0.10.0`，共 87 个文件；0.9.0 原目录保留，不重测。上述证据证明 0.10.0 安装、registry、宿主接线和 MCP 工具协议达到本轮软件发布范围，不扩大科学计算资格。

### 最终版本记录与边界

当前最终记录如下：

| 记录字段 | 当前值 |
|---|---|
| `enabled_version` | `0.10.0`，已启用并冻结 |
| `release_accepted` | `true`，限于本轮软件与原始带电固定几何 SCF/局部 E/F 加密 scope |
| `scientific_qualification` | `false` |
| `production_qualification` | `false` |
| `design_assessment` | `not_assessed` |
| `historical_failure` | job78 `FAILED/1:0` 保留；`120 Ry/2³ -> 120 Ry/3³` 的 ΔE/ΔF 超出阈值，未被 job80 覆盖或改写 |
| `remaining` | 形成能、化学势/费米能级与 VBM 参考、势对齐、介电/FNV/eFNV、尺寸收敛、材料势资格和全材料生产证据 |

## GPU 失败与显式 CPU 工程路线

job50 SCF 已完成并保留真实电荷；job53 GPU NSCF 完成对角化后在 Berry 阶段段错误，FAILED/139:0。job61在单V100、5分钟预算内运行29秒，取得真实GDB栈：GPU求解器→Berry→`unkdotp_G0`→`recip2real`→空地址；实际二进制反汇编将访问点收窄到 `FFT_Bundle::get_auxg_data<double>`。诊断启动器 FAILED/1:0，inferior 是 SIGSEGV。尚无完整对象/core或修复构建，不能声称最终根因或GPU成功。入口继续拒绝GPU Berry NSCF，普通GPU SCF保留。

显式 CPU 配置 `cazro3-berry-cpu-capability-v001.json` 使用同一 ABACUS 3.10.1 二进制和物理方法身份；仅执行设备改为 CPU。任务使用原 job50 电荷，在 v100 经 Slurm 运行。job55 超时，人工修订预算后的独立 job58 完成。CPU 路径仅用于小规模预算内兼容验证，不作为生产默认或继续重复计算的理由。普通 GPU 计算保持优先；GPU Berry 的事实与推断分别记在 [故障记录](berry-gpu-issue-53.md)。完整过程见 `workspace/reports/berry-v001/execution-ledger.md`。
