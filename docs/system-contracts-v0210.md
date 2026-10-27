# MLCC 0.21.0：化学参考来源与参数交付

2026-10-23。0.21.0通过v100模块207、安装208和原版MatterAI宿主后启用冻结；0.20保留回退，源码0.22候选。此次补齐参考来源和下游传递，不新增DFT、MD或训练。

## 本次实现

- `chemical-references --request ... --output ...`读取明确声明的host、elemental、competing来源。复用保存的电子结果和既有来源绑定，保留TaskRecord、模型/Study、原子、方法、Slurm终态和原生文件路径，不重解析能级。
- 明确区分整胞总能、每式量能量和元素每原子化学势。只有所有元素满足`cell_composition = formula_units × formula_stoichiometry`的正整数关系才归一化；分子元素参考也按元素原子数计算μ。
- 检查共同物理方法及共同元素赝势；各相原始`method_set`、磁态和数值协议分别保留，共同参考组另记`reference_method_id`。相间参数不同不会被宣称为精度等价。
- 已选来源齐备时调用现有化学势稳定域函数；μ点必须显式提供并通过可行性判断。没有新增优化器、自动选相或自动选点。
- `deliver-properties --study ... --chemical-references ...`交付现有Study；`neutral-formation --chemical-reference-delivery ...`只接收绑定同一host的真实点。完整数学样例只输出`mathematical_chemical_point`，不会进入原生中性形成能。

## 验收证据

| 环节 | 真实终态 | 结果 |
| --- | --- | --- |
| 新来源模块 | job207 COMPLETED/0:0，2秒 | 18项新增检查；公共来源CLI执行一次 |
| 安装副本消费 | job208 COMPLETED/0:0，4秒 | 11项共同组/交付/CLI检查，真实Study消费已保存集合一次 |
| 原版MatterAI宿主 | passed | 0.21 Bundle、七MCP声明及一次`mlcc_list_tasks`调用；registry/MCP/Python一致 |

207和208均请求1CPU、2GiB、2分钟，no-requeue；Slurm按现有SMT配置分配2逻辑CPU。任务仅做来源绑定、数值后处理和软件验收，无需GPU内核。所有这些数值工作均在v100 Slurm运行，本地只安装、控制和查看证据。Slurm accounting未启用，因此终态使用`scontrol show job`原生输出。

真实来源为已有CZO Pnma宿主job50和job200保存的电子JSON。Ca4Zr4O12归一为4个CaZrO3式量：整胞能量−14816.896622614182 eV，每式量−3704.2241556535455 eV。208完整保留207的集合和host来源，没有重复归一化、原生解析、旧DFT或冻结版本测试。

[模块报告](../workspace/reports/chemical-reference-native-v001/report.md)、[安装验收](../workspace/reports/chemical-reference-integration-v001/installed-208/acceptance.json)、[正式验收](../workspace/reports/chemical-reference-integration-v001/acceptance.json)、[物理合同](p4-v021-chemical-reference-contract.md)。发布与本地安装131个文件直接文本一致，未使用哈希。独立只读审查未发现阻塞参数传递的问题。

## 保留的缺项

Ca、Zr、O元素参考相、竞争相集合和μ点均未选择，native region/point/formation保持null。只有软件数学样例验证了完整区域/点算法接口；没有完整真实相集合的科学验收。当前固定几何SCF及共同字段检查不建立相稳定性、生产精度或有限温度自由能资格。科学/生产资格false，未给产品目标，设计判定not_assessed。

宿主/缺陷势对齐、介电屏蔽和带电修正、完整Born、原生Γ力集合及电子介电仍未完成。下一项先审查现有来源和可独立推进的接口；缺选相不引出材料搜索或自动追加DFT。已有材料精度差异按用户要求后置。

当前回退0.20；0.10旧删除审批阻断保留，0.11–0.19旧软件副本待退役，本轮没有删除。共享0.9环境、0.15依赖/构建工具和所有科学证据继续保留。
