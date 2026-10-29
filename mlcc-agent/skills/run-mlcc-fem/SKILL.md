---
name: run-mlcc-fem
description: 根据明确器件几何、材料和边界条件，选择并执行 MLCC 二维静电、电热、AC-EQS 或限定闭合端口电磁计算，读取场与端口指标。
---

# MLCC 器件有限元计算

使用 `module_id=fem`。用户希望由几何和材料求电容、场、损耗或温升时使用本 Skill；给定 RLC 参数求电路波形时选择 `run-mlcc-spice`。独立计算无需先运行 DFT、MD、相场或 RVE。

## 选择操作

| 需求 | SI 操作 | 显式量值操作 | 按需读取 |
| --- | --- | --- | --- |
| 理想等势电极、均匀线性介质的静电 | `electrostatics_2d` | `electrostatics_2d_quantities` | [静电方法](../../modules/fem/skills/linear-electrostatics/SKILL.md) |
| DC 导电或规定介电 AC 损耗到稳态热 | `electrothermal_2d` | `electrothermal_2d_quantities` | [器件扩展方法](../../modules/fem/skills/mlcc-device-coupling/SKILL.md) |
| 复电势 EQS、导电/介电损耗和可选热 | `ac_eqs_2d` | `ac_eqs_2d_quantities` | 同上 |
| Ex/Ey/Hz、有限导电 Ni、规定端口和回流 | `electromagnetic_2d` | `electromagnetic_2d_quantities` | 同上 |

仅加载选定物理的方法说明与 schema。上述是不同物理模型；不能为了输入方便改用另一个操作。

## 输入与准备

先明确二维截面几何、有效间隙数、面外深度、材料系数及来源、激励和网格；电热还需散热条件，AC/EM 还需频率、相量/幅值约定和相应端口定义。逐字段以 `mlcc describe-scale --module fem --operation OP` 返回的 schema 为准。有效间隙数不是电极数，结果不再乘一次层数。

用户提供带单位量值时选对应 quantities 操作，保留 `{value,unit,source}`；已有合法 SI 文件保持原表示。单位转换由模块的公共 UNIT 调用完成。缺材料、尺寸、深度、频率或边界条件时只澄清必要字段，不拿合成例子补值。输入中不放解释器、SSH 命令或部署授权。

## 创建、执行与读取

将已确认输入写入 INPUT.json，宿主准备 SITE.json 与明确资源/任务身份的 REQUEST.json。ARGS.json 具有 `input_path`、`site_path`、`request_path` 三个路径字段。

```sh
mlcc create-task --module fem --operation OP --arguments ARGS.json
mlcc prepare --site SITE.json --task TASK.json
mlcc transfer --site SITE.json --task TASK.json
mlcc submit --site SITE.json --task TASK.json
```

创建仅校验并准备文件；有执行授权后才提交。返回 task/job 后报告实际状态。后续用 `query` 查询、`collect` 收集，再用 `mlcc read-result --task TASK.json` 读取。[公共生命周期](../references/task-lifecycle.md) 说明路径、失败与重复查询规则；已有任务先查询，不因缺结果重建。

## 已有性质与产物

静电结果已包含电势/场诊断、电荷、能量、能量法电容、原始通量法电容及平衡误差，定义见静电方法。总量与每米深度量分别解释，尖角 Emax 不作为击穿结论。

扩展操作读取专业结果的 `electrical`、`thermal` 和已登记场文件。AC-EQS 的 Cp、EM 能量等效电容及端口磁能 L 各有定义；不统一改名为商业 C/ESR/ESL。未启用热时不补温度或热阻。完整结果见 [静电输出](../../modules/fem/schemas/electrostatics.output.schema.json)、[扩展输出](../../modules/fem/schemas/device.output.schema.json)。

这些指标已由模块计算和检查；解释时直接读取保存结果及引用，不另写公式重新求值。VTU/XDMF/HDF5 等是原始场，PNG 是辅助展示。先报告 execution，再报告 numerical/scientific 各检查；材料、端口适用性、网格收敛及实测对照的 `not_checked` 保持原值。

当前范围为已声明二维模型，无完整三维封装、自动参数传递或通用多物理反馈。部署/原生错误保留原任务和日志，停止自动推进；未知远端状态须核对，不能自动重提或换后端。
