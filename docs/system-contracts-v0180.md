# MLCC 0.18交付：P5来源与Study交付

2026-10-22 22:42。0.18已验收启用冻结，0.17回退，源码0.19候选。v100安装job199为COMPLETED/0:0、4秒，21项新增检查及两条公共Study消费通过；原版MatterAI实际0.18宿主与一次mlcc_list_tasks通过。MCP/registry/Python绑定一致，121个发布/安装文本文件直接一致。见[总验收](../workspace/reports/p5-study-delivery-v001/acceptance.json)。

本次补齐现有`deliver-properties --p5`的Study级消费，传递保存的Born、Γ力常数、电子/离子/总介电张量，绑定父Study/Model、原子顺序、单位及原生任务来源。可选源缺失时结果显式null并列原因；数学正例仍是software_math_only。没有新建runner、主控或同义后处理入口。

跨P7固定胞力与Berry NSCF比较物理方法身份，各自数值协议/缺项单独保留；不要求算法控制机械相同，也不据此判精度。现有单一Born位移系列仍保持其共同数值协议。

原生P7方法读取由job198通过9项定向检查及两项实际未提交输入审计，旧5项Γ数学测试未重跑。P7只有两项输入任务，完整力集合缺15项；diag、显式电荷与赝势处理等缺项保持，不产生原生Γ。原生Γ生成分支已接入来源读取，但没有真实完整力集合的端到端验收。

电子epsilon_infinity的原生producer仍未确认。Study交付拒绝未经定义的原生电子来源，当前完整电子/总介电消费只有明确数学产物证据；真实源缺失不补零、不隐式换引擎。

验收协议：[P5来源/Study合同](p5-v018-study-delivery-contract.md)、[安装消费协议](../workspace/reports/p5-study-delivery-v001/protocol.md)、[P7来源证据](../workspace/reports/phonon-gamma-native-source-v001/acceptance.json)。

真实CZO交付复用197/188，保留SCF177/178与NSCF180–185的原生任务记录、60列Born缺失及介电null。完整数学Born/Γ/电子/离子/总介电张量与197保存产物一致，未重生成。错误单位/形状、错Study/model/方法、跨来源及错误嵌套产物按新增路径拒绝。原始缺项结果见[真实Study交付](../workspace/reports/p5-study-delivery-v001/installed-199/real-czo-delivery.json)。

本切片无新增DFT、MD、训练、材料温度矩阵或MACE误差调查。材料科学/生产资格保持false。下一最小任务为缺陷VBM/静电势原生来源与现有方法合同接线，不等待P5完整材料输入；P5缺项及恢复条件继续保留。旧0.10审批阻断不绕过，0.11–0.16旧软件副本待退役，共享0.9环境和0.15依赖继续保留，本轮没有删除。
