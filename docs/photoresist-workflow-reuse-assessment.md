# 光刻胶系统工作流对 MLCC 的复用评估

日期：2026-10-21。性质：基于本地源码和已有验收记录的设计评估；不是移植完成记录，也不改变 P0–P12 的执行状态。

## 1 结论与当前进度

可以增量复用其工作流设计。优先吸收“明确科学输入 → 持久任务 → 确定性计算 → 来源可追溯的结果 → 科学验收 → 下游消费”的方法，接入 MLCC 现有执行层。不能整体替换 MLCC 主控，也不能把光刻胶的分子参数化、固定拓扑 MD 或工艺模型直接视为 MLCC 的科学能力。

MLCC 已有可复用基础：matterai.bundle.v2 Bundle 0.3.0、四项 Skill、七个 MCP 工具、可读 JSON 任务记录、Slurm runner、真实 VASP 工程闭环，以及 ABACUS Ni jobs 32/33/34 工程小闭环。当前缺口仍是 P4/H1 的截断能/应力与目标方法资格、显式生产引擎切换，以及后续性质和合格势 MD；复用工作流不会自动填补这些科学缺口。[当前台账](h1-execution-ledger.md)、[阶段状态](../plans/stages.json)。

CaZrO3/Pnma 是指定科学验证案例，不是通用系统的材料默认值。通用系统须保留正常性能、方案比较、给定规格后的适配评估及条件性机制分析；铁电/顺电/非铁电分流及第二部分铁电计算继续按现行任务推进。当前没有产品合格线，`design_assessment=not_assessed` 不妨碍系统建设和科学计算。

## 2 本次检查的是哪套工作流

源码实际根目录为 `Photoresist-agent-kit-main/Photoresist-agent-kit-main`。其中需要区分两层：

1. 通用开发流程：场景与架构决策 → 用户任务/可观察验收 → Agent/Skill/Tool 合同 → 最小真实闭环 → 评测/交付。这与 MLCC 已有 P0–P12、harness 和分工基本一致，可用于改善后续执行任务包，不需要重做 H0。
2. 光刻胶产品运行流程：`bundles/arf-car-computation` 当前 manifest 为 **0.3.7**，`mcpServers` 为空；公开入口主要是脚本与持久任务，独立 dispatcher/Slurm Worker 推进计算。旧 MCP 材料不能当成这一版本的当前架构。MLCC 已验证的 MCP 接口仍保留。

依据：[开发指南](../Photoresist-agent-kit-main/Photoresist-agent-kit-main/docs/agent-development-guide.md)、[产品 manifest](../Photoresist-agent-kit-main/Photoresist-agent-kit-main/bundles/arf-car-computation/bundle.json)、[产品 Agent](../Photoresist-agent-kit-main/Photoresist-agent-kit-main/bundles/arf-car-computation/agents/arf-car-computation/AGENT.md)、[部署说明](../Photoresist-agent-kit-main/Photoresist-agent-kit-main/bundles/arf-car-computation/deployment/README.md)。

## 3 最有价值的复用项

| 光刻胶系统的设计 | MLCC 中的具体用法 | 接入阶段与限制 |
| --- | --- | --- |
| 薄 Agent，按意图读取相关 Skill，确定性计算交给领域函数 | 四项现有 Skill 负责方法选择与解释；晶体生成、DFT 输入/解析、势转换和统计由 Python 函数执行 | P0/P2 及后续各阶段；不新增第二套 Agent 主循环 |
| 输入只表达科学对象、问题和条件；已有对象按来源 ID 引用 | Study 明确材料/相、目标、工况、所选任务、可空的设计规格；模型/结果通过 model/version、source_task 和角色引用传递 | P0.08、P2、P12；不由语言模型复制坐标、力数组或更改结果标签 |
| 同一持久任务可查询、补充输入、续接、取消和收集 | 在现有 TaskRecord 上保存所选任务与依赖、阶段产物和事件；重复“继续”先读已有任务，已提交任务不再次提交 | P0/P4；续接是继续未完成步骤，不等于失败自动重跑，也不宣称数值 checkpoint 恢复 |
| 先检查输入与能力，再明确执行；可以在指定阶段停止 | 建模、输入准备、提交和后处理分别有可见产物；请求只到建模时不越级提交 | P2–P4/P9–P11；延续已给授权，不反复索要同一确认，不将这次评估解释为计算授权 |
| 区分执行回执、科学 QC 和结果可消费性 | 保存调度状态、数值收敛、科学有效性、模型/方法资格及设计判定；下游逐项检查所需结果是否有效 | P4–P12；已有三层验收继续独立，不压成单个 `consumable` 或 `success` |
| 从同源模型、参数和轨迹形成可追溯交接 | DFT→MD 保留原子映射、方法、单位、势资格和适用域；只有科学条件相容的结果可传递 | P9.01–P9.13、P10.01、P12.01–P12.02；不混合 VASP/ABACUS 原始训练标签 |
| 对已有合格数据追加分析，不重复启动动力学 | 用已保存轨迹/DFT 输出新增 observable 或重新统计；记录新分析版本、源任务、窗口和定义 | P10–P12；源轨迹不支持目标量时明确缺口，不能靠改温度/材料字段补足 |
| 保留独立样本及失败记录，公开有界结果索引 | 为构型、温度、随机种子和分析建立清楚索引，输出汇总与按需详情，保留失败/排除原因 | P2.09、P10.04/P10.10–P10.13、P12.10；样本数和收敛协议按 observable 确定，不照搬统一“三副本” |

其中，单位/映射、来源追踪、失败保留、阶段验收在现行 MLCC 计划中已经存在。价值主要在于把这些要求实现为可靠的任务交接与用户入口，不能把文字相似误报成新能力已经完成。

还需区分合同外壳和科学内容：例如其 `parameterized-model-ensemble.v2` schema 只约束 `data/qc/provenance/limitations/consumable` 等外层字段；具体谱系约束由领域代码完成。MLCC 应定义周期晶胞、站位/原子映射、缺陷电荷态、方法集和目标物理量的实际字段与核对规则，不能只复制 schema 名称。分析对象也应按登记的相、位点、缺陷、界面层或极化区域选择，避免用模糊名称混合不同对象。

## 4 需要保留的差异

### 4.1 执行层

- **不替换现有 MCP。** 光刻胶的“直接脚本调用”是它的交付选择。MLCC 继续使用薄 MCP → 领域函数/现有 runner → Slurm；新增领域方法可以共用普通函数，没有必要同时维护两套提交器。
- **不引入自动重试/修复。** 光刻胶 Agent 允许某些数值错误最多两次新任务修复重跑（减小时间步、延长平衡）；驱动另有最多两次副本内部恢复（增加 NVT、减慢 NPT 耦合）。dispatcher 对特定 wrapper 失败设置了 3 次重试上限。这是不同层面的机制，均与 MLCC 项目规则冲突。借用状态/回执设计时必须去除这些策略。显式选定的预平衡协议可以作为新任务输入，不能在失败后悄悄改协议。
- **保存状态与实时查询分开。** 光刻胶公开 `status/list/collect` 主要读持久记录；MLCC 的 `query` 必须继续查询实际 Slurm。界面应标明调度查询时间与保存时间；历史快照不能冒充实时状态。
- **暂不搬 dispatcher/常驻 Worker。** 当前架构明确使用普通领域函数和轻量记录，不建消息队列或自动恢复服务。先完成单个有来源的科学闭环。以后确有脱离会话的多步骤调度需求时，再单独设计最小服务；不能顺带部署光刻胶的 host service、资源默认值或凭据。
- **数据位置沿用 MLCC。** 科学模型、任务、轨迹和结果都在 `workspace/`，不把对方 Bundle 内 `outputs/` 目录惯例带入可交付包。路径/解释器/MPI/资源继续来自本站配置；无哈希缓存、引擎替换或直接 SSH 数值进程。
- **重复继续按明确任务 ID 处理。** 光刻胶代码另有相同请求去重、部分内嵌分析结果复用，以及用 SHA-256 为工作区注册记录命名；后者不是科学内容缓存，但也没有必要搬入。MLCC 继续使用可读 ID/版本和原始回执，显式引用已有任务，不增加内容去重或结果缓存。

### 4.2 科学层

| 光刻胶内容 | 可以借用 | 不能等同为 |
| --- | --- | --- |
| 有机分子建模、PACKMOL、GAFF2/RESP、拓扑导出 | 原子身份、组分/电荷闭合、来源和格式转换核对思路；未来选定高分子分支的有限参考 | 陶瓷/金属/异质界面的合格势，或可极化铁电模型 |
| Amber/LAMMPS 能量与力的转换一致性 | 对同构型、同模型做导出前后的一致性检查 | DFT 与经验势应数值完全一致；跨赝势裸总能可直接比较 |
| 固定拓扑 MD 的扩散、结构、温度扫描 | 样本管理、平衡/生产段划分、统计不确定性和分析再利用 | 极化翻转、介电张量、缺陷电荷转变、断键/反应或器件寿命 |
| 净电荷/离子配方与分子电荷拟合 | 明确电荷约定及全体系一致性 | 带电周期缺陷的电子库、FNV/eFNV 修正、化学势稳定域或费米能级求解 |
| PMF、KMC、PEB/显影等模型 | 显式参数、来源与适用范围的交接方式 | MLCC 的 NEB 势垒、铁电相场、FEM 或完整器件多物理场 |
| 某些固定正交盒分析路径 | 已验证范围内的后处理模式 | 任意三斜晶胞、变胞 NPT、带真空界面的通用分析器；这些须单独适配和验收 |

“能够运行/参数项齐全”与“能可靠预测选定材料和 observable”始终分开。正常性能和设计有利结果也是科学输出，不以是否出现失效作为工作流的完成条件。

## 5 对现有任务的增量接入建议

不增加一轮从零开始的 P0–P12。以下 R1–R5 是实施建议编号，不是已立项或已完成的新阶段。

| 建议工作包 | 归入现有任务 | 最小产物与验收 | 时机 |
| --- | --- | --- | --- |
| R1：科学请求与来源合同落地 | P0.08、P2、P12.01–P12.02 | 扩展现有 Study/Task/Result，串起 study_id、case_id、model/version、method_set、depends_on、源任务与条件；用已有 Ni 记录只读演示来源追踪，不改写历史记录 | 当前即可设计/实现；不阻塞 P4 数值资格 |
| R2：单条科学链的持久续接 | P4 基础链 | 先支持“选定模型 → 弛豫 → SCF → 解析/科学验收 → 参数交接”；保存每一步真实产物与 Slurm ID。重复继续不重复提交；失败保留原错误。使用现有 runner，无新调度服务 | 与 P4 适配推进；CaZrO3 数值执行仍等相应资格 |
| R3：把科学分支写成依赖明确的任务组 | P4.18–P4.27、P5/P7、P9.19–P9.21、P10.14–P10.19、P11.18–P11.20 | 缺陷形成能等待参考/化学势/介电与修正证据；铁电 MD 等待极化/场模型资格。相应前置未通过只阻塞相关子任务 | 随已有铁电/缺陷工作包实施；不能被普通 MD 工作流替代 |
| R4：MD 样本与分析交接 | P9–P11 | 原子/类型映射、势资格、时间步/NVE、平衡/生产区间、样本与失败索引、observable 定义、误差和源轨迹引用；追加分析不重跑 MD | 相应 P9 合格势建立后；此刻不直接复制运行 |
| R5：有界结果接口与分层报告 | P12.10–P12.18 | 结果目录/选定指标详情、来源、条件、误差、能力/案例/设计结论；无规格正确输出 not_assessed，正常有效结果不必带损伤才能交付 | 可从现有数据先做，再随各科学链扩充 |

推荐顺序：**保留并完成 P4/H1 现有下一任务，同时增量落实 R1/R2 的合同与续接；按现行科学依赖实施 R3；有合格势后实施 R4；R5 逐批接收真实结果。** 不以开发新调度平台代替 100/120 Ry、应力标定和目标材料方法验证。

目标衔接如下，表示职责关系，不代表所有节点已实现：

```text
用户科学目标 + Study（材料/相/工况/可空规格）
  → Skill 选择实际所需分支（普通/铁电/缺陷/界面等）
  → 普通领域函数生成有依赖、有来源的 Task
  → 现有 MCP / SiteRunner → Slurm 原生作业
  → 原始输出 + 收敛/科学验收
  → 可复用 Result / 模型 / 轨迹 / 参数包
  → 下游所选任务与系统能力、案例、设计三类结论
```

## 6 对铁电与缺陷新增任务的具体帮助

缺陷工作流可借它的“多角色 source 引用”：一个修正后形成能结果应能分别指向母体、缺陷电荷态、元素/竞争相参考、VBM/带隙参考、介电张量、远场势和修正协议。组成、电荷、方法、参考和条件的相容性由领域函数核对，不把若干独立计算的数值由语言模型拼成无来源公式。结合能若采用电荷/组成守恒的反应，应保存反应定义；费米能级扫描与电荷中性平衡仍是不同任务。

铁电第二部分可借它的“能力先行、按 observable 路由”：先确认相态与工况，再消费 P5/P7 参考和 P9 已验证的极化/场模型，进入 P10/P11 的极化、微分介电、电致响应或界面电边界任务。普通 E/F 势合格不能使这一分支自动通过。CaZrO3 的非极性验证不覆盖铁电能力；仍需适用的独立验证案例，而不是在本次评估中自动换材料。

这些是对已补齐任务的实现帮助，**不删除、合并掉或宣称完成** [铁电与缺陷工作包](ferroelectric-and-defect-work-packages.md) 中的科学要求。

## 7 证据成熟度与本次边界

源码包含持久任务、工作进程、科学交接和大量本地测试，但不能据此宣布整个光刻胶系统所有分支已经真实通过。其 2026-09-21 自然语言功能验收明确记载：当次中性 MD/带电 MD 在参数化阶段失败，没有被验收的生产轨迹；后续修复报告包含接口/本地测试改进，也明确不等于新的完整服务器科学验收。这些是历史运行的范围，不证明最新源码仍有同样故障，也不补足最新版本的端到端证据。

依据：[功能验收](../Photoresist-agent-kit-main/Photoresist-agent-kit-main/bundles/arf-car-computation/docs/qwen-functional-acceptance-2026-09-21.md)、[后续修复与限制](../Photoresist-agent-kit-main/Photoresist-agent-kit-main/bundles/arf-car-computation/docs/natural-language-acceptance-repairs-2026-09-21.md)。因此复用任何模块时，应验收它在 **MLCC 对象、本站环境和目标 observable** 下的行为，而不是移交对方测试数量作为证明。

本次只读检查参考树，新增本评估文档。未复制/执行其运行时代码，未部署 dispatcher/Worker，未修改 MLCC Bundle、现行阶段状态或原始计算记录，未提交数值作业。正式实施仍以 [PLAN.md](../PLAN.md)、[执行交接](P0-P12-execution-handoff.md) 和 [架构边界](harness-design.md) 为准。

## 8 关键实现证据索引

以下是本地源文件定位；行号为本次审查时的版本，不能代替运行验收。

| 文件与位置 | 本次核实内容 |
| --- | --- |
| [md.py](../Photoresist-agent-kit-main/Photoresist-agent-kit-main/bundles/arf-car-computation/skills/md-intent-routing/scripts/md.py)，31–50、91–139 行 | 公开生命周期入口与 worker-managed 任务对象 |
| [arf_md_tasks.py](../Photoresist-agent-kit-main/Photoresist-agent-kit-main/bundles/arf-car-computation/mcp-servers/arf_md_tasks.py)，305–315、776–792、949–1104、1129–1145 行 | 请求去重、重复续接、按阶段停下、计算阶段与追加分析 |
| [arf_jobs.py](../Photoresist-agent-kit-main/Photoresist-agent-kit-main/bundles/arf-car-computation/mcp-servers/arf_jobs.py)，564–604、615–689 行 | 提交意图与原生 Slurm 回执；不确定提交结果需核对 |
| [run_scientific_dispatcher.py](../Photoresist-agent-kit-main/Photoresist-agent-kit-main/bundles/arf-car-computation/deployment/run_scientific_dispatcher.py)，31、361–380 行 | wrapper 自动重试策略，MLCC 不采用 |
| [arf_lammps_ensemble_driver.py](../Photoresist-agent-kit-main/Photoresist-agent-kit-main/bundles/arf-car-computation/mcp-servers/arf_lammps_ensemble_driver.py)，26–40、348–400 行 | 副本数值失败自动恢复，MLCC 不采用 |
| [arf_task_queue.py](../Photoresist-agent-kit-main/Photoresist-agent-kit-main/bundles/arf-car-computation/mcp-servers/arf_task_queue.py)，36–56 行 | 工作区注册文件名使用 SHA-256；不是科学结果缓存 |
| [arf_md_handoff.py](../Photoresist-agent-kit-main/Photoresist-agent-kit-main/bundles/arf-car-computation/mcp-servers/arf_md_handoff.py)，28–58、72–169 行 | 父阶段、来源、工况、模型与参数覆盖的科学谱系核对 |
| [arf_analysis_data.py](../Photoresist-agent-kit-main/Photoresist-agent-kit-main/bundles/arf-car-computation/mcp-servers/arf_analysis_data.py)，162–243 行 | 从已有合格任务提取分析数据；温度点保留原材料/模型/目标身份 |
| [参数化 schema](../Photoresist-agent-kit-main/Photoresist-agent-kit-main/bundles/arf-car-computation/schemas/parameterized-model-ensemble.v2.schema.json) | 通用输出外壳，不能代替 MLCC 科学字段与资格协议 |
| [test_replica_qc_claim.py](../Photoresist-agent-kit-main/Photoresist-agent-kit-main/bundles/arf-car-computation/tests/test_replica_qc_claim.py)，35–69 行 | 不把不同暂存 ID 或简单平移当作统计独立性的测试意图；本次未执行测试 |
| [MLCC tasks.py](../mlcc-agent/src/mlcc/tasks.py)，1–5、22–91 行 | 已有普通 JSON、可读任务 ID、事件及读写边界，可作为增量实现基础 |
| [MLCC site_runner.py](../mlcc-agent/src/mlcc/site_runner.py)，129–225、316–519 行 | 已有 Slurm 提交/查询/取消/收集执行层，无须替换 |
