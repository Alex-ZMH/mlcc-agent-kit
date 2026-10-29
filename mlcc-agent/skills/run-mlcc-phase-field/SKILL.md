---
name: run-mlcc-phase-field
description: 为 MLCC 选择标量或全矢量铁电相场稳态、演化及静态分支切线操作，处理显式参考尺度、畴结构和保存的场/张量结果。
---

# MLCC 铁电相场计算

使用 `module_id=phase_field`，处理限定 LGD 模型的极化、畴演化或静态分支响应。组织均质化选择 RVE，器件几何电容选择 FEM；各模块独立运行。

## 选择操作与方法

| 需求 | 无量纲操作 | 显式尺度 SI 操作 | 深层方法 |
| --- | --- | --- | --- |
| 固定标量 y 极化稳态/演化 | `steady`、`evolve` | `steady_si`、`evolve_si` | [标量方法](../../modules/phase_field/skills/mlcc-scalar-ferroelectric/SKILL.md) |
| 2D 两分量/3D 三分量极化稳态/演化 | `vector_steady`、`vector_evolve` | `vector_steady_si`、`vector_evolve_si` | [全矢量方法](../../modules/phase_field/skills/mlcc-vector-ferroelectric/SKILL.md) |
| 平衡分支完整静态介电切线张量 | `dielectric_tangent` | `dielectric_tangent_si` | [静态切线方法](../../modules/phase_field/skills/mlcc-tangent-dielectric/SKILL.md) |

空间 3D 不自动意味着三分量极化。标量与矢量的能量系数、畴壁宽度、边界和输出定义分别读取，不能混用。动态 P–E 轨迹斜率不替代静态切线操作。

## 输入与准备

用 `mlcc describe-scale --module phase_field --operation OP` 读取选定输入 schema。明确维度、模型 profile、初态、材料/合成参数来源、网格及场条件。演化需要明确时间协议和步进范围；静态切线需要明确偏置加载路径与平衡/稳定性相关输入，不添加演化时间项。

SI 入口还需正有限的长度、极化、时间、能量密度四个参考尺度及来源。保留用户量值，UNIT 与模块尺度映射确定执行；不把 reduced epsilon、绝对 F/m 和相对介电率混为一谈。合成 profile 和尺度不构成材料标定。授权输入保持逐字段原值；缺项时按所选方法澄清，不改初态、网格或系数来迁就预算。

## 创建、执行与读取

ARGS.json 为 `input_path`、`site_path`、`request_path` 路径对象，分别引用已确认科学输入、宿主站点和任务/资源请求。

```sh
mlcc create-task --module phase_field --operation OP --arguments ARGS.json
mlcc prepare --site SITE.json --task TASK.json
mlcc transfer --site SITE.json --task TASK.json
mlcc submit --site SITE.json --task TASK.json
```

创建不求解、不提交；执行授权后沿同一 Slurm 生命周期运行。返回任务号后按需 `query`、`collect`，随后 `mlcc read-result --task TASK.json`。部署选择和具体失败处理见 [公共生命周期](../references/task-lifecycle.md)。同任务追问读取已有结果与文件，不重新启动求解。

## 已有性质与产物

稳态/演化已输出极化、电势、电场、能量及对应历史；完整 NPZ、VTU、XDMF/HDF5 与引用由模块保存。`solver_dimensionless`、可选 `results_si` 和 `unit_mapping` 分开读取。二维积分能量 SI 为 J/m，三维为 J，不虚构二维厚度；PNG 切片不替代完整体数据。

切线结果已输出完整张量、背景/极化贡献、分支与稳定性诊断，直接读取 [张量结果](../../modules/phase_field/schemas/tangent.result.schema.json)。SI 为绝对 F/m，`relative_permittivity` 的 null 保持；不由 LLM 换算为 εr。不稳定/近奇异或未平衡拒绝不能改写为有效材料张量。有限固定端多畴表观响应与均匀分支局部响应分别说明。

先读取 execution 和各项 QC，再解释场、历史或张量。Newton 收敛不证明稳定性，有限时间轨迹不证明准静态材料滞回。未实施的网格/时间收敛和材料检查保持 `not_checked`。无弹性、电致伸缩、温度材料标定或自动 RVE/FEM 传参；遇原生失败/未知状态保留证据，停止自动推进，不换模型或重提。
