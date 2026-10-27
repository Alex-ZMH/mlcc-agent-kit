# MLCC 0.22.0：显式区域势差诊断

2026-10-23。0.22.0经模块job209、安装job210及原版MatterAI宿主验收后启用冻结，0.21保留回退，源码进入0.23候选。这一切片交付实际可运算的领域函数和来源传递，没有新增DFT、MD、训练或材料精度优化。

## 运行能力

`potential-alignment --request ... --output ...`消费同胞、同网格、显式选区的host/defect电子势能记录。三维半开整数箱取并集，重叠点只计一次；支持完整非正交网格基矢，不做插值、平移、重采样或自动找平台。完整输入计算区域内`mean(Vdefect−Vhost)`，单位eV，并输出样本数、双方均值、差值最小/最大、总体标准差及峰峰差。

来源检查绑定各自同一task的保存电子与势、方法、模型/Study、原子谱系、调度完成和原始文件；host50电子不能凭同模型身份替代host205同task电子。原生cube和能级解析器未重复执行。显式缺陷描述支持已有vacancy/substitution/interstitial谱系校验，不把host/defect原子数不同当作错误。

若host VBM可用，输出`candidate_host_vbm_on_defect_gauge_eV = VBMhost + ΔV`候选；所有方法、q、原始零点及选择依据保留。`deliver-properties --study ... --potential-alignment ... --output ...`消费保存诊断并绑定defect Study，安装消费不重算势差。

电子势能差不等于现有形成能接口中的`potential_alignment_eV`修正能量，选区也不自动建立物理远场。q>0表示移去电子，本功能不乘q，不生成FNV/eFNV，不把候选VBM写成科学对齐值。未来校正须统一模型长程势、介电与alignment-like项，避免重复计数。[物理合同及依据](p4-v022-potential-alignment-contract.md)，[Kumagai–Oba原始方法论文](https://doi.org/10.1103/PhysRevB.89.195205)。

## 新增验收

| 环节 | 实际终态 | 验收范围 |
| --- | --- | --- |
| 领域函数/来源 | job209 COMPLETED/0:0，3秒 | 32项新检查；完整数学运算与真实保存源缺项，公共CLI一次 |
| 安装副本/Study | job210 COMPLETED/0:0，4秒 | 6项新交付检查；原生缺项和209保存的完整数学结果各消费一次 |
| 原版MatterAI宿主 | passed | 0.22 Bundle、七MCP声明及一次只读任务列表调用，registry/MCP/Python绑定一致 |

209和210均在v100 Slurm请求1CPU、2GiB、2分钟、no-requeue；调度器按现有节点配置分配2个逻辑CPU。本切片为保存源后处理和软件数值检查，无需GPU内核。209初次PENDING/InvalidAccount原始观测保留，随后同一job正常启动完成，没有重提或重试。

真实来源为205宿主静电势及同task电子（206保存）和121缺陷电子（200保存）。没有真实缺陷势，也没有用户选定区域；结果准确保留`missing=[defect_potential, selection]`。完整软件样例产生ΔV=1eV、候选VBM=−1.5eV，均明确software_contract_only。210消费该实际保存产物并保持字段一致，不重新运行差值函数或把样例当材料结果。

[模块验收](../workspace/reports/potential-alignment-v001/acceptance.json)、[安装验收](../workspace/reports/potential-alignment-integration-v001/installed-210/acceptance.json)、[正式验收](../workspace/reports/potential-alignment-integration-v001/acceptance.json)。发布与本地安装134个文件直接文本一致，无哈希。主线与Luna分别静态审阅，未发现阻塞运算或传递的问题；未来大网格可复用已转换数组减少重复内存处理，本轮没有扩大重构。

## 未完成范围与后续

真实区域势差、物理对齐、aligned VBM、修正能量、FNV/eFNV和带电形成能仍为空；native_alignment_accepted、科学/生产资格均false，设计判定not_assessed。此次工程验收不建立完整双native势实验或材料资格。

下一步审查带电修正producer的独立物理合同及就绪依赖；缺原生网格、显式选区、介电/模型电荷或化学势时保留来源缺项，不用重复null包装代替功能。P5仍缺完整Born、Gamma力和电子介电源；只读复核未发现无需新输入即可恢复的新来源接口，因此保留其优先级与实际缺口。元素参考相/μ、BTO相/掺杂不代选。

0.21为当前选定回退。0.10删除审批阻断不变，0.11–0.20旧软件副本待退役，本轮无删除；共享0.9环境、0.15依赖/构建工具及科学证据保留。
