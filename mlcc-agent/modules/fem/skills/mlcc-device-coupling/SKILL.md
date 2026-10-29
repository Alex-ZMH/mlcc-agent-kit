---
name: mlcc-device-coupling
description: Select and interpret MLCC two-dimensional electrothermal, AC-EQS and closed-port electromagnetic calculations with optional one-way steady heat.
---

# 二维器件电热与电磁

公网调用统一见[公网操作入口](../../../../skills/references/public-operations.md)；本文件只补充方法 schema、单位和结果解释。

本文件是按需读取的方法细节；创建、提交、查询和读取以[顶层运行Skill](../../../../skills/run-mlcc-fem/SKILL.md)及[公共生命周期](../../../../skills/references/task-lifecycle.md)为准。专业输入/schema、物理定义与检查仍由本模块维护。

沿Agent→领域Skill→TaskRecord/SiteRunner→Slurm内固定Adapter→显式科学环境→结构化结果链使用。不是另一套执行器；输入、单位、资源、状态和QC由代码决定。

## 选操作

| 操作 | 用途与输入 |
| --- | --- |
| `electrothermal_2d` | 均匀介质、实电势，DC导电或规定介电AC损耗到陶瓷+Ni稳态热。见[输入](../../schemas/electrothermal.input.schema.json)、[例子](../../examples/electrothermal.json)。 |
| `ac_eqs_2d` | 复电势EQS，均匀或半高度共形双介质，Y/Z/Cp及导电+介电损耗；可关闭热。见[输入](../../schemas/ac_eqs.input.schema.json)、[例子](../../examples/ac_eqs.json)。 |
| `electromagnetic_2d` | Ex/Ey/Hz Maxwell、有限导电Ni、规定闭合引导电流端口和回流，分区损耗及可选热。见[输入](../../schemas/electromagnetic.input.schema.json)、[例子](../../examples/electromagnetic.json)。 |

当前会话operation由宿主固定，不能默默用静电替代AC/EM，或用端口R/L冒充商业ESR/ESL。原静电操作仍可用于无损静态电容；本Skill不改变其契约。

## 输入与方法

带单位用户输入优先选对应 `electrothermal_2d_quantities`、`ac_eqs_2d_quantities`、`electromagnetic_2d_quantities`。其严格schema和示例见[多单位交接](../../EXTENDED_UNITS_HANDOFF.md)，完整字段为 `{value,unit,source:{kind,reference}}`，units=`explicit_quantities`。Adapter调用唯一公共normalize_fields；支持白名单中的mm/μm、kV、kHz/MHz、mA、S/cm、热导/对流单位和°C，不要求用户先换SI。绝对°C按公共偏移转K；温升输出仍为K。全部复分量单独带单位/source，current.convention固定rms；voltage_convention仍须明确rms/peak/dc，不能作为单位换算倍率。

旧三个SI操作保留严格SI后缀字段，不把typed对象塞进旧schema，不由LLM默算或丢单位。缺单位/来源时澄清；原始用户量值和canonical SI/quantity审计各自保存。仅SI副本进入既有科学内核，不能二次缩放；核心缺失、版本/白名单不支持或换算错误时拒绝，不改用私有换算。

必须提供几何及面外深度、材料eps_r/sigma/tan_delta及来源、激励/幅值约定、网格、散热参数与来源。计数及epsilon_r无量纲。没有实际材料/工况来源时不把合成示例说成真实产品输入；例子仅在用户允许时使用。

- ET：DC/lossless为f=0、实电势、dc约定；规定AC要求f>0、rms/peak、sigma=0，只计算介电规定损耗。DC与AC损耗不隐式相加。
- AC：f>0，RMS exp(+jωt)；peak先转换为RMS，不再乘额外1/2。导电与介电损耗分开记录；Ni理想等电势，只导热不发热。半高度分区必须是共形模型。
- EM：f>0、mu_r=1、显式复RMS电流；有限Ni发热，空气无损。必须指定bus/feed/bottom及端口来源。其闭合引导/PEC接触轨/磁壁是模型条件，不能说是开域辐射或实际PCB回流。
- 热为单向顺序稳态；指定左右端定温或Robin边界，其他固体边界绝热。不自动添加正反面对流；无温度反馈、瞬态、三维封装或磁滞。

## 执行与解释

固定公共入口 `mlcc create-task --module fem --operation OP --arguments ARGS.json`，由宿主绑定部署；创建不提交，执行授权后经prepare/transfer/submit一次，领域预检在Slurm内执行。部署与任务步骤见[公共生命周期](../../../../skills/references/task-lifecycle.md)，不得让LLM生成WSL命令、环境路径、资源限额或授权。缺依赖/非法输入应报告结构化错误；未知执行状态保留任务，不能自动重提或声称Linux已停止。

结果见[输出schema](../../schemas/device.output.schema.json)。复数对为[实,虚]。Cp在AC-EQS是Im(Y)/ω；EM的capacitance_F是能量等效值，不能与Cp混为一谈。EM磁能L包含参考面内馈电/回流，不是商业ESL。空值表示未计算/不适用，不能解释为0；零功率热阻为null。

先读execution，再逐项读quality。数值回归容差继承受审实验并保留依据，不构成产品科学阈值。原始端口通量/梯度热流与离散反力功率分开解释，不能用后者闭合掩盖前者误差。单任务网格收敛、解析对照、端口适用性、材料有效性及独立实测对照未实施时保留not_checked。

原始复场、温度和分区热源从VTU/XDMF/HDF5及映射NPZ产物引用，不手抄数组。PNG只是已保存场的展示，不作为独立科学验收。新操作尚未单独运行真实LLM对话验收，不把旧静电对话证据当作新操作对话。
