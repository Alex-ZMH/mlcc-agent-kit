# 0.9.0 系统功能合同与验收边界

0.9.0 已安装启用并完成验收。P7 Phonopy 入口、ABACUS 位移子任务适配器、原生力收集门和 LAMMPS 工程适配器已经纳入 Bundle。数值测试与后处理验收均在 v100 的 Slurm 作业中完成；最终证据见 [acceptance.json](../workspace/reports/system-v090/acceptance.json)。

系统仍是通用 MLCC 计算系统。CaZrO₃ 与 BaTiO₃ 是验证案例上下文，Ni 是已有的 LAMMPS 工程 fixture。案例名称不等于材料相、工艺路线、铁电状态或生产资格已经被系统自动选择和确认。

## 1 版本范围和证据分层

| 轨道 | 0.9.0 可交付的接口 | 证据边界 |
| --- | --- | --- |
| P7 声子软件桥 | 显式 `+/-` 位移计划、每个位移独立子模型/Study、固定胞 ABACUS SCF 输入、真实力收集门、谐波 q 点数学计算入口 | 计划和输入可验收；完整真实力集尚未形成，因而不授予声子或生产资格 |
| LAMMPS P9/P10 桥 | 显式势文件、显式 run0/MD 协议、LAMMPS data/input 导出、原生 log/dump 解析、Slurm 任务记录 | Ni job 41 是工程静态回路证据，fixture=true；势的科学适用域、MD 采样和生产资格未通过 |
| 工作流语义 | 将 LAMMPS run0/MD 标为工程完成，并保留科学依赖的 `converged` 门 | `evaluated_engineering_fixture` 与 `executed_engineering_fixture` 不得作为科学收敛依赖 |
| 温度语义 | 保持固定胞静态声子入口与调用者显式的 LAMMPS MD 温度字段 | 不生成温度矩阵；CaZrO₃ 的 400–580 °C、BaTiO₃ 的 800–1350 °C 只是后续工艺/热过程 Study 的上下文，不被写成当前 DFT 力或声子温度结果 |

0.8.0 的基线验收记录继续保留。0.9.0 使用独立证据：v100 job43 为 296 项测试全部通过，job44 复核安装副本；前一轮 job42 的 3 个测试缺陷及原始失败报告保留，修复后才形成最终验收。没有把历史本地测试改写成远端测试。

数值任务和安装副本验收位置固定为 v100/Slurm；本地窗口只负责代码编辑、任务控制和证据查看，不在本地运行 DFT、MD、声子力集或其他数值验收。已有 workspace 记录若来自历史窗口，只能按其原始来源和任务记录使用，不能改写成当前 0.9.0 的远端验收统计。

## 2 P7：显式有限位移计划

入口：

```text
mlcc phonon-plan --model <模型目录> --request <请求.json> --output <计划目录>
```

CLI 的三个参数都是必填。`--output` 是新计划目录，目录已存在时函数拒绝覆盖。计划生成使用 `phonopy` 的显式固定设置：`is_plusminus=true`、`is_diagonal=false`、`is_trigonal=false`、`calculator=null`、力单位约定 `eV/angstrom/amu`，并保存行向量晶胞约定和原子 lineage。

最小请求对象如下，字段名和类型对应当前实现：

```json
{
  "plan_id": "czo3-p7-phonon-v001",
  "version": "v001",
  "phonopy_version": "4.8.3",
  "repeat_matrix": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
  "primitive_matrix": [[1.0, 0.0, 0.0], [0.0, 1.0, 0.0], [0.0, 0.0, 1.0]],
  "distance_angstrom": 0.01,
  "symprec": 1e-5,
  "is_symmetry": true,
  "hermitianize_dynamical_matrix": false
}
```

CaZrO₃ 的验证调用可以将 `--model` 指向 `workspace/models/cazro3-pnma-pristine/v001`。BaTiO₃ 采用完全相同的请求合同，只替换为调用者明确提供的 BTO 模型目录和已经选定的相；当前系统不会从材料名称自动选立方、四方、正交或铁电相，也没有交付 BTO 材料选择结果。计划输出的主文件为 `displacement-manifest.json`，schema 为 `mlcc.phonon-displacement-plan.v1`，至少包含：

- `source_model`：父模型 ID、版本、路径、材料和请求相字段；
- `reference`：未位移参考超胞的结构、原子 ID、质量、初始磁矩和 lineage；
- `displacements`：每个 `entry_id`、`sign`、`phonopy_atom_index`、`displaced_atom_id`、`displacement_angstrom`、结构文件、原子 ID、质量、初始磁矩和 lineage；
- `production_qualified=false`、`scientific_qualification=false` 和 `scientific_status=software_displacement_plan_only`。

计划只产生结构计划，不能被解释成 DFT 力、频率、热力学稳定性或铁电性质结果。加载计划时会重新核对父模型、参考结构、每个位移结构、质量、磁矩、原子 ID、晶胞和位移向量，防止以改写的 extxyz 代替已验证计划。

## 3 P7：独立位移子模型和 ABACUS 静态输入

入口：

```text
mlcc create-phonon --plan <displacement-manifest.json> --study <母Study.json> --method <ABACUS方法.json> --site <站点.json> --request <请求.json> --output <子模型与任务目录>
```

六个参数都是必填。`--plan` 必须是上一节的 `displacement-manifest.json`，而不是计划目录。请求必须显式给出一个计划条目，当前适配器要求以下字段：

```json
{
  "displacement_id": "reference",
  "child_model_id": "czo3-p7-child-reference-001",
  "child_model_version": "v001",
  "child_study_id": "czo3-p7-study-reference-001",
  "task_id": "czo3-p7-scf-reference-001",
  "resource_request": {
    "nodes": 1,
    "partition": "gpu",
    "ntasks": 1,
    "cpus_per_task": 1,
    "gpus_per_task": "v100:1",
    "hint": "nomultithread",
    "mem_mib": 8192,
    "time": "00:20:00"
  },
  "required_results": []
}
```

`displacement_id` 也可以是 manifest 中的 `disp-000001` 等显式位移条目。`child_model_id`、`child_model_version`、`child_study_id` 和 `task_id` 必须与父对象和同一计划条目区分开。`calculation` 只能省略或写为 `scf`，`input_transformation` 必须为 null。

创建动作会：

1. 从已验证 manifest 读取所选结构，创建独立子模型，不任意重建或信任被改写的结构文件；
2. 保留父模型的材料、相、案例、掺杂、质量、初始磁矩和父 Study 来源，并在 lineage 中登记所选位移向量、原子 ID 和父子关系；
3. 写出子模型 `model.json/model.extxyz/source.cif/atom-lineage.json/dopants.json`、子 `study.json`、`abacus-request.json` 和本地 ABACUS TaskRecord；
4. 使用现有 ABACUS 创建器生成固定胞、0 K reference 条件的静态 SCF 输入，阶段为 P7，状态为 `defined`，不提交调度任务。

输出中的 `task.json.phonon_displacement` 保存 `plan_id`、`plan_version`、manifest 路径、`displacement_id`、父模型/父 Study 身份和位移信息。子模型保持 `relaxation_status=not_run`、`production_qualified=false`。这一步的成功只说明输入链路和身份绑定成功，不说明 ABACUS 已运行。

## 4 P7：真实原生力收集门

入口：

```text
mlcc phonon-forces --plan <displacement-manifest.json> --tasks <任务目录...> --thresholds <阈值.json> --output <力收集.json>
```

`--plan`、`--thresholds`、`--output` 必填；`--tasks` 是可重复的路径列表，当前 argparse 允许空列表，以便明确产生 blocked 结果。阈值对象必须包含以下五个有限正数，单位固定：

```json
{
  "force_match_tolerance_eV_per_A": 1e-9,
  "reference_force_tolerance_eV_per_A": 0.01,
  "force_drift_tolerance_eV_per_A": 0.01,
  "geometry_tolerance_A": 1e-7,
  "displacement_tolerance_A": 1e-7
}
```

适配器只接受真实 ABACUS 任务/结果证据，不生成力、不填补缺失条目、不提交任务。要得到 `ready_for_harmonic=true`，输入集合必须包含 manifest 的 `reference` 和每一个显式 `+/-` 位移条目，并通过以下检查：

- 任务均为 P7、原生调度状态 `COMPLETED` 且退出码 `0:0`，电子收敛标志为 true；
- `task.json`、子模型、子 Study、父 Study、manifest 条目、原子 ID、元素、坐标、质量、磁矩和 lineage 一致；
- ABACUS `INPUT/KPT/STRU` 与方法记录、原生固定胞 SCF 力输入和方法物理设置一致；
- 任务为中性（`net_charge == 0`），同一方法集、赝势、原生物理和结果来源；
- 原生日志力和保存结果力在 `force_match_tolerance_eV_per_A` 内，参考残余力、力漂移、几何和位移误差满足显式阈值。

返回对象 schema 为 `mlcc.phonon-force-collection.v001`。不满足集合完整性或任一检查时，状态为 `blocked_force_collection`、`ready_for_harmonic=false`，并保留 `checks` 和 `issues`。当前 `workspace/reports/system-v090/phonons/source-v002/acceptance.json` 记录的是计划/输入链路验收，明确 `complete_native_phonon_force_set=false`；当前 workspace 没有完整真实位移力集。因此不能把软件输入验收写成声子力集已完成。

## 5 P7：谐波 q 点数学入口

入口：

```text
mlcc phonon-qpoints --plan <displacement-manifest.json> --tasks <任务目录...> --thresholds <阈值.json> --qpoints <q点.json> --output <谐波结果.json>
```

该入口先执行上一节的真实力收集门。只有 `ready_for_harmonic=true` 才读取 q 点并调用 `compute_harmonic_qpoints`；否则写出 blocked 收集结果并返回非零退出状态。q 点文件是 primitive reciprocal fractional 坐标的 JSON 数组，例如：

```json
[[0.0, 0.0, 0.0], [0.5, 0.0, 0.0]]
```

通过力门后，结果 schema 为 `mlcc.phonon-harmonic-result.v1`，力单位为 `eV/angstrom`，输出声子力常数和所请求 q 点频率。当前输出明确保留 `scientific_status=software_math_only_unqualified`、`production_qualified=false`、`scientific_qualification=false`、`nac=not_requested`、`asr=not_applied` 和 `imaginary_frequencies_preserved=true`。它不进行温度修正、不生成温度矩阵、不自动施加 ASR/NAC，也不把频率升级为材料稳定性或 MLCC 设计合格结论。

## 6 LAMMPS：显式势、协议、导出和原生解析

### 6.1 创建工程任务

入口：

```text
mlcc create-lammps --study <Study.json> --model <模型目录> --potential <势.json> --protocol <协议.json> --site <站点.json> --request <请求.json>
```

六个参数都是必填，当前入口没有 `--output`；任务目录由 `site.workspace.local/tasks/<task_id>` 决定。任务请求的最小结构由当前实现直接读取：

```json
{
  "task_id": "p9-ni-lammps-run0-v001",
  "required_results": [
    {
      "task_id": "h1-ni-relax-v001",
      "result_file": "result.json",
      "scientific_status": "converged_engineering_fixture"
    }
  ],
  "resource_request": {
    "nodes": 1,
    "partition": "cpu",
    "ntasks": 1,
    "cpus_per_task": 1,
    "hint": "nomultithread",
    "mem_mib": 1024,
    "time": "00:02:00"
  }
}
```

`potential.json` 必须由调用者提供明确的 `potential_id`、`version`、`source`、`license`、`elements`、`element_order`、`model_ids`、`units`、`atom_style`、`pair_style`、`pair_coeff`、`files`、`fixture` 和生产资格字段。当前适配器只接受 `units=metal`、`atom_style=atomic`、三维周期边界和与模型元素集合完全一致的势；不推断势、不添加电荷、不混用 DFT 能量。

run0 协议的最小字段为：

```json
{
  "protocol_id": "ni-static-run0-v001",
  "kind": "run0",
  "units": "metal",
  "boundary": ["p", "p", "p"],
  "timestep_ps": 0.001
}
```

run0 不允许 `temperature_K` 或 `seed`。MD 协议的 `kind` 必须为 `md`，还必须显式给出 `ensemble`（`nve` 或 `nvt`）、`steps`、`timestep_ps`、`temperature_K`、`seed`、`thermo_every`、`dump_every`；`nvt` 还必须给出 `tdamp_ps`。`dump_every` 必须整除 `steps`，以保存最终步；解析逐原子核对轨迹末帧与 `dump.final` 的类型、坐标和力。这些字段描述输入协议，不授予采样平衡或生产资格。

创建任务会显式导出 `model.data`、`atom-map.json`、`in.lammps`、`method.json` 和调用者指定的势文件，写入 Slurm 任务记录，但不 transfer、不 submit。P9 run0 和 P10 MD 都保持 `fixture=true`、`production_label=false`。

### 6.2 解析真实回传

入口：

```text
mlcc parse-lammps --task <已完成任务的task.json>
```

该入口没有 `--output`，在任务目录写入 `result.json`。解析前必须存在已保存的真实 Slurm `COMPLETED/0:0`，任务、站点、原生 LAMMPS 版本、`method.json`、势身份、协议和模型身份必须一致。解析器实际读取 `log.lammps` 和 `dump.final`，核对 `units metal`、步数、盒子、原子 ID/type、坐标和力；缺少原生产物或身份不一致时保留原始错误。

结果 schema 为 `mlcc.lammps-result.v1`。run0 结果的 `scientific_status` 为 `evaluated_engineering_fixture`；MD 结果的状态为 `executed_engineering_fixture`，并显式保留 `sampling_equilibrium_qualified=false`。二者都不进入通用科学收敛集合。

现有真实工程证据是 `workspace/tasks/p9-ni-lammps-run0-v001/`，Slurm job **41**，终态 `COMPLETED/0:0`，包含真实 `log.lammps`、`dump.final`、`method.json`、`model.data`、`atom-map.json` 和 Ni_u3.eam。该证据证明导出→原生运行→回传解析链路可工作；它不证明 CaZrO₃/BaTiO₃ 势、陶瓷温区、界面、铁电响应、热输运、MD 采样或生产材料资格。

## 7 工作流完成语义和科学依赖

`inspect_task` 对通过身份、调度、原生结果和来源检查的 LAMMPS 工程任务返回 `action=completed`，同时返回 `scientific_qualification=false`，并说明这是工程静态评估（run0）或工程 MD 执行记录（md）。这只是生命周期完成语义。

`require_result_dependencies` 继续要求真正的科学 `converged` 门。`evaluated_engineering_fixture` 和 `executed_engineering_fixture` 不得代替科学依赖，也不能绕过电子收敛、方法、原子结构、来源和单位检查。工程 fixture 的完成不能推导材料性质或设计达标。

## 8 六个新增 CLI 入口速查

| 入口 | 必填参数 |
| --- | --- |
| `phonon-plan` | `--model --request --output` |
| `create-phonon` | `--plan --study --method --site --request --output` |
| `phonon-forces` | `--plan --tasks --thresholds --output` |
| `phonon-qpoints` | `--plan --tasks --thresholds --qpoints --output` |
| `create-lammps` | `--study --model --potential --protocol --site --request` |
| `parse-lammps` | `--task` |

JSON 字段的最小合同分别见第 2–6 节。`create-lammps` 和 `parse-lammps` 没有输出路径参数；它们使用站点工作区和任务目录合同。声子 q 点入口不能绕过真实力收集门，LAMMPS 解析入口不能把缺少原生 log/dump 的目录当作完成任务。

## 9 本版明确未交付项

本版交付边界不包括：

- 温度矩阵或由烧制温度自动展开的计算矩阵；
- 完整、真实、同一 ABACUS 方法下的声子参考态与全部 `+/-` 位移力集；
- 由缺少力集的输入计划产生的真实频率、声子稳定性或生产声子资格；
- 真实 MD 热平衡/采样收敛、尺寸/时间步/势的科学资格；
- CaZrO₃ 的 400–580 °C 或 BaTiO₃ 的 800–1350 °C 材料温度性质结论；
- BaTiO₃ 的材料相、结构、铁电状态或任务集合自动选择；
- MLCC 器件、电极/介质界面、缺陷浓度、极化、介电响应、热输运或生产设计合格线；
- 任何生产资格、替代 ABACUS/VASP 的静默回退或由工程 fixture 推导的科学结论。

## 10 0.9.0 最终验收

2026-10-22 完成，来源为 `workspace/reports/system-v090/`：

```text
installed_version: 0.9.0
acceptance_json: workspace/reports/system-v090/acceptance.json
remote_unit_tests: 296 passed, 0 failed, 0 skipped; Slurm job43 COMPLETED/0:0
installed_phonon_checks: 14 passed
installed_lammps_checks: 9 passed
installed_extension_checks: 18 passed
installed_public_regression_checks: 13 passed
installed_Ca_native_checks: 17 passed
installed_contracts: passed
installed_verification: v100 Slurm job44 COMPLETED/0:0
MatterAI_original_host_and_MCP: passed; version 0.9.0, 7 tools
source_release_installed_equal: 44 text files, direct comparison
phonon_native_force_set: 未完成
lammps_job41_native_parser: 安装副本复核通过，静态run0，不是MD采样
production_qualification: false
temperature_matrix_started: false
design_assessment: not_assessed
```

0.9.0 完成的是上述系统软件切片。P0–P12 整体、H1/生产引擎资格、完整声子力集及 MD 科学资格仍未完成。下一软件切片按精确版本审查推进 P5 Berry 极化输入与原生解析；不能把 slab saw-like 电场当成体相有限场或 DFPT 介电路线。
