# 0.25.0 系统交付：固定胞弛豫来源与后续任务

2026-10-23：0.25.0已完成v100验收、安装及原版MatterAI宿主检查，启用冻结；0.24.0为回退版，源码进入0.26候选。registry、MCP入口和Python绑定均为0.25，发布与安装的145个文本文件直接比较一致。沿用既有七MCP和Slurm架构。

## 本轮功能

- **显式离子约束**：既有`create-abacus`的relax请求按稳定原子ID给出Cartesian自由分量，再映射为ABACUS按元素分组的`m`标记。中性固定胞、新CG实现；至少一个自由度。ABACUS3.10.1新实现的力和位移掩码存在基底差异，因此部分轴冻结只支持正对角、轴对齐的正交胞，整原子自由/冻结支持一般固定胞。不自动切换优化器或解释约束。
- **原生停止与几何绑定**：解析实际输出INPUT中的控制、电子/离子收敛和结束标志。收敛判据为自由分量最大绝对力，保留原有原子力范数诊断。未收敛时最终STRU可能是尚未评估的下一构型，即使与最后快照相同也不可晋升；迭代耗尽和电子失败分别记录。
- **保存源晋升**：`derive-relaxed-structure`核对保存终态、方法、原子映射、固定胞、冻结坐标及最终结构，生成明确新ID的Model/Study。保留相/掺杂、约束、原子谱系和job/result/native来源；不推断弛豫后的相或材料资格。
- **后续输入**：`create-relaxed-scf`调用既有普通SCF或Berry参考SCF创建器，保留弛豫依赖，生成新的SCF输入。既有依赖读取器可消费该来源。不会复用relax电荷或提交计算；Berry资格不满足时透传原始拒绝。

完整输入、接口和物理边界见[固定胞合同](p5-v025-fixed-cell-relax-contract.md)。

## 实际证据

| 环节 | 原生终态与检查 | 范围 |
| --- | --- | --- |
| producer230 | COMPLETED/0:0，4秒，18项受影响检查 | 16个新约束/停止检查及2个相关旧行为；历史GPU Ni33只在新副本重解析一次 |
| bridge231 | COMPLETED/0:0，2秒，18项新增检查 | 真实保存终态→新Model/Study→SCF输入→依赖消费；保留Ni的Berry原始拒绝 |
| installed232 | COMPLETED/0:0，3秒 | 新安装副本首次执行两个公共CLI，读取同一保存源；不重跑模块测试或原生解析 |
| 原版MatterAI | 通过 | 0.25 Bundle和七MCP声明、一次任务列表调用；没有执行计算 |

所有建模、数值处理和数值检查均在v100 Slurm。本轮没有新增DFT、MD或训练，没有重算Ni33、CPU Berry、原生应变或冻结版本。非DFT软件作业请求1CPU/2GiB/10分钟/no-requeue，调度分配2逻辑CPU，计算线程保持1。

Ni33原生是历史四原子、全自由、固定胞GPU工程任务，五离子步且电子/离子均收敛，native自由分量最大力约0.01092946eV/Å，小于原阈值0.02。其原始文件、结果和历史30分钟预算原样保留；不能改写为当前无限时协议。历史Study与Model的相名称文案不同，本轮新建caller-supplied父Study，明确绑定同一已有Ni fixture和模型原标签，记录两种历史文案，没有修改材料选择或声称job33已有Study身份。

本地安装首次缺少已有setuptools构建工具的搜索路径，失败日志保留；显式加入现有build-tools路径后安装成功。已成功的宿主检查直接复用，没有因此重跑科学或数值验收。

证据：[发布验收](../workspace/reports/fixed-cell-relax-integration-v001/acceptance.json)、[主线审查](../workspace/reports/fixed-cell-relax-integration-v001/review.md)、[producer230](../workspace/reports/fixed-cell-relax-producer-v001/checked-230/acceptance.json)、[bridge231](../workspace/reports/relaxed-structure-bridge-v001/acceptance.json)、[installed232](../workspace/reports/fixed-cell-relax-integration-v001/installed-232/acceptance.json)。

## 未完成的边界

真实正例只证明历史全自由Ni保存源链。原生部分约束弛豫、绝缘材料弛豫后Berry正例、可变胞、NEB和完整relaxed-ion响应尚未验证或未实现；不能把软件测试写成这些功能的原生资格。完整Born、原生Γ力集合、电子介电来源及物理分支仍有缺项。P4修正、材料势生产资格、P6/P8/P11继续保留未完成状态，整体P0–P12未完成。

MACE/CZO约2.708GPa差异继续后置：同模型接口和参数传递已有证据，保持该材料候选科学未资格，不为数值过线重复选势、加密或训练。下一步审查一个就绪的P5.04/P5.07来源合同，复用本轮桥，不重造流程。科学及生产资格仍为false，无设计指标时design_assessment=not_assessed。旧软件副本待按已记录的退役规则处理，本轮未删除历史证据或共享环境。
