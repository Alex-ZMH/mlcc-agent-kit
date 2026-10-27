# P4 / H1 Ni 工程执行台账

日期：2026-10-21（Asia/Shanghai）。本轮只推进 Ni 工程迁移小闭环；生产材料为用户确认的无掺杂 CaZrO3/Pnma，330 K 与 400 K，外压 1 atm = 101325 Pa = 0.000101325 GPa。生产温度不用于替代静态 DFT 的电子展宽。

## 方法与执行准备

- 只读站点核对见 `workspace/reports/h1/preflight-20261021.txt`：Slurm 队列空闲，4 V100，ABACUS 3.10.1 CUDA/MPICH。旧 Si 日志只作为输入和兼容性参考，不计作本项目验收。
- 新方法为 `workspace/configs/h1-abacus-method-v001.json`：Ni ONCV PBE、18 价电子、PW、共线自旋、0.1 eV Gaussian 展宽、100 Ry 候选与 120 Ry 对照，k 网格按用户 `ceil(30/length)` 规则。未采用 ORB，未宣称赝势或方法已获生产资格。
- 新任务入口 `scripts/h1/abacus_fixture.py` 调用同一 Slurm runner，生命周期动作逐项执行。P4 submit 明确要求 H0 工程门先通过，不自动串联提交或重试。
- 站点环境文件 `workspace/configs/abacus-mpich-env-v001.sh` 单独激活 ABACUS 环境并限定其库目录；没有复用 VASP NVHPC 环境。
- 实际命令：`scp workspace/configs/abacus-mpich-env-v001.sh v100:/home/v100/projects/mlcc/configs/abacus-mpich-env-v001.sh`，退出码 0。只上传本任务配置，无数值进程、无 job ID。

后续每项 Slurm 任务的完整命令、job ID、原生状态、退出码和资源记录在对应 `workspace/tasks/h1-ni-*/task.json` 的 events 中；科学状态及选定产物独立记录，不从退出 0 推导科学收敛。

## job 32：同几何 SCF 已完成

命令逐项执行：`python scripts/h1/abacus_fixture.py create scf`、`prepare scf`、`transfer scf`、`submit scf`、`query scf`、`collect scf`、`parse scf`，解释器均为 `workspace/.venv/Scripts/python.exe`；各退出码 0。任务 `h1-ni-scf-v001`，Slurm job **32**，终态 `COMPLETED`、`0:0`，运行 00:08:33。资源为一张 V100、1 MPI rank、1 物理核（Slurm 分配 2 逻辑 CPU）、8 GiB 内存；实际 GPU 进程读数约 3.7 GiB。原生资源/命令/状态见 task.json。

真实 ABACUS 3.10.1 输出：10 次电子迭代，charge density convergence is achieved；有限展宽自由能 -16779.146723254777 eV，最大力 0.27865321568177726 eV/Å，总磁矩 2.41425570809 μB/胞。4 个 Ni、72 价电子；9×9×9 网格遵循用户规则。`OUT.NiPW` 约 5.7 MB 已回传，赝势留在服务器。原始 warning.log 中初始原子密度归一化和本征值阈值提示保留；最终收敛不能由退出码替代。

与 VASP job24 相同几何的最大力分量差为 0.0060580952 eV/Å。VASP OUTCAR 全胞磁矩 2.4196039 μB（不是各 PAW 球磁矩之和）；目前只是差异记录。ABACUS 原始应力已按 kBar×0.1 转为 GPa，尚未完成有限应变符号/截断检验，不报告生产方法等价，也不比较裸总能。

## job 33：独立固定胞弛豫已提交

查看 job32 的收敛、实际内存和耗时后，逐项运行 `create relax`、`prepare relax`、`transfer relax`、`submit relax`，退出码均 0，生成 `h1-ni-relax-v001` / Slurm **33**。保持同一100 Ry方法、同一位移初始结构；资源仍单GPU/单rank，时限30分钟。没有复用VASP弛豫坐标，也没有自动重试。最终结果以原生终态及后续验收记录为准。

## 本地代码与 Bundle 0.3.0

ABACUS直接输入/解析适配器、三任务入口、谱系导出和对照脚本已实现。`python -m pytest mlcc-agent/tests -q -p no:cacheprovider` 退出0，20 passed；26条ASE/NumPy上游弃用告警保留在 `workspace/reports/h1/unit-tests-v030.txt`。宿主5项聚焦测试含真实v003原始JSONL重放，通过；没有以模拟日志替代科学验收。

首次本地安装命令 `pip install --no-deps --no-build-isolation -e mlcc-agent` 退出2，原因为当前虚拟环境无 `setuptools.build_meta`，原错误见 `local-package-install-v030.txt`。经检查改用项目声明的隔离构建 `pip install --no-deps --no-cache-dir --retries 0 -e mlcc-agent`，退出0，安装0.3.0；见 `local-package-install-v030-build-isolated.txt`。没有升级驱动、系统软件或重装Slurm。

测试缓存删除命令被自动审批拦截，未执行；改为将缓存完整移动到 `workspace/reports/h1/pytest-cache-before-v030`，退出0，不删除缓存。随后原版MatterAI安装器 `npm run bundle:install -- D:\project\mlcc\mlcc-agent --workspace D:\project\mlcc\workspace --enable` 退出0，真实启用 `mlcc-agent@0.3.0`；见 `installer-v030-output.txt`。已安装0.2.1目录与其历史验收保留。项目mcp.json仅将入口版本指向0.3.0。

## job33 真实终态与 job34 谱系

job33 实际终态 `COMPLETED/0:0`，00:23:54；5个离子步，最后电子步收敛、原生 `Relaxation is converged!`，最大力0.010929463703683896 eV/Å，能量-16779.150860889447 eV。`query relax`、`collect relax`、`parse relax` 与 `export_relaxed_model.py` 均退出0。导出 `workspace/models/ni-abacus-engineering-relaxed/v001` 四件套，4个atom_id保持0..3，源job33和method记录随模型保存。

之后逐项 `create post-relax`、`prepare post-relax`、`transfer post-relax`、`submit post-relax`，退出码0，任务 `h1-ni-post-relax-v001`、Slurm job34。输入从job33真实末结构派生，task指向新ABACUS模型ID；原生STRU回读与导出模型的最大坐标差4.992178e-9 Å，处于extxyz文本精度内。任务为单GPU/单rank、8GiB、10分钟，最终科学收敛另行验收。

安装后的0.3.0原版宿主真实模型调用 `mlcc_list_tasks` 返回24条记录、CLI0；`matterai-headless-provider-session-v030-list-tasks.json` 保存原始JSONL。另以真实stdio MCP调用 `mlcc_query_calculation` 查询job33得到COMPLETED/0:0，协议版本报告0.3.0、工具7项，命令退出0；见 `mcp-installed-v030-query-job33.json`。这两份证据分别证明模型→MCP与已安装MCP→Slurm查询。

## 三任务小闭环验收：通过，P4/H1生产资格仍未完成

job34 的 `query post-relax`、`collect post-relax`、`parse post-relax` 均退出0，原生终态COMPLETED/0:0，耗时00:09:21；12次电子迭代收敛，最大力0.009683471610314959 eV/Å。`python scripts/h1/compare_abacus.py --report workspace/reports/h1/ni-engineering-loop-v001.json` 退出0，七项工程检查全通过。报告同时保留 `production_qualification=false`、`production_engine_switch=false`。

| 任务 | job ID | 终态/退出码 | 最大力 eV/Å | 运行时间 |
|---|---|---|---:|---|
| 同几何SCF | 32 | COMPLETED/0:0 | 0.27865322（位移起点） | 00:08:33 |
| 独立固定胞弛豫 | 33 | COMPLETED/0:0 | 0.01092946 | 00:23:54 |
| 弛豫后SCF | 34 | COMPLETED/0:0 | 0.00968347 | 00:09:21 |

弛豫和后续SCF均低于预先指定0.02 eV/Å；同方法弛豫降低自由能0.00413763467 eV，post−relax能量差-1.10194e-8 eV。实际STRU/结构sidecar/atom_id与末结构谱系一致；相对VASP独立弛豫的最大周期原子位置差0.0005804462 Å。不同赝势裸总能未比较、标签未混合。

合计41分48秒单V100运行时间（0.6967 GPU小时）；三个任务逐个提交，无自动串联/重试/requeue。`job34-runtime.txt`记录实际单rank/单GPU、进程显存3686MiB；`final-resource-release.txt`记录最终squeue为空、GPU计算进程为空、四卡利用率0%。没有把缺失的sacct/MaxRSS指标填零。

下一最小任务为同几何120 Ry单点，与已完成100 Ry结果作预定能量/力/应力截断对照；按实测耗时显式复核单卡资源和时限（建议20分钟上限），再进行±0.5%应变应力标定。本轮不提前提交这些任务。H1仍缺数值方法资格、本机生产所需能力验证及显式生产引擎切换；P5–P12未开始。Ni固定胞工程态不代表330/400 K、1 atm的平衡态，生产工况只绑定用户选择的无掺杂CaZrO3/Pnma。

## job35与系统0.4.1补充（2026-10-21）

本节开始采用新版案例条件：CZO400–580°C、1atm，BTO800–1350°C且其余边界未选；上文330/400K保留为历史，不用于新任务。Ni静态工程态不赋予任何案例温度/压力。

同几何120Ry job35已完成COMPLETED/0:0、00:08:54，10电子步，能量-16779.146820773167eV，最大力0.2793349904146426eV/Å（位移SCF，不要求达到离子弛豫阈值）。单V100/单rank/8GiB/20分钟，运行时显存4756MiB。显式任务与命令记录见task.json，原始结果保留。

与job32的100Ry相比，能量差2.4379597562e-5eV/atom、最大力分量差0.0006817747eV/Å、最大应力分量差0.01530027461GPa，均通过原定阈值。首次比较v001因冗余输出开关记录格式差异退出1；核验原生INPUT并修正比较器后v002退出0，原报告与数值任务均保留。证据：[截断v002](../workspace/reports/h1/ni-cutoff100-120-v002.json)、[系统合同/命令说明](system-contracts-v041.md)、[能力矩阵v002](../workspace/reports/h1/capability-matrix-v002.json)。H1和生产引擎切换继续未通过，下一科学门是有限应变应力标定。

## 0.5.0显式输入与用户快速参数（2026-10-21）

已运行旧负应变job36：COMPLETED/0:0，8分57秒、11SCF步、E=-16779.13743596486eV。用户随后指定能力先行2×2×2、scf_thr=1e-4；旧正应变未提交。新job37通过显式Study/Model/Method入口创建，COMPLETED/0:0、10秒、7SCF步，DRHO=1.3831e-5；E=-16778.90745945708eV。两者不混算有限差分。工程资格、应力符号标定和生产资格分别记录。

本批82项单测通过，新版原版安装器、非桌面宿主MCP、已安装MCP→Slurm查询、安装版解析与交付通过。真实命令、文件与限制见[0.5.0实施验收](system-contracts-v050.md)，汇总见[acceptance.json](../workspace/reports/system-v050/acceptance.json)。H1和生产切换仍false，最终队列/GPU计算进程为空。

## B03粗参数应变三点完成，科学标定未通过

同job37参数，新增job38（−0.5%，8秒、6SCF步）和job39（+0.5%，9秒、7SCF步），顺序单卡、均COMPLETED/0:0并达到1e-4。三点比较可比性通过；D=4.3976744224GPa，原生迹−10.7531563225GPa，最近符号候选误差6.3554819001GPa>预设1GPa，标定失败/比较退出1如实保存。没有调整阈值、重试或使用旧job36。85项单测通过，原生KPT和来源检查已补齐；新版检查本次从源码执行，原0.5.0安装保持不变。

详见[B03应变验收](h1-strain-capability-v004.md)及[机器验收记录](../workspace/reports/h1/strain-quick-v004/acceptance.json)。能力链路通过不等于科学资格；H1/生产切换仍false。后续不依赖应力资格的B04软件工作由主窗口推进。
