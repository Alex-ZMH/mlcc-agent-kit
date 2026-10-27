# MLCC 系统进度草稿（0.9.0，2026-10-22）

此为 job42 后的历史草稿，已由 [正式进度](project-progress-20261022.md) 和 job43/44 最终验收取代。以下“当前/待完成”仅描述编写草稿时的状态，不是现行状态。

本文件是根执行窗口替换正式进度记录前的 0.9.0 草稿。它只汇总已经存在的源代码、远端验收报告和历史原生任务证据，不改变 `PLAN.md`、`plans/`、现有进度文件或版本文件。

当前状态必须分开理解：源代码和测试材料已经进入 **0.9.0 candidate**，系统实际启用版本仍为 **0.8.0**。0.9.0 尚未安装验收，远端 job 42 的全套测试没有通过，因此不能把 0.9.0 candidate 写成已发布版本。

## 1 当前版本和执行位置

| 项目 | 当前状态 | 证据或边界 |
| --- | --- | --- |
| 启用版本 | `0.8.0` | 0.8 安装版仍是当前可用 Bundle；0.7 作为开发基线保留 |
| 开发源 | `0.9.0_candidate` | `workspace/reports/system-v090/remote-job42.json` 的 `source_release` |
| 0.9 安装验收 | 待完成 | 尚未形成通过的 0.9 安装版 acceptance 记录 |
| 数值任务位置 | v100 / Slurm | 本地仅编辑代码、控制任务和查看证据；不在本地运行 DFT、MD、声子或其他数值验收 |
| 远端测试 job | job 42，失败，`1:0` | 软件测试与历史证据后处理；`new_DFT_or_MD_jobs=[]` |
| 远端数值来源 | 历史任务 20、32–41 | 作为来源证据复核，不是 job 42 新提交的数值任务 |

远端环境安装的第一次网络安装因 15 秒读取超时失败，随后按原始错误将读取超时明确提高到 120 秒并完成安装；报告记录没有自动重试数值作业。该环境准备不等于 0.9 安装版验收完成。

## 2 job 42 远端测试状态

报告 `workspace/reports/system-v090/remote-42/unit-tests.txt` 和 `remote-job42.json` 给出：

| 统计 | job 42 记录 |
| --- | ---: |
| passed | 293 |
| failed | 3 |
| skipped | 0 |
| 终态 | `FAILED` |
| 退出码 | `1:0` |
| 新 DFT/MD 作业 | 0 |

这 293/3 只是当前远端候选源的中间测试结果，不是 0.9 最终统计。3 个失败目前按远端报告分类为测试/fixture 问题，正在修复：

1. 一个测试 fixture 使用 Windows 专用绝对路径；
2. 一个断言使用 Windows 路径分隔符；
3. 一个负向测试依赖精确文本替换，但没有实际修改原生数据。

修复后必须在 v100/Slurm 重新运行同一套验收，并由根执行窗口填写新的通过数、失败数、作业状态和证据路径。在重新验收前，不把 293 项写成“0.9 已通过”。

## 3 当前已形成的软件范围

0.9 源代码已经形成以下系统桥接范围，具体合同见 [`system-contracts-v090.md`](system-contracts-v090.md)：

| 轨道 | 当前源代码能力 | 当前资格状态 |
| --- | --- | --- |
| P7 Phonopy | 显式 `+/-` 位移计划、独立子模型/Study、固定胞 ABACUS SCF 输入、原生力收集门、谐波 q 点入口 | 软件合同可审查；没有完整真实位移力集，未授予声子/热学/生产资格 |
| LAMMPS | 显式势和协议、data/input 导出、真实 log/dump 解析、Slurm 任务记录、run0/MD 工作流语义 | 工程 fixture 入口；势适用性、MD 采样和生产资格未通过 |
| 工作流 | LAMMPS run0 与 MD 工程完成状态单独表示；工程状态不作为科学 `converged` 依赖 | 已加入来源和身份门，待 0.9 安装副本验收 |
| P5 审查 | ABACUS 3.10.1 Berry 输入/输出路线和限制已审查 | 版本/接口路线已确认，MLCC Berry 适配器和数值资格未实现 |

0.8.0 的 223 单元测试、18 个安装扩展检查、13 个公共回归和 17 个 Ca 回归只属于 `workspace/reports/system-v080/acceptance.json`，继续作为历史基线，不能替代本版验收。

## 4 P7 Phonopy 进度

### 已形成

- `phonon-plan` 以显式 `repeat_matrix`、primitive matrix、位移距离、对称性和 Phonopy 版本生成 `mlcc.phonon-displacement-plan.v1`。
- 位移计划固定产生成对的正负位移，保存参考超胞、结构文件、原子 ID、质量、初始磁矩和父模型 lineage。
- `create-phonon` 为每一个明确选择的 manifest 条目建立独立 child model、child Study 和 ABACUS 静态 SCF task；不提交任务，不弛豫，不覆盖父模型掺杂和相信息。
- `phonon-forces` 只读取真实 ABACUS 结果，检查 `INPUT/KPT/STRU`、方法、模型、Study、原子映射、几何、调度状态、电子收敛、力一致性和阈值。
- `phonon-qpoints` 只有在 reference 与全部显式位移力任务通过真实力门后才计算谐波 q 点；结果保留 software-only、未资格化状态，不自动施加 NAC/ASR。

### 真实证据边界

`workspace/reports/system-v090/phonons/source-v002/acceptance.json` 的软件验收通过，但明确记录：

```text
complete_native_phonon_force_set = false
phonon_scientific_qualification = false
temperature_matrix_started = false
```

因此当前 P7 只能报告计划和输入链路已形成，不能报告完整真实声子力集、力常数、频率、热容、热膨胀或热导资格已完成。缺力输入时 q 点命令保持 blocked，不能用数学测试数据或计划文件伪造频率。

## 5 LAMMPS 进度

### job 41 的实际范围

`workspace/tasks/p9-ni-lammps-run0-v001/` 是已有真实 Ni `run0` 工程 fixture，Slurm job **41**，终态 `COMPLETED/0:0`。任务含 `method.json`、`model.data`、`atom-map.json`、`in.lammps`、Ni_u3.eam、真实 `log.lammps` 和 `dump.final`。

该任务证明显式势→LAMMPS 输入→Slurm→原生回传→解析的工程链路。它的状态是 `evaluated_engineering_fixture`，不是生产势、不是 MD 热平衡，也不是 CaZrO₃ 或 BaTiO₃ 计算。job 42 的 `source_numerical_jobs` 包含 41 只是引用历史来源；job 42 没有提交新的 DFT/MD。

### 当前工作流边界

- run0 需要真实存在且文件名正确的 `log.lammps` 和 `dump.final`；不要求轨迹文件。
- MD 需要在上述两个文件之外，真实存在且文件名正确的 `trajectory.lammpstrj`；当前没有真实 MD 正例。
- `evaluated_engineering_fixture` 和 `executed_engineering_fixture` 都不加入通用科学收敛状态，不得作为科学结果依赖。
- 工程 fixture 不证明势的 DFT 基准、时间步/尺寸/采样收敛、热输运、介电、极化、界面或生产范围。

## 6 P5 版本审查和下一步 Berry 路线

`docs/abacus-3101-p5-capability-audit.md` 已完成 ABACUS v3.10.1 的版本和接口审查，结论是：Berry phase 的版本级输入/输出契约可依据官方源码、文档和示例实现；当前 MLCC 没有 Berry 输入写入器、`POLARIZATION CALCULATION` 原生解析器或 branch-tracking 结果合同，真实 Berry 数值资格未通过。

审查形成的下一条路线是：

1. 新增显式 Berry SCF/NSCF 输入适配器，固定 `out_chg`、`init_chg`、`berry_phase`、`gdir`、`symmetry`、`pw_diag_thr` 和方向 KPT；
2. 只解析 ABACUS 3.10.1 的原生 `POLARIZATION CALCULATION` 日志，保留 phase、极化量子、方向、单位和来源；
3. 先检查绝缘性、固定占据、方法/赝势/晶胞一致性，再用 CZO 参考和 BTO 参考/极性路径做小规模输入验证；
4. 在 v100/Slurm 完成参考 SCF→NSCF Berry 原生任务和方向/k/阈值检查；
5. Berry 解析和分支测试通过后，再决定有限差分 Born/极化-应变路线，并与 P7 力常数单向绑定。

这条路线目前只是版本审查后的下一步规划，尚未实现适配器、解析器、任务或数值结果。CZO 的非极性状态不删除其正常介电需求；BTO 的材料相、极性路径和铁电资格也不能由普通 SCF 或化学式自动推断。

## 7 两个验证案例与温度边界

系统继续按通用 MLCC 架构建设，CaZrO₃ 和 BaTiO₃ 是两个独立验证案例，不是把所有温度、相、缺陷、场和工艺组合展开成一个矩阵。

- CaZrO₃：当前验证上下文为已选的 Pnma 无掺杂模型；烧制温区 400–580 °C（673.15–853.15 K）。
- BaTiO₃：当前验证上下文为铁电能力案例；烧制温区 800–1350 °C（1073.15–1623.15 K），具体相和结构仍由 Study 明确选择。
- 上述温区是后续工艺历史/有限温度方法的输入上下文，不是当前 0 K ABACUS SCF、P7 力或 LAMMPS job41 的结果。
- 未有经过资格化的有限温度采样、Berry `P(T)`、`D(E)`、介电 `C(T,V)` 或铁电翻转结果；不从 0 K 或工程 fixture 外推这些量。

## 8 科学资格和设计判断

当前仍保持以下状态：

- `production_engine_switch=false`；源代码开发不能替代 ABACUS 生产方法资格。
- P7 完整真实 force set、极性 NAC 所需 Born/ε∞、完整弹性真实任务集和中性缺陷 host/defect 对仍未完成。
- 带电缺陷的 VBM/费米能级/化学势/带电超胞修正接口可以分别进行数学或合同实现，但未形成带电原生生产结果。
- `design_assessment=not_assessed`；通用系统没有用户提供的产品指标和合格范围，不能对 CaZrO₃ 或 BaTiO₃ 宣布符合设计或失效。
- “未发生劣化”不等于材料满足设计；设计符合性和材料劣化诊断都必须消费相应工况、观测量、来源和资格证据。

## 9 0.9.0 仍待根窗口填写的最终统计

以下字段故意保留待填，不引用 job 42 的中间数字：

```text
installed_version: 待填写
installed_release_path: 待填写
installed_acceptance_json: 待填写
remote_final_job_id: 待填写
remote_final_terminal_state: 待填写
remote_final_exit_code: 待填写
remote_final_unit_tests_passed: 待填写
remote_final_unit_tests_failed: 待填写
remote_final_unit_tests_skipped: 待填写
installed_extension_checks: 待填写
installed_public_regression_checks: 待填写
source_installed_equality: 待填写
P7_complete_native_force_set: false，除非新增真实证据并由根窗口复核
P5_Berry_adapter: 未实现
LAMMPS_job41: 历史 run0 工程证据；0.9 安装副本状态待填写
production_qualification: false
temperature_matrix_started: false
design_assessment: not_assessed
```

根窗口应在 3 个远端测试问题修复后，重新执行 v100/Slurm 验收，确认安装副本与源代码边界，再将本草稿中的待填字段写入正式进度记录。任何新增数值任务、完整 P7 力集、Berry 路线或 MD 采样都必须附原生任务 ID、方法、结构、来源和资格状态，不能用软件通过数替代科学证据。
