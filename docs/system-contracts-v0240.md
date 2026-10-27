# 0.24.0 系统交付：极化—应变输入、响应与 Study

**2026-10-23原生补证已完成**：实际GPU SCF221/222→gdir1 Berry225/226→首次解析227→公共消费228→父Study229全部COMPLETED/0:0。每项DFT串行单V100/time0，两个SCF均9步电子收敛；实际应变胞、量子、各自电荷和来源已贯通。223报告脚本遗漏task_id的失败保留，224只修报告脚本并复用已存SCF结果。产品源码未改，0.24继续启用、0.23回退，无新发布或宿主复验。分支/gdir2/3缺失，响应仍unresolved/null，科学资格false。见[原生补证报告](../workspace/reports/berry-strain-native-v001/report.md)和[验收](../workspace/reports/berry-strain-native-v001/acceptance.json)。以下04:52段落是原发布时的证据边界。

2026-10-23 04:52：0.24.0 已安装、验收、启用并冻结；0.23.0 为回退版，源码进入0.25.0候选。原版MatterAI宿主通过，七个MCP工具保持原架构；registry、MCP路径与Python绑定一致。发布与安装副本142个文本文件直接比较一致，未使用哈希。

## 本轮交付

1. `create-berry-strain`：复用已有Voigt应变函数，按调用者显式给出的单分量±应变生成子模型、子Study和SCF输入；保持分数坐标、原子ID、元素映射和共同父来源。工程剪切gamma=2epsilon，晶胞按行向量C'=C@F.T变换。
2. `create-berry-strain-nscf`：仅在该应变点自身SCF完成、电子收敛、来源/应变几何绑定一致后，复用既有Berry创建器生成指定gdir的NSCF输入。创建器不提交，DFT资源显式time=0。
3. `polarization-strain`：消费保存的原生Berry记录及显式分支，按每点量子倍数恢复reduced charge；参考胞导数给出proper e，另存两端Cartesian极化差的improper响应。非正交胞gdir为晶格方向，完整列需三个方向；缺方向/分支逐项null，不补零。
4. `deliver-properties --polarization-strain`：绑定父Study，原样传递保存的数值、缺项、单位和来源，不重算响应。

首切片限中性、无外场、nspin1固定占据、非SOC、clamped-ion固定分数坐标。不包含内部离子弛豫、stress-driven d、电致伸缩或全张量科学资格。单分量响应不冒充全张量，零响应也不自动解释为物理不适用。

## 验收证据

| 环节 | 证据与实际终态 | 说明 |
| --- | --- | --- |
| 真实模型输入接线 | v100 job213，COMPLETED/0:0，1秒；6项检查 | 原有20原子CZO模型生成±yy未提交GPU SCF输入；保留time0、INPUT/STRU、映射和来源 |
| 新增来源绑定修复 | job216，COMPLETED/0:0，1秒；4项定向检查 | 子Study显式模型路径、SCF绑定与应变几何；214失败、215修正记录均保留 |
| 响应模块 | 217先通过20项，4项软件替身缺case字段；218仅复查4项，COMPLETED/0:0，1秒 | 共24个受影响检查有通过证据；不重跑公式正例，217仍记FAILED/1:0 |
| 安装副本集成 | job219，COMPLETED/0:0，5秒；10项新增检查及3次公共CLI消费 | 213真实未提交manifest→缺来源响应→父Study；保存数学正例→Study；不重算正例 |
| MatterAI宿主 | 原版宿主通过 | 七MCP声明与一次mlcc_list_tasks调用；没有第二套runner或工具框架 |

所有建模、数值函数和数值检查均在v100 Slurm。非DFT检查使用有限墙钟；没有新增DFT、MD或训练，没有重解析旧Berry输出，也没有重复冻结0.23验收。

完整证据：[发布验收](../workspace/reports/polarization-strain-integration-v001/acceptance.json)、[主线审查](../workspace/reports/polarization-strain-integration-v001/review.md)、[模块验收](../workspace/reports/polarization-strain-v001/acceptance.json)、[宿主记录](../workspace/reports/polarization-strain-integration-v001/matterai-headless-session-v0240.json)。接口和物理定义见[0.24合同](p5-v024-strain-response-contract.md)。

## 保留的真实缺口

现有CZO结果只是未提交应变输入；实际应变SCF/Berry源、物理分支连续性、绝缘路径、应变步长和电子精度尚未验证。完整非零响应正例明确为software_contract_only，不能称CZO/BTO压电结果。scientific_qualification、production_qualification、full_tensor_qualified为false，无产品目标仍design_assessment=not_assessed。

P5完整原生Born、Γ力集合、电子介电来源与relaxed-ion响应继续未完成。MACE/CZO应力差、MD113和P4/FNV不回到本轮主线。下一步按原P5清单审查就绪来源/响应依赖，不重复本轮检查或为材料数值过线追加计算。旧软件副本待按已有退役规则处理，本轮未删除任何旧版本或科学证据。
