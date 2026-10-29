---
name: mlcc-linear-electrostatics
description: Prepare and interpret the fem electrostatics_2d operation for a parameterized two-dimensional MLCC with a uniform linear dielectric and ideal equipotential electrodes.
---

# 二维 MLCC 线性静电

公网调用统一见[公网操作入口](../../../../skills/references/public-operations.md)；本文件只补充方法 schema、单位和结果解释。

本文件是按需读取的方法细节；创建、提交、查询和读取以[顶层运行Skill](../../../../skills/run-mlcc-fem/SKILL.md)及[公共生命周期](../../../../skills/references/task-lifecycle.md)为准。专业输入/schema、物理定义与检查仍由本模块维护。

用于 `fem/electrostatics_2d`。固定入口是本模块 `adapter.py`，由公共 TaskRecord/SiteRunner 在 Slurm 分配中调用；科学建模、网格、求解、导出在宿主显式绑定的 native Linux 环境运行。宿主可读的方法说明不等于已连接的 LLM/自动工具服务。

## 输入与选择

读本模块 [README](../../README.md) 与 [输入 schema](../../schemas/electrostatics.input.schema.json)。采用 SI：九个几何参数、有效间隙数、明确出平面深度、均匀 εr 及来源、A/B 电势、网格尺度、是否导出图片。必需科学值缺失时只澄清这些字段，不补材料、尺寸或深度。B=0 V 是有效接地，不能误报缺项。

有效间隙数不是电极数，电极数为间隙数加一。几何闭合要求 L=左边距+重叠长度+右边距；陶瓷 cover/margin 与主体同材。全部间隙已在几何中表示，不再给结果乘层数。例子是合成验证模型，不是某个实物产品的材料授权。

模型：二维截面沿面外方向不变；电极矩形从陶瓷扣除，暴露边界分别为 ELECTRODE_A/B 等势组，无金属域；其余 OUTER_INSULATION 为自然零位移通量。单个 CERAMIC 域使用 ε=ε0εr。只支持非零压差、P1 串行线性无源静电。输入不能指定后端命令、WSL路径、provider或审批状态。

若问题需要频率/介电损耗、漏电、击穿、非线性ε、不同材料分区、真实有限宽3D、温度反馈或电热力，不将其改写成当前静电模型；说明需另行确定方法。当前静电操作不包含这些物理。新增电热、AC-EQS和规定端口电磁见 [器件扩展Skill](../mlcc-device-coupling/SKILL.md)，需选择相应已注册操作；COMSOL未实现。

## 调用与失败

使用顶层Skill的 `mlcc create-task --module fem --operation electrostatics_2d --arguments ARGS.json` 准备任务；领域预检在Slurm分配内执行。部署由宿主提供 `MLCC_FEA_DEPLOYMENT`，不由用户科学输入或模型生成。ready 只说明结构/资源/已安装环境可用，不表示科学合格。实际 argv、路径映射及任务/产物管理由代码确定执行。

明确执行授权后沿prepare/transfer/submit执行；返回真实task/job。query查询调度、collect收集、read-result读取保存证据，不运行内层worker。不能只准备或提交就说计算完成；更改参数产生明确新任务。

校验错误指出具体字段/单位/几何关系。BACKEND_UNAVAILABLE/DEPLOYMENT_NOT_CONFIGURED 报环境事实，不安装依赖或静默换后端。科学异常保留 native response/stderr 和原始首错。SCIENTIFIC_STATE_UNKNOWN 或公共 interrupted 表示通信/客户端中断，**不能声称 Linux 求解已停止**；保留任务、核对原生进程，禁止自动重提交。

## 结果与检查

先读 execution，再读 numerical/scientific 每项状态和 provenance。主电容是能量法 `C=2U/ΔV²`；有符号电极电荷 `Q=-t∫D·n ds`，n向陶瓷外；U=t/2∫E·D dA。总 Q/U/C 与每米深度量分别列出，不能混成同一量。raw-flux 电容是离散通量诊断，同时报告两端电荷平衡、外绝缘通量和两种电容差。

`artifacts/fields/fields.vtu` 是原始场；manifest 区分节点电位和单元电场。VTU的z=0分量只是显示补零，不是三维模型。JSON 指标和原生日志为计算证据；图片只是辅助。原比例图与夸张纵向比例图分开，后者标题必须说明。

代码实际检查语义边界覆盖/互斥/外界身份、非空非退化三角形、PETSc reason、场有限性、VTU回读、摘要/文件hash与深度归一化。残差范数和三角形形状指标已保存；其科学阈值、一般MLCC电荷/电容容差、单任务网格收敛、材料适用性、实物对照未经确认时保持 `not_checked`。不得由LLM裁定收敛或以程序无错误替代检查。

独立 [验收记录](../../ACCEPTANCE.md) 包含平行板真实求解与解析比较、少量缩放及两级网格观测。其历史基准容差只适用该参考，不自动授予所有器件科学合格。尖角 Emax 对网格敏感，只解释为局部场诊断，不作击穿/安全结论。


## 显式多单位入口（0.2.0）

`fem/electrostatics_2d_quantities` 使用 [独立schema](../../schemas/electrostatics.quantities.input.schema.json)；旧 `electrostatics_2d` 和SI schema保持兼容。新入口长度/电势字段不用 `_m`/`_V` 后缀，必须提供 `{value, unit, source:{kind, reference}}`，例如间隙 `{value:5,unit:"um",source:{kind:"user",reference:"设计输入"}}`。不得把mm数值直接填进旧 `_m` 字段。间隙数为整数，epsilon_r为无量纲物理参数，不附长度单位。

Adapter通过唯一公共单位核心做确定性转换，再校验原SI模型；Agent不能自行计算换算结果来替代工具。缺单位或来源时澄清，不暗用全局单位、默认长度或推断材料。未知/维度冲突/非有限/多余字段拒绝。原始输入快照和 `input.original.json` 保留用户值；`input.canonical-si.json`、`unit_normalization.json` 保存实际SI输入与逐字段规则。科学进程仅接收SI，不二次转换。

全部结果仍为SI，电荷C是库仑；总量与每深度量保持原语义。单位一致性通过不升级任何not_checked科学检查。部署与执行授权仍由宿主管理，不进入多单位科学输入。
