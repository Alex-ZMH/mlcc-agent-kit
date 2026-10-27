# MLCC 0.26.0 saved relaxed strain 系统契约

2026-10-23：0.26.0 已启用冻结，0.25.0 为回退版本，源码进入 0.27.0 候选。保存的弛豫 ± 应变来源、约束标签、响应消费和 Study 数据传递完成软件范围验收；不代表材料响应科学资格。完整记录见 [发布验收](../workspace/reports/relaxed-strain-integration-v001/acceptance.json)。

## 适用范围与边界

0.26.0 扩展既有 Berry 应变 producer/consumer 和 v1 manifest、binding schema，不新增 runner 或独立框架。每个 saved relaxed response manifest 必须包含同一未应变父 Model/Study 下、同一 Voigt 分量的两个非零且等幅反号应变点。一个 manifest 只能使用一种机械边界：

- `relaxed_ion_fixed_cell`：`relaxation_scope=all_internal_dofs`，响应类型为 `relaxed_ion_stress_form_piezoelectric_e`。`relaxed_ion_response` 只用于描述该全自由边界。
- `constrained_ion_fixed_cell`：`relaxation_scope=selected_internal_dofs`，响应类型为 `constrained_ion_stress_form_piezoelectric_e`。结果必须单独放在 `constrained_ion_response`，不得称为完整 relaxed-ion 响应。

原有 `clamped_ion_fixed_fractional` 分支继续保持固定分数坐标和无弛豫约束。all-free 与 partial 不能混合，partial 结果不能提升为全自由离子响应。

## 来源绑定与参数传递

每个端点必须引用已经存在的 `relaxed_structure_bridge`。bridge 必须来自已接受的 `derive_relaxed_structure` 结果，并满足实际收敛、几何可提升、固定胞和冻结分量检查。producer/consumer 应保留并传递：

- `mechanical_boundary`、`relaxation_scope`；
- `pre_relax_model`、`pre_relax_study`；
- bridge 的绝对路径；
- bridge 中完整的 `relaxation_source`，包括原生任务、结果、方法、作业号和实际约束；
- 规范化后的 `ionic_constraints`；
- promoted child 的 Model/Study 身份和响应专用任务绑定。

共同父 Model/Study 必须与端点的原子 ID、元素、净电荷、相/掺杂、case 和父身份一致。应变构造阶段保持原子分数坐标，bridge 的最终分数坐标可以改变，但最终胞必须等于该点的预弛豫应变胞。

两端必须使用相同的原子选择、移动标志、坐标基、弛豫控制、力指标、力阈值、物理方法、赝势和 k 点规则。约束的来源标记属于 provenance，不构成新的物理条件；比较时应保留实际约束字段而忽略来源标记差异。阶段专用的 SCF/relax 输出控制可以不同，但不得改变物理方法身份。两个端点的 source task、bridge 和响应任务必须可追溯且不能互相冒充。

producer 为每个已提升端点创建新的 Berry reference SCF，再绑定既有 response task；不得修改源 Model、Study、bridge 或历史任务。缺失 bridge、来源不收敛、几何不可提升、端点不成对或方法/约束不一致时，应保留原始错误并拒绝创建，不自动弛豫、重试、调参或补造来源。consumer 继续复用 saved-source 校验结果，不重新解析 native 输出。

## 科学资格边界

0.26.0 的软件 B 切片只验证来源绑定、all-free/partial 区分、±应变选择、参数传递、缺失分支和失败状态。数学 fixture 必须标为 `software_contract_only`，不能成为 native、scientific 或 production 结果。缺失 Berry 方向、显式物理分支或连续性证据时保持 `null`/`unresolved`，不补零。单分量结果不能宣称完整张量，也不能据此给出材料设计结论。

A 是独立的 CZO20 单胞工程验证链，不是 B 的 ±应变端点，也不能建立应变导数。原生 job237 已完成 `0:0`，但电子收敛后在 `relax_nmax=8` 达到离子迭代上限，`geometry_promotable=false`；job240 已解析并记录冻结自由度、未评估的下一几何和 blocked dependency。因此该链没有继续创建 fresh SCF/Berry，且 scientific/production qualification 均为 false。详见 [A237/A240 验收记录](../workspace/reports/constrained-relax-native-v001/acceptance.json) 和 [A240 blocked 记录](../workspace/reports/constrained-relax-native-v001/blocked-relax-240.json)。

## 验收证据与未完成范围

consumer239 为 `COMPLETED/0:0`：37 个不同用例、39 次执行，其中13个新增用例。选择器误匹配目录，额外执行24个旧用例并重复其中2项；偏差已记录，不再重跑。它验证软件契约和 partial 标签，不建立原生 ± 应变资格。详见 [consumer239 汇总](../workspace/reports/polarization-strain-relaxed-v001/acceptance.json)。

producer 的10个不同增量用例全部已有通过证据：241通过4项、其余6项因夹具缺目录失败；242修目录后通过4项，余2项暴露 manifest 缺弛豫范围字段；243补字段后仅重验这2项并通过。已通过项直接复用。主集成还修复了约束 origin 被二次当作物理条件比较、配置与原生方法记录格式不同造成误拒绝的问题。仅 `create_relaxed_scf` 在该 producer 软件测试中被 stub，保存来源校验和 producer 本身实际执行；不冒充完整原生输入正例。更早235取消及236/238错误解释器调用均保留，238重复错误调用属于执行偏差。见 [producer验收](../workspace/reports/berry-strain-relaxed-producer-v001/acceptance.json)。

安装副本 job245 `COMPLETED/0:0`、3秒，复用239保存的 partial 请求，通过两个公共 CLI：响应消费、父 Study 交付。缺失方向仍为 `unresolved`，没有补造数值。244因报告脚本漏传 CLI `--output` 在分析前失败，修正后才执行245。原版 MatterAI 宿主通过，registry/MCP/Python 均绑定0.26；145个发布/安装文本文件直接比较一致。初次宿主检查脚本相对路径错误已保留，改绝对路径后通过；未重装或重跑数值检查。

完整原生受约束/全自由度 ± 应变弛豫→SCF→Berry 正例、物理分支、完整 Born/Γ/电子介电、可变胞和 NEB 仍未完成。A237不收敛不触发重跑或参数优化；后续按系统缺失路径选择独立开发，不以验证材料精度阻塞版本推进。

相关定义见 [P5-v026 relaxed strain contract](p5-v026-relaxed-strain-contract.md)；0.25 原生 A 协议见 [P5-v025 native strain protocol](p5-v025-native-strain-protocol.md)。
