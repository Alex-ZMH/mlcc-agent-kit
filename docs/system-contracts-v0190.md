# MLCC 0.19交付：缺陷电子参考与Study消费

2026-10-22 23:39。0.19已验收启用冻结，0.18回退，源码0.20候选。MCP、registry和Python均绑定0.19，原版MatterAI宿主与一次mlcc_list_tasks通过。124个发布/安装文本文件直接一致。见[总验收](../workspace/reports/defect-reference-integration-v001/acceptance.json)。

新增 `deliver-properties --defect-references`，消费保存的ABACUS电子结果并交付到缺陷Study，没有新增主控或runner。请求显式绑定宿主电子JSON、缺陷电子JSON与缺陷model.json，保存父子模型、原子谱系、方法、数值协议、单位、原生job与终态。VBM/CBM、采样KS gap和SCF费米能保留各任务自己的能标，带电采样能级不称为对齐后的宿主VBM。

| 证据 | 验收范围 | 原生终态 |
| --- | --- | --- |
| 200 | 用冻结0.18既有电子parser首次读取已完成50/121，保存两份JSON | COMPLETED/0:0，记录0秒 |
| 201 | 新参考模块14项检查及5组真实保存源消费：50/121、50与75/76/77/80 | COMPLETED/0:0，记录0秒 |
| 202 | 0.19安装副本5项新增Study/CLI检查及真实50/121公共交付 | COMPLETED/0:0，3秒 |

三项均为v100 Slurm后处理/工程验收，请求1 CPU、2 GiB、2分钟、no-requeue，实际分配2逻辑CPU。未新增DFT、MD、训练，没有重复已通过的旧解析或模块验收。有限时间只用于这些非DFT作业。201由原实施窗口交付，主线审查后直接复用；202核对能级值精确传递、原生50/121、Study与模型、方法比较、null及未资格标记。

方法比较只声明列出的已记录字段是否一致，并保存未评估字段。50/121方法标签和已列物理字段相同，Berry输出配置记录有差别；四个带电任务的截断/网格/SCF阈值差异保留。不把这一比较当完整方法等价或精度资格，不改写既有中性能量链验收。

现有源没有静电势网格、公共势零点、化学势、介电屏蔽和修正来源。aligned_host_vbm_eV、potential_alignment_eV、FNV_eFNV_correction_eV与charged_formation_energy_eV均null。总能量只作总能量来源，电荷密度不能替代电势。原生带电形成能gate未开放，数学形成能函数未用于绕过缺源。

scientific/production qualification为false，无设计目标为not_assessed。完整Born、原生Γ力集合与电子介电producer仍未完成。下一最小切片是ABACUS3.10.1精确版本的静电势输出定义及现有writer审查，先确认内容/单位/网格/零点，再确定最小source adapter；本次不追加材料计算或精度矩阵。

使用合同见[P4合同](p4-v019-electronic-reference-contract.md)，真实产物见[Study交付JSON](../workspace/reports/defect-reference-integration-v001/installed-202/defect-reference-delivery.json)，模块证据见[201验收](../workspace/reports/defect-electronic-reference-v001/acceptance.json)。MACE/CZO误差继续后置。旧0.10删除审批阻断未绕过，0.11–0.17旧软件副本待退役，本次未删除；全部科学证据、共享0.9环境与0.15依赖/构建工具保留。
