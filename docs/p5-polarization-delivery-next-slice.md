# P5 下一执行切片：极化来源、分支与响应

**当前：0.14已安装启用。** 原生公共交付138、分支模块136/边界139和安装140均已通过；宿主通过，无新DFT。以下首项实现合同已兑现为两个公共入口，不能再重复原计划的验收。0.15的核心下一项是[Berry GPU候选补丁/独立构建](berry-gpu-issue-53.md)以及由此恢复的实际响应生产者；现有单点只能提供代表值，真实ΔP/Born/介电仍缺。实施窗口转入[CER-DATA薄适配](../workspace/reports/polarization-path-v001/cer-data-review/integration-request.md)，其独占ceramic_data.py、test_ceramic_data.py、reports/ceramic-data-v001，主线保留Study/原生来源/公共接口，standalone原作者文件不改。

前置状态：0.13中性原始能量链/安装127已通过。按用户纠偏要求，核心优先级回到铁电/介电，暂停新增基础Ni MD、RDF精调、MSD/统计/聚合物扩展。原P0–P12清单不删项；独立DeePMD专项不接管。

## 所有权与最小实现

主窗口负责P5方法/物理适用性、任务与来源合同、公共入口/交付和集成。复用既有property_delivery和assess_design，新增小型专用极化交付函数，不能把仅接受eV电子标量的deliver_electronic_properties硬套到Berry结果。现有实施聊天负责独立极化差/分支直接函数及对应验收；具体文件所有权交接后登记，不同时修改主窗口CLI/property_delivery。无需新的路由、主控或自动选相机制。

已交接文件所有权：实施窗口独占`mlcc-agent/src/mlcc/polarization.py`、`mlcc-agent/tests/test_polarization.py`、`workspace/reports/polarization-path-v001`；主窗口及其子代理不创建重叠模块。首切片固定胞/单gdir、显式整数分支；最近邻半量子算法不能自动证明物理连续性。

首项真实路径完全复用50/58/65：从原生Berry解析结果交付指定gdir的极化代表值、方向向量、单位、极化量子、branch_status、原生NSCF/参考SCF任务与job来源。须对Study/模型/方法/来源一致性做绑定，保留CPU兼容证据身份、not_unwrapped及全部未资格状态。使用单一方向时不能伪造完整3D向量。

公开交付包可供既有assess_design消费：无指标not_assessed，有指标但未资格insufficient_evidence。单状态绝对极化模量子代表值不等于自发极化、Born电荷或介电常数；任何此类字段均保持未计算。原生task/source文件只读，不靠填写缺省量子、分支或方向补齐。

## 后续核心路径

1. 极化差与分支直接函数：显式参考/目标/路径、方向和量子，记录分支选择/歧义；不把单个58结果复制成多个状态，不把数学测试作为真实极化路径。原生来源验收与算法验收分开。
2. 实际引擎响应路线：针对安装ABACUS3.10.1的真实版本实现核对有限场/原子位移/应变可执行性，明确所需参考、扰动、单位、边界及电子/离子贡献。未经版本证明不生成DFPT/Born/epsilon输入；本机不支持则记具体阻因与恢复条件，推进独立数据路径。
3. 只有需要验证新增真实路径时才补最小任务。GPU支持则GPU；实际DFT经v100 Slurm time=0，明确资源并按原生收敛验收，不调参追好数值、不扩矩阵、不代选BTO相。

## 已有证据与限制

50为参考SCF；58为既有CPU Berry兼容输出，gdir=1、极化量子和未解分支已原生解析；65为解析/入口证据。GPU53失败及61的FFT边界故障独立追踪，没有有效GPU极化结果；现有创建器/解析器限定CPU，不得声称GPU路径已修复。

不重跑CPU Berry；GPU仅在能新增定位证据且有具体修复依据时运行。Berry GPU局部问题不阻塞极化交付、明确来源的分支函数或独立响应能力审查。首项新入口验收仅在v100 Slurm后处理作业中运行，复用原生输出，检查错误身份/缺量子或来源拒绝；不重复65全套验收。
