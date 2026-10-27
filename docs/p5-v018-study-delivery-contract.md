# 0.18候选：P5来源与Study最终交付

2026-10-22 22:42更新：本合同已由198原生来源reader、199安装Study消费及MatterAI宿主验收，0.18启用冻结、0.17回退、源码0.19候选。以下所有权为该切片实施分工，已完成并交回root；科学源缺项不变。见[交付与边界](system-contracts-v0180.md)。

本切片补现有 `deliver-properties --study ... --p5 request.json --output ...` 路径，消费已保存的Born、Γ、电子、离子和总介电产物。原 `--tasks` 电子性质交付保持兼容，两种输入互斥；不新增第七个同义后处理命令，不重做0.17六入口验收，不生成DFT、MD或训练任务。

## 方法与来源合同

跨P7力与Berry响应匹配父Study/Model、稳定atom_id顺序、胞、单位、电学及力学边界。物理方法比较包含引擎及版本、基组类型、XC、赝势身份与处理、自旋/SOC/初始磁态、占据类型、展宽和净电荷；未知显式字段不能静默丢弃。赝势资格标签不属于物理身份。

方法标签、截断、k网格/shift、nbands、scf_thr/nmax、mixing与pw_diag_thr作为各来源数值协议原样记录，不机械要求SCF/NSCF角色间相同。数值协议不同或未记载不自动等于不同哈密顿量；也不能据此授予目标量收敛。缺字段明确列出，不能从另一模块复制或猜引擎默认值。P7自身KPT可提供其网格和shift，未显式记载的diag继续缺失。所有原始方法记录保留。

已有完整张量可传递，但software_math_only不得混入native_source_bound，软件数学例不得改变材料科学状态。原生Born来源追溯到保存的188响应及真实任务/SCF记录；真实任务原生job、终态、退出码保留。未解分支、缺Born列、缺力集合或电子producer分别逐项保留，不能用零补齐。完整力集合不存在时不得输出原生Γ矩阵。

## 所有权

- root：物理合同、dielectric_response.py共享方法比较、CLI、文档/计划、集成验收。
- Luna p5_study_delivery：property_delivery.py及新增test_p5_property_delivery.py；不改共享CLI或Γ适配器。
- Luna p5_binding_review：新增test_p5_method_binding.py与只读审查。
- 既有执行聊天“推进 MLCC H0 闭环实施”：phonon_gamma.py、test_phonon_gamma.py及phonon-gamma-native-source-v001报告独占。

## 本轮验收边界

复用installed197完整数学产物和真实CZO缺失产物、188/192及既有P7文件。只验证新增Study消费/方法来源路径。v100 Slurm CPU后处理预算1CPU、2GiB、2分钟，no-requeue；不提交实际DFT。数学输入检查传递完整张量和明确软件来源；真实CZO交付必须保留60列Born缺失、介电null和原生job来源。错Study/model/物理方法、错来源或交叉产物应拒绝。

电子epsilon_infinity没有本站ABACUS3.10.1已确认的原生producer；恢复条件是获得明确可执行的原生路线及来源合同，本轮不建空壳、不再重复源码调查、不升级换引擎。完成可实现的来源与Study接线后推进就绪的缺陷静电势/VBM来源，不等待完整材料张量或误差过线。
