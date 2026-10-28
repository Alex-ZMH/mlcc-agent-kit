---
name: run-mlcc-spice
description: 根据明确给定的线性 RLC、漏电及源/负载参数运行 ngspice AC 阻抗或有限脉冲瞬态，读取频响、波形及模块已有指标。
---

# MLCC 电路响应计算

使用 `module_id=spice`，处理给定电路参数的频响或单脉冲问题。根据器件几何求场或提取响应时选择 FEM；本入口不自动从其他尺度抽取 C/ESR/ESL。

## 选择操作

| 需求 | SI 操作 | 显式量值操作 |
| --- | --- | --- |
| 单支路或受控并联 RLC 的 AC 阻抗 | `ac_impedance_si` | `ac_impedance` |
| 有限源阻/外线电感的单脉冲与恢复 | `transient_si` | `transient` |

按需读取 [线性电路方法](../../modules/spice/skills/linear-circuits/SKILL.md)，其中定义支路数、漏电位置、电流方向、AC 功率约定及瞬态初态。

## 输入与准备

通过 `mlcc describe-scale --module spice --operation OP` 读取选定 schema。明确模型名/版本、synthetic/manual 来源、适用条件、C、ESR、ESL 和可选端口漏电。AC 需要明确扫频范围和采样；瞬态需要源/负载、外部线参数及完整脉冲/采样时间。缺参数时澄清，不从材料名称、封装名称或示例推断寄生参数。

SI 操作按既有字段单位提供数值；量值操作保留 `{value,unit,source}`，由共享 UNIT 转换。电容 F 与介电系数 F/m 不混用。只支持受控结构化线性电路，不生成任意 netlist/include、拟合、非线性或温度/偏压定律。

## 创建、执行与读取

ARGS.json 为 `input_path`、`site_path`、`request_path` 三个路径字段。解释器和 ngspice 路径由宿主站点配置提供，不进入科学输入。

```sh
mlcc create-task --module spice --operation OP --arguments ARGS.json
mlcc prepare --site SITE.json --task TASK.json
mlcc transfer --site SITE.json --task TASK.json
mlcc submit --site SITE.json --task TASK.json
```

创建不计算；执行授权后经 Slurm 提交一次。后续 `query`、`collect`，再用 `mlcc read-result --task TASK.json`。见 [公共生命周期](../references/task-lifecycle.md)。追问频点或指标时读取同一任务的已保存曲线/metrics，不重跑或自动加密扫频。

## 已有性质与产物

专业结果的 `summary` 与 `metrics_artifact` 已包含本操作计算的指标，`curve_artifact` 是曲线，另保留原生 raw、CSV、日志和独立回读，见 [输出契约](../../modules/spice/schemas/output.schema.json)。按登记引用读文件，不手抄数组或重复计算指标。

AC 的采样最低点、插值虚部零点和单支路 L/C 抵消频率分别解释，不能把它们统称网络反谐振；有限采样不提供峰值收敛资格。瞬态 RMS 仅对实际有限脉冲/恢复窗口定义，不是周期稳态纹波；电容向母线供能时保留有符号功率/电流。不同模型比较须有相同源/负载条件。

先报告 execution、数值检查及科学检查；保留材料、器件和采样敏感性的 `not_checked`、null 与原失败。理想无损共振可能奇异，不能以修改 ESR 或删数据强行成功。部署或求解错误保留原任务与首错，不自动换后端、重试或重提。
