# MLCC 通用 MD 后处理、统计与聚合移植清单

**审查日期：** 2026-10-22  
**审查范围：** `Photoresist-agent-kit-main`、`Autonomous_Computational_Scientist-main` 两棵只读参考树，以及当前 `mlcc-agent` 的 LAMMPS 实现。  
**本清单的边界：** 只讨论通用 MD 轨迹/热力学后处理、统计和多任务聚合。高分子流程不属于当前晶体 MD 主线；为避免与另一份清单互相遗漏，第 4 节列出高分子 MD 候选来源、最小修改、证据和后置条件，但本次不实施。Berry 极化 GPU 故障、晶体缺陷、铁电介电和材料势资格属于当前主开发线，也不在本清单中重新实现。

## 1. 当前 MLCC 能力基线

下表记录清单编制时的0.9/早期0.10基线，行号为当时源码位置。随后job63/66/67补了候选静态张量、真实材料的限定资格用途及续接门，见 `workspace/reports/potential-qualification-v002/execution-ledger.md`；这些新增静态功能没有实现下面的通用MD序列/统计移植项，也没有放行真实材料MD。

当前 MLCC 的 LAMMPS 模块仍是可审计的工程接线和末帧解析器，尚未形成通用 MD 分析器：

| 位置 | 现状 | 直接证据 |
|---|---|---|
| `mlcc-agent/src/mlcc/lammps.py:34-35` | thermo 字段固定为 `Step/Temp/PotEng/KinEng/TotEng/Press`，dump 字段固定为 `id/type/x/y/z/fx/fy/fz`。没有速度、image flag、完整时间序列或 replica 元数据。 | 源码字段常量 |
| `mlcc-agent/src/mlcc/lammps.py:387-414` | `validate_lammps_protocol` 只检查 `run0`/`md`、`nve`/`nvt`、步数、步长、温度、seed、输出间隔和末帧可整除性；没有 equilibration/production 窗口、NPT、采样独立性、平稳性或统计门。 | `validate_lammps_protocol` |
| `mlcc-agent/src/mlcc/lammps.py:648-680` | `_parse_thermo` 只解析最后一个 thermo block 的最后一行。 | `_parse_thermo` |
| `mlcc-agent/src/mlcc/lammps.py:724-812` | `_parse_dump` 只取最后一个 frame；`_compare_md_final_frames` 只比较最终轨迹和 `dump.final`。 | `_parse_dump`、`_compare_md_final_frames` |
| `mlcc-agent/src/mlcc/lammps.py:815-952` | `parse_lammps_outputs` 生成 `mlcc.lammps-result.v1` 的末态结果，明确保持 `production_qualification=false`；没有 MSD、RDF、块统计、 replica 汇总或不确定度。 | `parse_lammps_outputs` |
| `mlcc-agent/src/mlcc/lammps_tasks.py:125-259` | `create_lammps_task` 只接受 `engineering_fixture`，写入 `production_label=false`。 | `create_lammps_task` |
| `mlcc-agent/src/mlcc/lammps_tasks.py:280-363` | `parse_lammps_task` 只将完成的工程 fixture 标为 `executed_engineering_fixture`，并写入 `sampling_equilibrium_qualified=false`。 | `parse_lammps_task` |
| `mlcc-agent/tests/test_lammps.py`、`mlcc-agent/tests/test_lammps_tasks.py` | 现有测试覆盖输入、原生输出、末帧、文件身份和损坏输入；没有 MD 后处理/统计测试。 | `rg` 审查结果，无相关函数/测试 |

因此“已有 MD 后处理”只能表述为末态提取和工程接线，不应在能力报告中写成生产级 MD 分析。已有服务器证据也只支持这一结论：

- `workspace/reports/lammps-md-system-v001/execution-ledger.md:19-20` 记录真实原生 Slurm **job45** 完成；`29-34` 记录不重跑 MD 的解析验收 **job47** 完成，正例为 `executed_engineering_fixture`，轨迹和 thermo 各有 0、10、…、100 共 11 个记录。
- `workspace/reports/lammps-md-system-v001/execution-ledger.md:40` 明确没有据能量变化授予时间步收敛、势精度或采样资格；`51` 明确生产、科学采样和陶瓷能力仍未验证。
- `workspace/reports/lammps-md-system-v001/reports-v002/acceptance.json:23-27,241-244,532-533` 的 `overall_pass=true` 只代表工程解析验收，`production_label=false`、`production_qualification=false`、`sampling_equilibrium_qualified=false`。

## 2. 分类和共同验收约束

本表中的“可移植”只表示源函数包含可复用的数学或输入合同；不表示可以把参考树代码直接复制到 MLCC。MLCC 仍需按本项目的原生 LAMMPS/Slurm/MatterAI 合同重写适配层。

- **可移植核心算法：** 参考函数已经做了数值计算，可提取其数学核心；输入单位、轨迹身份、周期边界、采样窗口和失败状态必须由 MLCC 合同重新定义。
- **仅包装/编排：** 参考函数负责路由、快照、报告、任务生命周期或提交；它不替代 MLCC 的科学函数，不能作为科学验收证据。
- **确实缺失：** 当前 MLCC 没有对应能力，应新增最小函数和结果字段，而不是把末帧解析器包装成统计分析器。

所有需要数值计算或科学后处理的验收都必须：

1. 在 v100 上通过 Slurm `sbatch` 执行，保留原生 job ID、提交脚本、stdout/stderr、输入、原始轨迹和终态；本地不得跑数值或数值测试。
2. 生产任务使用已通过材料势资格的模型；工程 fixture 的结果只作接线验收，不能升级为科学结论。
3. 对计算引擎本身支持 GPU 的任务，按配置优先使用 GPU；通用 MD 后处理和统计可在 v100 Slurm allocation 的 CPU 上执行，分析函数不因后端没有 GPU 支持而强行 GPU。Berry GPU 故障单独追踪；只有 Berry 的小规模 CPU 兼容性验证受明确预算限制，不把这一限制套到通用 MD。
4. 对不能满足门槛的轨迹返回结构化 `unresolved`/失败原因并保留已读入样本和诊断，不能给出伪造的扩散系数、RDF、平衡或生产资格。
5. MD-00 至 MD-07 共用一个在任务协议中声明的生产证据集；各分析切片从同一 collection/result/source_files 读取，不为每项另跑任务。统计所需的 replica、block、重叠或收敛检查属于该证据集协议，必须按声明执行，也不应被误解为禁止必要的重复采样或收敛验证；不进行温度矩阵扩展。

本清单中的 **P0/P1/P2 只是本移植表的优先级**，不是 `PLAN.md` 的阶段编号，也不改变主计划中晶体缺陷、铁电介电和材料势资格的优先顺序。

## 3. 逐项移植清单

### MD-00：扩展 MLCC 原生轨迹/thermo 数据合同（当前缺失，P0）

- **参考来源：** 当前 MLCC `mlcc-agent/src/mlcc/lammps.py:34-35,387-414,648-680,724-812,815-952`；参考树没有一个可以直接替代 MLCC 原生解析器的函数。
- **分类：** **确实缺失**。参考树的算法都假定已经有完整、有单位、有身份的时间序列，而 MLCC 目前只保留末帧。
- **已有能力/限制：** 能检查原生 log/input、读取末态 thermo、读取末态坐标/力并比较 `dump.final`；不能读取完整 thermo/dump 序列、速度或 image flags，也不记录 equilibration/production 切分、replica ID、packing/velocity seed、温度、时间步和模型身份的完整绑定。
- **最小修改：** 在现有解析器上增加一个明确版本的 MD collection/result 合同，保留现有末帧字段，新增：完整 thermo rows、完整轨迹 frame 索引、`timestep_fs`、物理时间、原子 ID/type 顺序、周期 image/unwrap 证据、replica/seed、`equilibration_window`、`production_window`、源文件和原生 job ID。缺失必需字段时失败或 `unresolved`，不得用默认值填补。
- **MLCC 目标文件：** 首选 `mlcc-agent/src/mlcc/lammps.py`（原生解析）；新增 `mlcc-agent/src/mlcc/md_analysis.py` 仅消费已验证 collection；`mlcc-agent/src/mlcc/lammps_tasks.py` 负责写入 Slurm/job/模型 lineage；对应测试扩展到 `mlcc-agent/tests/test_lammps.py` 和 `test_lammps_tasks.py`。
- **现有验收证据：** 有 `job45/job47` 的 11 条记录工程验收，但明确无完整序列分析、无生产资格；因此本项现有证据为 **部分证据**，不能作为完成证据。
- **共享生产证据集产物和门：** 一个已声明的 v100 Slurm 生产证据集（包含任务协议所需的原生 job）及其 `task.json`、`input.lammps`、完整 log/trajectory、`collection.json` 和 parser result；门为 job 正常完成、所有帧单调且完整、ID/type/盒子/单位一致、原生 job ID 和模型/势身份可回溯、不得出现隐式默认值。该 collection 供后续多个分析切片复用，只有需要的统计协议才增加声明的 replica/block 证据。
- **优先级：** **P0**，是所有后处理的输入前提。

**MD-00 工程证据更新（2026-10-22，job105）：** 新增独立直接函数`mlcc.md_trajectory.read_md_collection`及`tests/test_md_trajectory.py`，复用现有`parse_lammps_outputs/_parse_dump/_parse_thermo`等原生函数，未改公共LAMMPS/任务/CLI或冻结0.10。v100 Slurm **105 COMPLETED/0:0，2秒**：13项真实job45正例/临时损坏副本测试通过（0失败/跳过），随后只读job45，输出完整11帧/11条thermo、原子ID/type与坐标基底、源job/model/potential、metal单位、0.001ps=1fs时间步和0–100fs相对时间；下游JSON读回成功，原始任务及旧末帧result未变。image flags、逐帧速度、unwrap、平衡/生产窗口、replica和packing seed缺失明确保留，已有velocity seed正确绑定，不输出MSD/扩散/平衡资格。本项**当前固定格式的工程序列读取已验收**；通用生产轨迹和采样资格未建立，不阻塞后续系统合同/统计接口开发。没有新MD/DFT或材料筛选计算。证据：[报告](../workspace/reports/md-series-v011-v001/report.md)、[机器验收](../workspace/reports/md-series-v011-v001/acceptance.json)、[完整collection](../workspace/reports/md-series-v011-v001/collection.json)、[台账](../workspace/reports/md-series-v011-v001/execution-ledger.md)。公共CLI/MCP接线与发布由主集成窗口负责。

### MD-01：条件归一化和采样窗口合同（可移植合同，P0）

- **参考来源：** `Photoresist-agent-kit-main/Photoresist-agent-kit-main/bundles/arf-car-computation/mcp-servers/arf_md_conditions.py:16-28` 的 `_number`/`_steps`；`:30-75` 的 `normalize_settings`；`:78-98` 的 `compile_settings`。
- **分类：** **可移植输入合同 + 少量编译逻辑**，不是直接复制值域。参考实现为光刻胶扩散场景，包含 NPT/NVT、dt/duration、equilibration 等假设，MLCC 必须按 LAMMPS 单位和任务目标重新声明。
- **已有能力/限制：** MLCC 只校验固定 MD 基本字段和步数；不将时间步转换为物理时间，不区分平衡和生产，不要求生产采样区间与输出间隔相容，也不表达 NPT 盒子变化或统计目标。
- **最小修改：** 提取“显式条件、显式单位、显式窗口”的原则，新增 MLCC `md_conditions` 归一化：ensemble、温度/压力、dt、equilibration steps、production steps、thermo/dump interval、物理时间、目标分析和 replica identity；每个分析函数声明最低样本/窗口门。禁止照搬参考树中的自动默认和扩散专用阈值。
- **MLCC 目标文件：** `mlcc-agent/src/mlcc/lammps.py` 的协议验证；必要时新增 `mlcc-agent/src/mlcc/md_analysis.py` 的 analysis request schema；任务字段写入 `lammps_tasks.py`。
- **现有验收证据：** `job45/job47` 证明固定 100 步短程输入可运行，但未证明平衡/生产窗口；**无此项生产证据**。
- **共享生产证据集产物和门：** 同一证据集的 `conditions.json` 与 input 逐字段对照、窗口/输出间隔可整除性记录、Slurm job ID；门为输入合同完全显式，分析所需物理时间和窗口可由原生记录重建，NPT 时每帧盒子有效。
- **优先级：** **P0**，和 MD-00 同批完成。

**MD-01工程移植更新（2026-10-22）：** 参考上述`normalize_settings`/`compile_settings`的显式条件合同，最小实现为`mlcc.md_conditions.read_md_conditions`；不移植上游默认温压、NPT、扩散阈值或任务编排。模块job109 COMPLETED/0:0、10项检查通过，复用45/105；0.12候选公共`md-conditions`入口由job111 COMPLETED/0:0验收，新增3项CLI检查与2个真实命令调用通过。未声明窗口保留`unresolved_missing`及null计数，显式工程选择得到5/6样本；NVE初始化温度不冒充恒温目标，压力和replica不自动补值。原模型/势/任务来源及未资格状态继续传递，没有新MD/DFT。模块见`workspace/reports/md-conditions-v011-v001/acceptance.json`，公共入口见`workspace/reports/md-conditions-cli-v012-v001/acceptance.json`。上述模块验收时0.12尚未发布；随后安装job113已完成公共入口与统一交付验收，0.12现为0.13的回退版。生产采样资格未建立。

### MD-02：复用现有任务来源和选择校验（仅包装/编排，P1）

**0.12交付：** 最小接入为`md_sources.select_md_sources`，从既有collection直接读取原生task/job、模型/势/协议、全部帧原子索引和来源，复用上述来源选择/绑定原则，不复制上游snapshot存储、handoff路由或主控。模块job110通过10项检查；安装job113补公共`md-sources`入口两项与纵向消费。重复数据不能当独立replica，缺replica仍unresolved。证据：`workspace/reports/md-sources-v012-v001/acceptance.json`与`workspace/reports/system-v0120/installed-113/acceptance.json`。

- **参考来源：** `Photoresist-agent-kit-main/Photoresist-agent-kit-main/bundles/arf-car-computation/mcp-servers/arf_analysis_data.py:102-150` 的 `store_snapshot`、`:153-159` 的 `_read_snapshot`、`:162-182` 的 `_saved_data`、`:246-268` 的 `resolve_data`；`arf_md_handoff.py:13-15` 的 `bind_ref`、`:18-25` 的 `checked_binding`、`:28-35` 的 `write_handoff`、`:38-58` 的 `read_handoff`、`:66-69` 的 `_bound_document`、`:72-170` 的 `_check_parent_lineage`；`arf_md_task_analysis.py:104-138` 的 `_select`、`:141-228` 的 `analyze_task`。
- **分类：** **仅包装/编排**。这些函数不产生物理量；价值在于把已批准的数据、选择的 replica/species 和父任务绑定起来。
- **已有能力/限制：** MLCC 的 task/result 已写源文件和 Slurm 状态，但当前 parser 只读一个目录，不能表达多 replica 的选择和混合禁止规则；不需要另造 snapshot/handoff 数据库。
- **最小修改：** 复用现有 task/result/source_files、模型身份和原生 job ID；在已有结果进入分析函数前做本地选择校验，拒绝缺失、混用模型/物种/replica 或未批准的原始目录。不要新增 Photoresist 风格 `snapshot_id`、handoff ID、server 生命周期或路由框架，分析函数直接读取现有来源。
- **MLCC 目标文件：** `mlcc-agent/src/mlcc/lammps_tasks.py` 的现有 task/result/source_files；`mlcc-agent/src/mlcc/md_analysis.py` 只增加直接消费这些字段的校验/分析参数。结果仍存 workspace，遵守 MatterAI bundle 外科学数据规则。
- **现有验收证据：** `workspace/reports/lammps-md-system-v001/reports-v002/acceptance.json:207-226,241-244` 有模型路径、model_id、版本和源范围；**无多 replica 选择/lineage 的生产证据**。参考树的 snapshot/handoff 代码仅作为审查过的包装模式，不是 MLCC 已有证据。
- **共享生产证据集产物和门：** 复用同一证据集的现有 `task.json`、result、source_files 和 lineage 对照；门为所有原始文件、模型/势版本、原生 job ID、replica/seed 与各分析结果一一绑定，混用或缺失即不可消费。
- **优先级：** **P1**，在 MD-00 之后接入，属于可追溯性基础设施。

### MD-03：现有任务上的直接分析调用（仅包装/编排，P1）

- **参考来源：** `Photoresist-agent-kit-main/Photoresist-agent-kit-main/bundles/arf-car-computation/mcp-servers/arf_md_task_analysis.py:11-42` 的 route/field contract（仅作字段校验参考），`:45-48` 的 `_result`，`:141-228` 的 `analyze_task`。
- **分类：** **仅包装/编排**。`analyze_task` 负责输入校验、数据解析和调用 scientific kernel，本身不是 MSD/RDF 算法。
- **已有能力/限制：** MLCC 没有公共 MD analysis API；`parse_lammps_task` 只生成工程 fixture result，不能从现有 result/source_files 直接调用统一的统计内核。
- **最小修改：** 不新增公共路由框架。由已有任务处理入口在分析目标已声明时直接调用 `md_analysis.py` 中的具体函数（例如 `analyze_msd`、`analyze_rdf`、`analyze_thermo_statistics`）；保留每个 kernel 的原始诊断和 `unresolved` 结果。禁止从输入字符串自由选择引擎或静默改分析方法。
- **MLCC 目标文件：** `mlcc-agent/src/mlcc/md_analysis.py`；必要的调用点放在现有 `lammps_tasks.py` task/result 流程内，不新增 route record、snapshot 或 bundle API。
- **现有验收证据：** **无**；现有测试没有从 MLCC task/result/source_files 直接调用 MD 后处理函数的证据。
- **共享生产证据集产物和门：** 同一证据集上的具体 analysis request、result JSON 和 lineage；门为调用目标、输入字段和 scientific kernel 一一对应，失败保留原因并不生成可消费科学量。
- **优先级：** **P1**，只在已有至少一个可验收 kernel 后加入，避免先做空壳 API。

### MD-04：原子示踪多时间原点 MSD、扩散诊断和 Fick 窗口（0.44已启用，453/454验收，P1）

- **参考来源：** Photoresist 固定参考树 `Photoresist-agent-kit-main/Photoresist-agent-kit-main/bundles/arf-car-computation/mcp-servers/arf_properties_v2.py:522-534` 的 `_linear_fit`（带截距 OLS、RSS、R²）；`:560-593` 的 `_msd`（均匀时间检查、所有时间原点/track 的三维平方位移平均、实际 lag 与 origin count）；`:608-787` 的 `analyze_tracer_transport`（物理 Fick window、两半斜率、log-MSD 和失败保留）。`:537-557` 的 `_diagnostic`、`:596-605` 的 `_unresolved_transport` 只作失败状态参考；上游聚合物 COM/replica/CI 语义不移植。
- **分类：** **可移植数学核心 + MLCC 原子轨迹直接重写**。`source_atom_ids` 是原子集合，不是聚合物实体 COM；`dimensions=3`、`com_policy=none` 固定，不自动扣除整体漂移。上游自动 drift、0.75–1.25 log-MSD 门、1.0 Å² 最小变化和正态 CI 不进入 MLCC。
- **已有能力/限制：** `mlcc-agent/src/mlcc/md_trajectory.py::read_md_collection` 已绑定固定格式 collection、task/model/potential/source files、Prism、原子 ID/type 和物理时间。原生 unwrapped 输入/读取、`md_msd.py`及公共消费已由453验收；job45/job105只有wrapped `x/y/z`、缺image/unwrap，真实MSD/D仍null。新展开任务仅defined/jobnull，没有新增MD。
- **最小修改：** 请求固定 `source_atom_ids:[...]`、`dimensions:3`、`com_policy:"none"`、显式 `fick_window:{start_ps,end_ps}`，以及可选 `thresholds:{minimum_r_squared,maximum_relative_slope_spread,log_msd_exponent_range:[min,max],minimum_msd_change_A2?}`。从真实 unwrapped `id/type/xu/yu/zu` 读取多时间原点 MSD，输出 lag、MSD、origin/atom-origin counts、OLS、两半斜率差、log-MSD 和原始失败项；所有阈值和物理时间均由请求/原生记录提供。
- **MLCC 目标文件：** `mlcc-agent/src/mlcc/md_msd.py` 只负责已绑定 unwrapped 坐标上的 MSD/拟合；`mlcc-agent/src/mlcc/md_unwrapped.py` 负责可选 `protocol.unwrapped_trajectory=true` 的真实 `id/type/xu/yu/zu` 薄读取和校验；`md_trajectory.py` 复用现有 collection/Prism/source binding；由 `property_delivery.py::deliver_md_properties` 接入既有 `deliver-md`，不新增 router。
- **现有验收证据：** `workspace/reports/md-msd-v001/acceptance.json`：453 COMPLETED/0:0、4秒，17项新增检查（7算法/6原生格式输入读取/4集合消费）与2条公共命令成功。真实45/105缺项经deliver-md进入同一Ni Study；数学MSD正例独立保存；create-lammps仅生成未提交展开输入。Photoresist参考测试 `.../tests/test_transport_physical_window.py:35-83` 只作数学/输入参考。未重复MD-06/RDF、旧测试或新MD/DFT/训练。
- **共享证据集产物和门：** 同一 collection/source selection 产出 `md-msd.json`（lag、origin counts、MSD、Fick window、fit）、诊断和原生 job lineage，并接入现有delivery artifact清单。数学正例独立验证多原子/多原点、已知解析 MSD、非均匀时间、显式 Fick window 和未通过/null；真实 45/105 缺项路径已确认MSD/D null。新原生 unwrapped 正例未执行。安装454 COMPLETED/0:0、3秒，仅核对模块绑定、两条help、453真实argv参数解析和保存产物；无handler/kernel/native parser调用。发布证据：`workspace/reports/md-msd-v001/integration-v044/release-acceptance.json`。
- **优先级：** **P1**，先完成软件接线和失败保留；科学材料用途与采样资格仍保持未决，不作为本系统切片的前置。

### MD-05：显式单标量replica汇总（源码0.45由455/456验收，P1）

- **参考来源：** `Photoresist-agent-kit-main/Photoresist-agent-kit-main/bundles/arf-car-computation/mcp-servers/arf_properties_v2.py:75-87` 的 `_sample_summary`（`n>=3`、样本标准差、`SE=sd/sqrt(n)`、`mean±1.96*SE`）；`:90-113` 的 `hierarchical_replica_summary`（每 replica block 均值/within variance，并调用 `_sample_summary`）。
- **分类：** **等权数学核心移植 + 保存源薄适配**。不复制上游n>=3/默认1.96；显式descriptive或Student-t，后者使用SciPy n−1自由度及声明的置信度/iid假设。`hierarchical_replica_summary`只作block与replica边界参考，本片不新增层级块统计/bootstrap。
- **已有能力/限制：** 支持保存MD delivery中的`MD_temperature_sample_mean`或`MD_total_energy_final_minus_initial`。真实源仍为45原生→105集合→450标量的一条链，observed_source_count=1、replica_count=0，缺原replica ID/独立性声明，SD/SE/CI均null；不补造多轨迹。
- **实际修改：** `mlcc.md_replica.summarize_md_replicas`一次调用既有`select_md_sources`，绑定task/method/collection/保存thermo artifact原值；检查模型/势/方法/单位/固定几何/协议/窗口和原生ID/seed。只对已经保存的标量汇总，不重算thermo/MSD或读取原生轨迹。不同packing/拓扑、其它observable和层级block留后续。
- **公共入口：** `md-replicas --request --output`保存请求和本次Slurm ID；`deliver-properties --study --md-replicas --output`调用`property_delivery.deliver_md_replica_properties`，只消费保存产品并绑定原Study、task/job/observable，保留statistics/null/缺项和artifact清单，不再汇总。
- **现有验收证据：** 领域455 COMPLETED/0:0、14新增检查，见`workspace/reports/md-replica-v001/handoff.md`；公共456 COMPLETED/0:0、4秒、4新增交付检查和2条公共命令，见`workspace/reports/md-replica-delivery-v001/acceptance.json`。456复用455产品，未重跑领域测试、MD04/MD06或原生MD/DFT/训练。
- **交付产物：** 同一Ni Study的`run-456/replica-summary.json`和`delivery.json`，真实单源描述均值164.29835101990727 K，SD/SE/CI=null，45/105/450/455/456角色分开保留。数学多replica例仅在455验证，不当真实多轨迹。
- **优先级/剩余：** **P1首片已完成**，待0.45安装集成；缺真实多replica数据只影响该实例，不阻止软件发布。后续层级统计与其它observable须按明确需求扩展，不展开温度矩阵。

### MD-06：thermo 显式块统计、漂移和异常诊断（0.43已启用，450/452验收，P1）

**0.12部分交付及当前状态：** 既有`mlcc.md_thermo.analyze_md_thermo`消费MD-01/02合同，在`whole_record`或`step_range`上保留原始thermo rows，输出温度描述量和总能首末差；旧112/113证据保留且本轮未重复。0.43新增`thermo_diagnostics`及`deliver-md --collection`接线，由job450 COMPLETED/0:0验收，10项新检查、2条公共命令；一次读取job105保存的job45数据做新诊断，缺生产窗口请求不计算。安装job452 COMPLETED/0:0，复用450，仅核对绑定、help、真实参数解析和保存产品，没有重放统计；451缺摘要文件失败及定向修复保留。0.43已启用，发布证据见`workspace/reports/md-thermo-diagnostics-v001/integration-v043/release-acceptance.json`；源证据见同目录上级`acceptance.json`及`final-handoff.md`。

- **参考来源：** ACS 固定参考树 `Autonomous_Computational_Scientist-main/Autonomous_Computational_Scientist-main/mcp_services/MCP_IC_Tool/src/vasp_server/analyzers/md.py:1176-1234` 的 `_analyze_stability` 负责时间序列编排、平衡/异常调用和结果保存；`:1236-1247` 的 `_detect_equilibrium_index` 是带截距移动窗口 OLS 斜率的数学参考；`:1249-1255` 的 `_detect_anomaly` 是 z-score 异常索引的形状参考。Photoresist 的 `Photoresist-agent-kit-main/Photoresist-agent-kit-main/bundles/arf-car-computation/tests/test_md_stage_diagnostics.py:29-124` 只作为“短轨迹/失败阶段仍保留原生诊断”的测试参考，不移植其运行器、门或 `consumable` 语义。
- **分类：** **算法参考 + MLCC 直接重写**。ACS 的默认移动窗口、平衡索引和异常阈值不进入 MLCC；Photoresist 测试也不构成 MLCC 数值验收。
- **实际实现：** 新领域函数`mlcc-agent/src/mlcc/md_thermo_diagnostics.py::analyze_thermo_diagnostics`接入`md_thermo.py::analyze_md_thermo`、`property_delivery.py::deliver_md_properties`及CLI `deliver-md`。块统计、OLS漂移、z-score和保存集合消费已验收；未实现自动平衡判断，也不从描述性块量生成replica/CI/SE。
- **最小修改：** 在现有 `deliver-md` 请求中可选加入 `thermo_diagnostics`：`fields` 可选择 `temp`、`etotal`、`press`，每字段可提供 `max_abs_slope_per_ps` 和 `anomaly_z_threshold`；`blocks` 可提供带 `block_id`、`start_step`、`end_step` 的显式步区间。它们分别沿用原生单位 K、eV、bar，漂移阈值单位为 K/ps、eV/ps、bar/ps；异常阈值无量纲。观察窗口仍由 `whole_record`/`step_range` 指定，块区间为包含端点且必须落在窗口内，不生成默认窗口或默认块长。
- **算法边界：** 漂移使用真实物理时间 ps 的有截距 OLS；块均值/样本方差和块均值离散度是新增直接统计，不声称来自 ACS。异常使用有限样本总体标准差，零方差 z-score 定义为零并记录原因，不加 epsilon、不丢弃异常样本；少于两个样本的样本方差保留 `null` 和原因。
- **失败和状态：** 保留原始 rows、单位、来源、缺失证据和原始错误。显式阈值失败记录诊断失败项，但不自动移动窗口、截断、重跑、retry/requeue 或换引擎，也不把工程结果改成不可消费；未决状态不会阻断其他系统开发。已有 `sampling_equilibrium_qualified=false` 和科学资格状态照实保留。
- **现有验收证据：** job450 COMPLETED/0:0、3秒；7项新增领域检查和3项保存集合身份检查通过。`workspace/reports/md-thermo-diagnostics-v001/run-450/whole-record/delivery.json`及`thermo-diagnostics.json`保存真实11行/0–0.1ps、两显式块的统计及原生单位；`run-450/missing-window/delivery.json`保留诊断null。命令/原始输出/实际资源见该报告目录`execution-ledger.md`、`run-450/commands.json`、`scheduler-450.txt`。没有重跑47/112/113或其他旧验收。
- **共享证据集产物：** 继续从同一 collection 产生原始 thermo 序列、显式块统计、漂移和异常诊断；数学参考检验非零斜率、显式 blocks、异常阈值和零方差分支，不能当作新的材料数据。工程路径通过后继续原队列，不为 job45 短轨迹追加生产采样。
- **优先级：** **P1**，可与 MD-04 共用 collection；实现和验收不以材料生产资格为前置。

### MD-07：RDF、配位数和第一峰演化（可移植核心算法，P1）

- **参考来源：** `Autonomous_Computational_Scientist-main/Autonomous_Computational_Scientist-main/mcp_services/MCP_IC_Tool/src/vasp_server/analyzers/md.py:73-125` 的 `PyMatGenRDFAnalyzer`/`compute_rdf`；`:803-877` 的 `_analyze_rdf_pymatgen_custom`；`:919-962` 的 `_analyze_rdf_manual`；`:1044-1100` 的 `_compute_rdf_all`/`_compute_rdf_pair`；`:1102-1158` 的 `_analyze_rdf_features` 和 peak tracking。
- **分类：** **可移植核心算法**，需要脱离 VASP/XDATCAR 和 pymatgen 输入层重写。周期距离、r-bin、体积/密度归一化、pair selection 和峰特征可复用；参考实现自身没有 MLCC 所需的严格轨迹身份、盒子变化和统计门。
- **已有能力/限制：** 0.13已交付固定胞/完全周期的显式物种对RDF与截断内累计配位计数；第一峰资格、variable-box及block/replica统计仍未完成。
- **最小修改：** 对每个 production frame 使用原生 LAMMPS cell/PBC，显式 species/type pair、rmax、bin width、归一化和样本窗口；对 variable box 逐帧使用实际盒子，不允许隐式正交盒假设；输出 `g(r)`、配位积分、峰位置/高度/宽度及 frame/block/replica 统计。把 ACS 的自定义 RDF 作为数学参考，不直接依赖其 `Structure`/VASP loader。
- **MLCC 实际文件：** `mlcc-agent/src/mlcc/md_rdf.py::analyze_md_rdf`，测试`tests/test_md_rdf.py`；由`property_delivery.py::deliver_md_properties`最小接入既有`deliver-md`。
- **现有验收证据：** v100 job119 COMPLETED/0:0，11项模块检查及job45真实11帧；安装127通过显式50–100步RDF交付及缺窗口不计算分支。见`workspace/reports/md-rdf-v013-v001/acceptance.json`与`workspace/reports/system-v0130/installed-127/acceptance.json`。
- **共享生产证据集产物和门：** 从同一 collection 产生 `rdf.json`/`coordination.json`，包含输入 pair、r 网格、PBC/cell、帧数、block/replica 汇总和原生 job ID；门为 cell/PBC/单位全部显式、帧完整、pair 选择不混淆、归一化可复算，并通过一个独立负例（缺 cell 或非均匀轨迹拒绝）。
- **优先级：** **P1**，对晶体 MD 结构稳定性有直接价值，但必须排在 collection 和材料势资格之后。


实际最小适配：复用ACS分箱/密度思路，改为原生prism/PBC、保守半面距截断、去自对的有向配对及有限粒子数归一化；不照搬缺物种填零、默认分母或自动峰判定。job45合法范围内确实无配对，不能称完整第一壳配位数为零。当前冻结本切片，不追加RDF精调；核心队列先P5。

### MD-08：多温度 Arrhenius/温度依赖聚合（可移植骨架，P2）

- **参考来源：** ACS `Autonomous_Computational_Scientist-main/Autonomous_Computational_Scientist-main/mcp_services/MCP_IC_Tool/src/vasp_server/analyzers/md.py:1260-1321` 的 `_analyze_arrhenius_across_subdirs`；Photoresist `Photoresist-agent-kit-main/Photoresist-agent-kit-main/bundles/arf-car-computation/mcp-servers/arf_advanced_analysis_v2.py:138-193` 的 `fit_temperature_dependence`。
- **分类：** **可移植统计骨架 + 严格输入重写**。ACS 以子目录聚合 D 并线性拟合；Photoresist 提供 Arrhenius/WLF 拟合和诊断，但参考场景有独立 replica/temperature contract。两者都不能替代 MLCC 的材料温度设计。
- **已有能力/限制：** MLCC 没有多温度 MD 聚合、温度身份、D 不确定度、Ea 区间或模型比较；当前需求明确不展开 CaZrO₃/BaTiO₃ 温度矩阵。
- **最小修改：** 只提供“已存在且各自通过 MD-00~07 的任务结果”的聚合函数：要求显式温度单位、每温度独立 replica/seed、每温度统计门通过；输出 Arrhenius 拟合、拟合区间、R²、残差、温度点清单和限制。不得由聚合器自动提交缺失温度或把不同模型/势混合。
- **MLCC 目标文件：** `md_analysis.py` 或独立 `md_statistics.py`；接入 `lammps_tasks.py` 的结果引用；不修改材料温度矩阵配置。
- **现有验收证据：** **无**。当前 job45/job47 是单温度工程 fixture，且未发布 D。
- **共享生产证据集产物和门：** 仅在主代理明确批准后，使用同一批已完成且各自通过统计门的多温度结果生成 `temperature-fit.json`；门为每个温度都有完整 lineage/统计门、拟合范围和不确定度，可追溯到原生 Slurm job ID。当前开发窗口不提交此任务。
- **优先级：** **P2**，后置；不得以此项阻塞晶体缺陷、铁电介电和材料势资格主线。

### MD-09：PMF/WHAM 等窗口聚合（后续可选，P2）

- **参考来源：** `Photoresist-agent-kit-main/Photoresist-agent-kit-main/bundles/arf-car-computation/mcp-servers/arf_advanced_analysis_v2.py:206-273` 的 `analyze_pmf_windows`；参考测试 `Photoresist-agent-kit-main/Photoresist-agent-kit-main/bundles/arf-car-computation/tests/test_arf_advanced_transport_v2.py:173-243` 的窗口重叠、平衡和收敛门。
- **分类：** **可移植核心算法，但当前缺失且不属于首轮通用晶体 MD 必需项**。
- **已有能力/限制：** MLCC 没有反应坐标、窗口、bias、重叠和 WHAM/PMF 数据合同；当前 LAMMPS 工程 fixture 不能支持该科学任务。
- **最小修改：** 仅在明确科学需求和材料势资格后建立独立 request：窗口反应坐标、bias、平衡证据、采样数、重叠、迭代收敛和自由能参考；失败保留窗口诊断，不发布 PMF。
- **MLCC 目标文件：** 后续 `md_analysis.py` 的独立模块或单独 `md_pmf.py`；不塞入基础 parser。
- **现有验收证据：** **无**，参考树测试不能算 MLCC 验收。
- **共享生产证据集产物和门：** 若后续批准，所有窗口的原生 Slurm job/trajectory、窗口审计表、重叠和收敛报告、PMF JSON 必须在同一声明协议下汇总；当前窗口不执行。
- **优先级：** **P2**，明确的范围外科学任务。

### MD-10：HTML 报告和直接执行包装（仅包装/明确排除，P2）

- **参考来源：** ACS `Autonomous_Computational_Scientist-main/Autonomous_Computational_Scientist-main/mcp_services/MCP_IC_Tool/src/vasp_server/analyzers/md.py:1542-2449` 的 `MDHTMLReportGenerator`，`:2455-2477` 的 `generate_md_analysis_report`；`Photoresist-agent-kit-main/Photoresist-agent-kit-main/bundles/arf-car-computation/mcp-servers/arf_lammps_ensemble_driver.py:157-400` 的 retry/recovery 逻辑和 `run_ensemble`（`:269-422`）。
- **分类：** **仅包装/明确排除**。HTML 是展示层；`run_ensemble` 包含自动 retry/recovery。MLCC 规则禁止自动重试、静默换引擎和本地绕过 Slurm，因此不移植其运行器行为。
- **已有能力/限制：** MLCC 当前有 JSON/ledger 证据习惯，没有通用 MD HTML 报告；这不是当前科学功能缺口。
- **最小修改：** 只生成结构化 JSON 和一页可读的验收摘要（若主代理需要），由已有报告/ledger 引用；任何失败保留原错误，提交由 Slurm runner 负责，不自动重跑/改后端。
- **MLCC 目标文件：** `workspace/reports/...` 证据和现有报告生成路径；不将参考 HTML 类复制进 `mlcc-agent`。
- **现有验收证据：** `workspace/reports/lammps-md-system-v001/reports-v002/acceptance.json` 与 `execution-ledger.md` 已证明 JSON/ledger 方式可用；**无通用 MD 报告需求证据**。
- **共享生产证据集产物和门：** 结构化 result、acceptance summary、原生 job ID；门为所有数值结论能回溯同一证据集的原始文件和诊断，不得因报告生成失败改变科学状态。
- **优先级：** **P2**，不投入主开发时间。

## 4. 高分子 MD 候选移植清单（登记、后置，不要求本轮实施）

这一节补齐高分子链段 MSD、构象和表观 Tg 的归属，避免两份清单互相遗漏。它们是 Photoresist 的高分子专用科学 kernel，不能算作当前 MLCC 陶瓷体系已经具备的能力；若未来需要，仅复用 MLCC 现有 task/result/source_files，直接调用分析函数，不新增 snapshot 或 route 框架。

### POL-MD-01：链段 MSD/segmental dynamics（可移植核心算法，P2 后置）

- **参考来源函数：** `Photoresist-agent-kit-main/Photoresist-agent-kit-main/bundles/arf-car-computation/mcp-servers/arf_properties_v2.py:790-850` 的 `analyze_segmental_dynamics`；其在 `:829` 调用同文件 `:560-593` 的 `_msd`。
- **已有能力/限制：** 该函数真实计算每个 replica 的 segment COM 多时间原点 MSD，但明确不把 segment MSD 改名为扩散系数。参考输入硬性要求 `replicas` 至少 3 行、唯一 `replica_id`、唯一 packing/velocity seed、`no_jump_evidence=true`、严格递增 `times_ps`、每条 segment track 与时间长度一致；结果在 `:839` 调用 `_sample_summary`，因此还继承参考实现的 `n>=3` 和 `1.96*SE` 特例。这是该参考 kernel 的限制，不是 MLCC 通用生产标准。MLCC 当前没有链拓扑、segment 映射或该类轨迹证据。
- **最小修改：** 若未来纳入高分子模型，使用现有 task/result/source_files 传入 LAMMPS 轨迹和链拓扑，显式声明 atom/type→segment 映射、whole-segment COM、PBC image/unwrap、production window、replica/seed 和统计区间方法；保留“segment mobility descriptor，不是 D/Tg”的 claim scope。不得直接复制 Photoresist 的字段名或把陶瓷 type 当链段。
- **MLCC 目标文件：** 后续可放入独立 `md_analysis.py` 的 polymer 分支或专用模块；现阶段不修改 `lammps.py`/`lammps_tasks.py` 以支持高分子。
- **现有验收证据：** 只有参考函数代码；MLCC 无链拓扑、unwrap segment COM 或 segmental MSD 的任务/Slurm 证据。参考函数的数学单测不能作为 MLCC 科学验收。
- **共享生产证据集产物和门：** 若后续批准，复用同一高分子生产 collection 生成逐 replica segment MSD、`origin_counts`、链段映射和统计汇总；门为拓扑/映射/unwrap 证据、时间和窗口完整、独立性与区间方法按任务声明通过，并明确不输出扩散系数。当前窗口不提交该任务。
- **优先级：** **P2 后置**，不阻塞陶瓷缺陷、铁电介电或材料势资格。

### POL-MD-02：组分构象/回转半径（可移植核心算法，P2 后置）

- **参考来源函数：** `Photoresist-agent-kit-main/Photoresist-agent-kit-main/bundles/arf-car-computation/mcp-servers/arf_properties_v2.py:853-876` 的 `analyze_component_conformation`；函数在 `:873` 调用 `_sample_summary`（定义于 `:75-87`）。
- **已有能力/限制：** 该函数按 replica 接受 `radius_of_gyration_angstrom` 序列，要求唯一 replica/packing/velocity seed，并返回 replica 均值、帧内标准差和整体汇总；其 claim scope 明确只是固定拓扑组分构象证据。MLCC 当前没有组分/链拓扑映射、PBC 下整组分 unwrap 或构象统计。
- **最小修改：** 未来从现有 LAMMPS task/result/source_files 解析显式 component/chain membership，在每帧先完成 whole-component image/unwrap，再计算 Rg；声明质量权重、帧/块相关性、replica 方案和有限样本区间方法。不能把参考 `_sample_summary` 的 3 replica/1.96 直接当生产标准。
- **MLCC 目标文件：** 后续 `md_analysis.py` 的 polymer conformation 分支；现阶段无实现。
- **现有验收证据：** 只有参考函数代码和其输入门；MLCC 无构象或 Rg 生产任务证据。
- **共享生产证据集产物和门：** 复用高分子 collection 的 `rg.json`、组分映射、每帧/每 replica 统计和原生 job ID；门为拓扑映射、PBC 处理、帧覆盖、统计依赖性和声明的区间方法可追溯。当前窗口不提交。
- **优先级：** **P2 后置**。

### POL-MD-03：表观玻璃化温度 Tg（可移植统计 kernel，P2 后置）

- **参考来源函数：** `Photoresist-agent-kit-main/Photoresist-agent-kit-main/bundles/arf-car-computation/mcp-servers/arf_properties_v2.py:897-902` 的 `_information_criteria`、`:905-928` 的 `_fit_temperature_scan`、`:931-1076` 的 `analyze_apparent_glass_transition`，其中 `:1024-1027` 计算每个 setpoint 的均值/诊断，`:1039-1059` 进行模型门，`:1060-1076` 汇总 breakpoint/bootstrap 并判断 consumable。
- **已有能力/限制：** 这是参考树中真实存在的 Tg 流程，不是文件名推断。参考函数要求显式递增且至少 20 个 distinct setpoint、至少 3 个独立 scan（`:943-954`），每个 scan 匹配相同 schedule、每个 bin 至少两组配对温度/密度样本（`:975-1021`），并要求 BIC/AICc 模型比较、bootstrap 参数和 stationarity diagnostics。这些是该高分子参考 kernel 的输入门，不能泛化为所有 MLCC 统计任务的默认值。它只声明 `apparent_md_tg_for_declared_force_field_chain_length_and_scan_rate`，`:1055` 明确诊断不是平衡证明。MLCC 当前既没有聚合物链，也没有温度扫描数据。
- **最小修改：** 若未来需要，改为消费已有 task/result/source_files 的温度扫描结果，显式绑定 chain length、scan rate、force field、setpoint schedule、初始化 seed 和采样窗口；由任务协议声明 setpoint 数量、独立 scan 数、有限样本区间和 bootstrap 方法。不得把该高分子 Tg 流程套到 CaZrO₃/BaTiO₃，也不得在当前窗口自行展开温度矩阵。
- **MLCC 目标文件：** 后续 `md_analysis.py` 或独立温度统计模块；当前不实现。
- **现有验收证据：** 参考测试 `Photoresist-agent-kit-main/Photoresist-agent-kit-main/bundles/arf-car-computation/tests/test_temperature_scan_startup.py:41-104` 覆盖扫描 schedule/启动校验；MLCC 无温度扫描、聚合物链或 Tg 的 Slurm 证据。
- **共享生产证据集产物和门：** 若主计划明确批准，产出同一声明温度扫描证据集的 schedule 对照、每 scan 原生 job ID、density/temperature series、model comparison、stationarity 和 bootstrap result；门为所有 setpoint/scan/配对样本/lineage 通过，并保留 `diagnostic_not_proof_of_equilibrium` 限制。当前窗口不提交。
- **优先级：** **P2 后置**，不阻塞当前陶瓷主线。

## 5. 参考树中明确不应直接移植的部分

1. **ACS 的 VASP 输入层和启发式默认值。** `VASP_MDAnalyzer._load_md_data`（`md.py:286-432`）会从 XDATCAR/vasprun/OUTCAR 推断时间步、温度、压力和能量，并在缺失时使用默认/正则匹配路径；MLCC 必须使用原生 LAMMPS 合同、显式单位和显式 provenance，不能把这些推断改名后继续使用。
2. **ACS 的电荷猜测。** `md.py:667-674` 的 `_guess_charge_number` 是按元素的启发式映射；MLCC 不得用它计算导电率/带电输运。电荷态必须由材料/模型合同显式提供。
3. **ACS 的单次 `_fit_linear_tail`。** `md.py:646-665` 固定使用 20%–80% tail，不能替代预声明的物理 Fick window、replica 统计和平稳性门。
4. **Photoresist 的自动 retry/recovery。** `arf_lammps_ensemble_driver.py:157-400` 为光刻胶运行器的容错策略；MLCC 规则要求原生 Slurm job ID 和原始失败，禁止自动重试、requeue 或换引擎。
5. **Photoresist 的聚合物专用函数。** `arf_properties_v2.py:790-876` 的 `analyze_segmental_dynamics`/`analyze_component_conformation` 和 `:931-1075` 的 `analyze_apparent_glass_transition` 已在第 4 节登记为后置候选；它们不能被计入 MLCC 当前通用晶体 MD 能力，也不能直接用于 CaZrO₃/BaTiO₃。
6. **HTML 和光刻胶 server 生命周期。** `arf_server.py:484-543,3369-3859` 的提交/注册/charged transport 集成是参考架构，不是可直接复制的 MLCC API；只吸收 lineage、失败保留和分析 kernel 分层原则。

## 6. 推荐实现顺序与当前窗口停点

推荐严格按以下顺序推进，以免在没有科学输入的情况下堆积包装代码：

1. **P0：** MD-00 原生完整 collection + MD-01 条件/窗口合同。先让一个按后端能力优先使用 GPU、材料势已资格化的生产标准 LAMMPS 任务能够产生可消费的完整序列；保留 job ID 和失败证据。
2. **P1：** MD-02/03 只复用现有 task/result/source_files 做最小直接调用绑定；随后 MD-04 MSD/Fick 和 MD-06 thermo 诊断；最后 MD-05 replica 汇总与 MD-07 RDF/配位。
3. **P2：** 只有主线科学需求确认后，才做 MD-08 温度聚合和 MD-09 PMF；不在当前窗口展开 CaZrO₃ 400–580 °C 或 BaTiO₃ 800–1350 °C 温度矩阵。
4. **验收策略：** MD-00 至 MD-07 使用一个声明的生产证据集，多个切片复用同一原生轨迹/result/source_files；必要的 block、replica、窗口重叠或收敛检查按同一协议完成，不为每个函数重复提交任务。数学单测只证明算法；科学资格必须由 v100 原生任务和材料势/轨迹合同分别证明，不能用一个替代另一个。

更新（0.11交付）：**MD-00完整序列模块已由105验收，公共`md-collection`入口由安装副本108验收并启用**，复用job45的11帧和11条thermo，源函数和最小适配见MD-00条目。108只补2项CLI检查和实际入口，不重复105全套检查或MD计算。MD-01由现有执行窗口继续，未纳入0.11；统计、RDF、MSD、replica聚合及生产资格仍未完成。工程路径可先消费缺失证据和未资格状态，不以材料精度通过作为继续移植的前置。验收见`workspace/reports/mace-public-v011-v001/installed-108/acceptance.json`。

2026-10-25当前：MD-06已由450/452验收，MD-04已由453/454验收并随0.44启用；下一MD-05领域模块与公共接线由两个现有窗口分工。45是唯一原生轨迹，105/450/453为消费或分析，不构成独立replica。不追加MD/DFT/训练或温度矩阵；下游保留真实缺项，科学采样资格分开记录。
