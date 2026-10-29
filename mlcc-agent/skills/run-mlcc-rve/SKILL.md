---
name: run-mlcc-rve
description: 根据明确微结构和材料输入执行独立二维/三维静态介电或导热 RVE 均质化，读取有效张量、逐载荷场及适用性证据。
---

# MLCC 静态 RVE 均质化

公网调用先走[统一操作入口](../references/public-operations.md)；四个 RVE operation 的 describe/create/read 仍复用本模块既有 ops，不自动接入 FEM 或替换材料、组织和边界。

使用 `module_id=rve`。问题是“给定组织的等效材料响应”时选择本 Skill；畴演化选择相场，器件边界/几何响应选择 FEM。不自动消费其他尺度的张量。

## 选择操作

| 维度/物理 | 操作 | 结果 |
| --- | --- | --- |
| 二维静电 | `homogenize_electrostatics_2d` | 2×2 绝对有效介电张量 |
| 三维静电 | `homogenize_electrostatics_3d` | 3×3 绝对有效介电张量 |
| 二维稳态导热 | `homogenize_thermal_2d` | 2×2 有效导热张量 |
| 三维稳态导热 | `homogenize_thermal_3d` | 3×3 有效导热张量 |

按需读取 [静态 RVE 方法](../../modules/rve/skills/static-rve/SKILL.md)，其中定义可用组织、孔隙模型、周期/仿射边界和固定单位宏观载荷。不是任意可调工况的动态模拟。

## 输入与准备

通过 `mlcc describe-scale --module rve --operation OP` 读取专业 schema。明确实际尺寸、网格、几何类型及相关参数、孔隙比例/模型、边界条件和严格材料条目数组。区域标签须完整覆盖，每个材料系数或张量都有单位、来源与适用说明。多晶取向元数据不代表已经实现本构旋转；不支持的几何组合直接说明缺项，不换组织继续算。

输入的相对介电率是单位 1，导热系数带明确单位；F/m 不能填入相对介电率入口。保留量值原表示，由共享 UNIT 和确定性代码校验。示例仅在用户授权后按合成用途使用，不能当真实材料默认值。

## 创建、执行与读取

ARGS.json 提供 `input_path`、`site_path`、`request_path`；科学输入和宿主部署/资源分开。

```sh
mlcc create-task --module rve --operation OP --arguments ARGS.json
mlcc prepare --site SITE.json --task TASK.json
mlcc transfer --site SITE.json --task TASK.json
mlcc submit --site SITE.json --task TASK.json
```

创建只准备未提交任务；执行授权后提交一次，按需 `query`、`collect`，再用 `mlcc read-result --task TASK.json`。见 [公共生命周期](../references/task-lifecycle.md)。已有任务先查询，追问读取同一任务，失败或未知状态停止自动推进并核对原生证据。

## 已有性质与产物

专业结果已含 `tensor`、`tensor_unit`、维度、物理、边界、孔隙模型、载荷数及产物引用；直接读取，不重新拟合或做标量平均。介电输出为 F/m，导热为 W/(m K)；保留非对角项、原坐标与二维/三维形状。

`effective_material_artifact` 指向有效材料文件，`readback_artifact`、`coordinate_artifact` 和 `load_fields` 给出独立回读、坐标映射及逐载荷场。按返回引用定位文件，不猜绝对路径。模块已有后处理检查保存场/平均通量/功与周期条件，解释时不再次求解。

报告 execution、numerical/scientific 状态及实际误差。数值通过不授予统计代表性、材料标定、单任务网格收敛或器件适用性；未检查项保持 `not_checked`。有效材料文件独立交付，不自动接器件 FEM，也不把均质化数值称为实测材料参数。
