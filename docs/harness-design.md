# MLCC harness 与上游集成

2026-10-23 00:42：当前启用0.20、回退0.19、源码0.21；新增静电势原生来源入口，沿用原Bundle、七MCP和Slurm架构，见[0.20合同](system-contracts-v0200.md)。下方旧版本段落为历史。

2026-10-22 23:39现行发布为0.19，0.18回退、源码0.20候选；新增缺陷电子参考与Study交付见[0.19合同](system-contracts-v0190.md)。仍沿用下述MatterAI Bundle、七MCP和Slurm架构，无新增主控。下方0.9状态段是早期架构记录，不表示当前启用版本。

本文件定义通用 MLCC 仿真计算系统的执行层边界。当前交付 0.9.0：结构与派生模型、VASP/ABACUS 输入/解析、方法资格、电子/DOS、弹性软件门、缺陷热力学与设计比较、Phonopy 位移/任务/原生力/谐波接口、LAMMPS 工程输入解析，以及 Slurm CLI 和 7 个 MCP 工具。完整弹性/缺陷/声子原生数据、带电修正、H1/生产精度、四性质科学执行链与 MD 采样尚未完成。真实范围见 [0.9.0说明](system-contracts-v090.md) 与 [阶段状态](../plans/stages.json)；[主计划](../PLAN.md) 是执行入口。

另一执行窗口的逐项任务与验收要求见 [P0–P12 执行交接文档](P0-P12-execution-handoff.md)；本文提供架构边界，不替代其中的真实集成验收。

2026-10-21 规划补充：架构主要参考 Photoresist-agent-kit 的薄 Agent、持久科学任务、阶段交接与收集后验收；功能参考 Photoresist 与 ACS，具体映射见 [双案例详细执行计划书](MLCC系统详细执行计划书-CaZrO3-BaTiO3-v002.md)。保留现有七 MCP/Slurm 执行层；不移植参考项目的自动重试、内容缓存、第二主控或常驻 Worker。CaZrO₃ 与 BaTiO₃ 是独立案例，后者烧制温区800–1350 °C已明确，相及其余边界未定；本次规划不改变运行时能力或资格。

2026-10-22 0.9.0 更新：v100 Slurm job43 通过 296 项测试，job44 通过安装副本全部专项与合同检查，原版 MatterAI/MCP 调用通过，44 个发布文件直接一致。LAMMPS 线程的 job41 验证静态 run0，P7 只验证软件/缺证据阻断，均不授予生产科学资格。两窗口继续按模块分工；下一版本切片是 P5 Berry 极化输入与原生解析。历史 0.8.0 的 223 项测试和 39 文件发布记录保留在其独立合同与报告中。

数值计算、科学后处理和数值验收统一在 v100 通过 Slurm 运行。本地只承担编辑、传输控制、安装/连接检查与结果查看。验收镜像显式迁移 JSON 中的工作区路径，原生数据不改字节；镜像中的既有 job ID 是历史来源，不是新计算。

## 1 三层职责

MatterAI 管会话、能力装载、工具网关和产物显示；MLCC Bundle 管科学 SOP 与确定性工具；v100 管指定资源的数值执行。ACS 是 VASP/MCP/任务的实现参考，第一版不运行第二套 ADK 主控、Web、PostgreSQL 或自动研究循环。不将 MatterAI campaign 的假候选/自动修补作为科研 harness。

## 2 MatterAI 契约

- mlcc-agent/bundle.json 使用 matterai.bundle.v2 和精确三段版本；两个上游下载树不进入 Bundle。
- agents/mlcc/AGENT.md 的 title、description、2–4 条 starters 是展示源；不在 .matterai-agent-kit 放定义。
- 四项 Skill：model-mlcc-structures、run-mlcc-dft、compute-mlcc-properties、run-mlcc-md。manifest.agent.skills 是权威列表，各 SKILL.md 有 name/description。
- 源码与安装目录 .zeus/bundles/<name>/<version> 分开；运行结果留 workspace。已安装版本不原地改写，升级新版本。
- Bundle mcpServers 声明不授予执行权限。当前安装的0.9.0声明真实 stdio 服务与 7 个允许工具，risk=networked；源码与已安装入口均通过直接 MCP 握手，已安装工具也实际查询过 Slurm。MatterAI非桌面原版runtime→已安装MCP真实调用已验收；桌面 review 只属于参考树的一个宿主实现，不是本项目必需入口。详见 [运行入口更正](matterai-runtime-scope.md)。
- 会话继续由 MatterAI Runtime Session Binding 管理，不用 ACS 项目会话 ID 替换，不跨项目复制 provider session。

本地依据：MatterAI docs/bundles.md:50、:81、:168，docs/extending-zeus.md:19，以及 packages/core-engine/src/bundles/bundle-registry.ts 的 BundleManifest/parseBundleManifest。在线两仓库本次 404，以本地副本为依据。

实际安装命令（从独立 `workspace/runtime/matterai` 运行；日志见 `workspace/reports/h0-p0/`）：

~~~powershell
cd D:\project\mlcc\workspace\runtime\matterai
npm run bundle:install -- D:\project\mlcc\mlcc-agent --workspace D:\project\mlcc\workspace --enable
~~~

安装成功也不等于计算工具接线成功。开发期项目 .zeus/mcp.json 只能登记实际服务，仓内路径用 zeus://workspace/current/...；机器绝对路径与凭据不写进可移植 Agent/Skill。

## 3 ACS 复用的边界

优先取用 VASP 输入/输出、任务 API、真实状态和文件产物链，不拷贝 .env、数据库、历史 workspaces、key、许可证文件或旧任务。

README 中另一个 IP/账号、/mnt/data/Autonomous_Computational_Scientist，以及 8130/8140/8190/8788 是原部署约定，不是本站已有服务的证据。v100 是 192.168.110.35:22，现已安装并配置单节点 Slurm；项目以 Slurm 为目标后端，但 ACS 控制面/worker 尚未部署，也不能只换 IP 后宣称可用。

不照搬自动恢复/重提、hash/digest 缓存或用通用离子半径阈值拒绝科研候选的逻辑。两个上游根未发现 LICENSE 文件，复制/再分发代码前明确许可证/授权。本次仅新写 MLCC 文档与能力定义，不复制实现代码，不宣称有重新发布授权。

已复核的具体实现入口（均相对 ACS 根）：

| 入口 | 实际契约 | MLCC 取舍 |
| --- | --- | --- |
| mcp_services/MCP_IC_Tool/src/mcp_ic_tool/client.py:106 | POST /vasp/structure-optimization、/scf-calculation；GET /vasp/task/{task_id} | 可参考提交/查询和结果合同，不假设服务已部署 |
| mcp_services/MCP_IC_Tool/single_port_server.py:234 | VASP MCP 的 /mcp 入口，原服务端口 8130 | 接入现有服务时显式配置 endpoint 和 user_id，不使用默认用户 |
| mcp_services/MCP_IC_Tool/src/vasp_server/hpc_pull_worker.py:143 | MCP→API/数据库→pull worker→数值任务 | HTTP 是原提交数据面，SSH 仅部署/隧道；不能说改 SSH 即接通原链 |
| mcp_services/MCP_IC_Tool/src/vasp_server/vasp_worker.py:2844 | 实际执行 sbatch；worker 查询 squeue/sacct | 显式适配本站 Slurm；sacct 持久记账尚未配置，不直接声称 worker 全链可用 |
| mcp_services/MCP_IC_Tool/src/vasp_server/settings.py:29 | 含原 VASP/赝势/工作根、MPI/Slurm、存储与服务默认值 | 不带入旧路径/默认凭据；本站配置独立 |
| mcp_services/MCP_IC_Tool/src/vasp_server/vasp_server_api.py:1132 | 旧 /download/file 路由返回 410，结果走 artifact | 不按旧下载 URL 拼结果；当前 LAN 回传另走明确 scp 路径 |
| mcp_services/MCP_Strctgen_Tool/src/tools/config.py:7 | 输出目录 STRUCTGEN_DOWNLOAD_ROOT/cif_outputs/<user_id> | 可借鉴工具面；建模内核仍按用户要求 pymatgen＋ASE |
| src/vasp_agent/persistence/store.py:69 | 原研究工作区为 .research 图/任务/事件 | 不复制原用户工作区或会话；需取用时做显式编号映射 |
| scripts/restart_jarvis_stack.py:228 | 启动前 terminate/kill 既有服务与端口 | 禁止直接运行此脚本初始化 MLCC |

原部署启动顺序是 Structure MCP→VASP API→pull worker→VASP MCP→Web；完整复用还要求独立数据库、worker token、可达输入与 artifact 存储。API/MCP 端口不同，不能猜控制面 URL。当前选择本站单节点 Slurm 调度适配器，SSH 仅承载提交命令与传输；不另造脱离调度器的进程管理器。

## 4 站点、执行、传输

配置为 ../configs/site.v100.example.json，安装前证据为 v100-environment.md，安装后记录为 slurm-installation.md。后端固定 slurm；VASP 用 NVHPC MPI、ABACUS 用其 MPICH，各自显式环境与 PMI/PMIx 测试，不依赖交互 .bashrc，也不自动回退直接进程。

函数区分 prepare、transfer、submit、query、cancel、collect。submit 使用 sbatch --parsable，返回 task_id 与原生 job ID；query 读取真实调度状态，cancel 调用 scancel。SSH 存亡不是作业状态，PID 不代替 job ID。资源先限单任务小基准，再按测量显式配置四卡。

保留 Slurm 原生状态、退出码和资源，以及 scientific_status 的电子/离子收敛与物理对照；COMPLETED/退出 0 不等于科学可用。当前控制器保留近期作业状态并写完成日志，未配置 sacct 持久数据库；项目完成时需保存自己的终态记录，若完整复用 ACS 则先补齐其记账依赖。无自动重试/requeue/替换。

scp 默认使用 v100 LAN 别名与明确路径；回传结构、JSON/CSV、日志和选定轨迹。WAVECAR/大电荷/完整轨迹留远端按普通 task_id/路径引用，不做文件摘要/内容缓存，不传全数据盘。

MatterAI 分布式 Worker 上传文档自身要求 SHA-256。当前使用本地 workspace＋SSH 数据面，不启用该云上传链；不删上游安全机制，也不把它冒称已符合当前无哈希约束。以后改用时需先解决约束冲突。

## 5 最小工具与模块

以下是计划函数，不是已存在的 MCP tool：

| 工具/函数 | 工作 | 阶段 |
| --- | --- | --- |
| build_model | 来源/相/掺杂→显式原子及映射 | P2 |
| prepare_calculation | 指定引擎输入，不提交 | P3/P4 |
| submit/query/cancel/collect_calculation | LAN 控制、Slurm 调度与真实结果 | P1/P3 |
| calculate_property | 极化、自旋、位移力、热电任务组 | P5–P8；当前仅公共标量性质交付切片已验收 |
| expand_model | exact 扩胞/映射或独立重随机派生模型 | P9 |
| prepare/collect_md | 明确势/边界的任务与可观测量 | P10/P11 |

按阶段建立一个 Python 包，用普通函数/轻量记录和 subprocess。已实现 modeling、model_derivatives、tasks、site_runner、vasp、abacus、studies、workflow、results、qualification、defect_thermodynamics、property_delivery、cli、mcp_server；MCP 仅薄封装。ferroelectric、magnetism、phonons、transport、lammps、reporting 仍待对应阶段创建或接通原生适配器，不创建空模块、插件基类、消息队列、通用版本猜测或自动恢复服务。

用户数据留 workspace/models/<model_id>/v001、workspace/tasks/<task_id>、workspace/results/<study_id>。原生 ACS 任务号若取用，存 source_task_id，不冒充 MatterAI thread/session。

## 6 数据合同与引擎迁移

Model：model_id、version、parent_models、structure_file、atom_ids、source_path/version、phase、composition、dopants、random_seed。异质界面有多个父模型，不从“最新文件”猜来源。

Task：task_id、stage、model_id/version、engine、method_set、depends_on、runner、scheduler_job_id、remote_workdir、resource_request、command、status、exit_code、log_file、source_task_id。命令按参数列表，环境显式给出。

Result：name、value 或 data_file、unit、conditions、method、source_task、model_id/version、status。未算 value=null、status=not_calculated，不补零或借其他材料值。

以下为新增待实现合同，不代表当前安装版本已经支持：Study 记录 study_id、case_id、角色（工程 fixture / 科学验证案例 / 具体研究）、selected_purposes、selected_scenarios、selected_required_tasks 和可空的 design_requirements_ref。通用请求模板见 [study.example.json](../configs/study.example.json)，可选规格模板见 [design-targets.example.json](../configs/design-targets.example.json)。材料、相、掺杂与工况来自每个 study；CaZrO3 案例条件不进入可移植定义的默认值。

新增结果合同分别保留原生 scheduler 终态、scientific_status、design_assessment。设计判定仅使用 met、not_met、insufficient_evidence、not_assessed、not_applicable；无规格时为 not_assessed，正常性能计算仍可完成。有效的未达标结果不属于工具失败，作业失败也不证明材料不达标。结果同时输出正常响应、方法/工况、误差、适用范围以及已有规格下的逐指标裕量，不将无损伤轨迹当作通过证明。

能力矩阵与 case_validation 是独立的轻量记录：前者保存能力状态、代表性案例、方法版本、证据和范围，后者保存 study_id、case_id、case_role、必需任务、独立参照、科学依据、结论与缺口。单次 scientific_status 不能替代系统或案例验收。Study 级 design_assessment 按 [需求文档第 4.3 节](design-requirements.md) 聚合：已证必需项不满足优先保留 not_met；否则必需证据不足为 insufficient_evidence；全部适用必需项有效满足才为 met。无规格或空必需集合不能自动通过。

统一结构/E/F/应力的输出形状，不抹掉 engine/method_set。适配器明确应力符号、单位、Voigt 顺序、电子数和原子顺序。相对能只在适用组成/电荷态/方法中比较，不跨赝势对齐裸总能。

VASP 只用于 P3 接线/对照。P4 验收后所有生产 DFT/标注 ABACUS；功能缺失就标明，不能自动回 VASP。数据按引擎/方法集分区。

新增科学记录按 [铁电与缺陷工作包](ferroelectric-and-defect-work-packages.md) 实现：铁电分支记录相态/工况依据、极化模型、场能量/力与电边界资格、P/D/微分响应及范围；缺陷分支记录组成/电荷、参考态、μ/EF、原始能、介电/势对齐/有限尺寸分项及来源。0.8.0 已实现缺陷化学势可行域、形成能/结合能数学后处理及真实中性任务绑定接口；这些函数不生产带电修正，也不授予材料科学资格。两者是领域计算与后处理任务，不另建主控框架。P4 基础资格、P5/P7 屏蔽数据、缺陷修正的依赖逐项登记，界面及铁电资格单列，已有中性 Ni 工程环不能代验。

## 7 Harness 三层证据

1. 行为案例：harness/cases/*.json 是 MLCC 自定义案例字段。MatterAI 声明 matterai.case.v2 标识，但当前源码未提供统一的案例内容执行器；接受 manifest 不等于案例通过。
2. 确定性检查：计量/补偿、原子/位移顺序、单位/应力、极化分支、能带桥与扩胞映射。模块实现时建立真实数值测试，不用匹配文案代替科学检查。
3. 真实集成：无计算命令→VASP relax/SCF→同几何 ABACUS 单点/独立弛豫→合格势 LAMMPS。各自验收，缺输出不报成功。

容差由具体方法/目标确定，不设“所有材料共用”的物理正确阈值。禁止防御性编程、哈希校验、自动重试、引擎回退、假结果与无意义通用验证框架。

### 7.1 验收对象分离

上面的三层是证据类型；另须区分系统能力、科学验证案例、具体设计三种验收对象。系统能力按实现和代表性验证证据登记；CaZrO3 是当前指定科学案例，Ni 是工程 fixture。某能力对 CaZrO3 不适用，只能关闭该案例的分支，不能标记整个能力已通过。其他材料案例按所需能力另行准备，不由本次规划自动提交数值任务。

新增验收覆盖正常性能的独立参照、同条件下的设计方案比较，以及给定目标后的满足/不满足/误差跨界/证据缺失/无目标情况。数值任务仍须物理收敛和真实数据；设计判定逻辑的单测输入不能充当材料科学证据。每个 study 按 selected_required_tasks 验收，系统总交付仍逐项核对能力矩阵。新增工作使用现有直接领域函数和薄适配器，不另建通用工作流框架。

## 8 求解器边界

LAMMPS 只输出局部原子/粒子行为与可标定的材料/界面响应；P12 只封装参数和条件性器件公式。没有 continuum.py、MOOSE 生成器或“LAMMPS FEM/相场”占位实现。真正连续分析另选求解器与实验标定；保留 Wsep、速率相关 MD 功与宏观 Gc 的区别。

## 9 当前执行记录（2026-10-21）

前文关于非桌面宿主“尚未验收”的句子保留为当时的架构基线；当前真实接线已经完成，范围仍限于本节所述的小闭环。

- `scripts/platform/headless-matterai-mcp.ts` 使用 Bundle registry、Agent/Skill profile、原版 `CodexCliRuntime` 和项目 `mcp.json`，通过薄 `spawn` 包装隔离全局配置并显式传入项目 MCP。只读会话只暴露 `mlcc_list_tasks`，sandbox 为 `read-only`，不启动数值任务。
- 私有 runtime 只复制实际需要的原版 runtime 文件，不修改两个上游树，不写桌面 trust，不启用 image proxy/hash/内容寻址缓存。原版 MCP 事件由 runtime 交付为 `provider.raw`，因此验收直接使用保存的 Codex JSONL。
- [v003 证据](../workspace/reports/h0/matterai-headless-provider-session-v021-list-tasks-v003.json) 显示同一原版会话 CLI 退出码 0、真实调用 `mcp__mlcc__mlcc_list_tasks` 并返回 23 条任务。v002 断言失败和首次配置错误仍保留在历史报告中。
- H0 acceptance 与 `plans/stages.json` 已记录为真实通过；P4 Ni 工程 jobs 32/33/34 均完成且小闭环通过，未形成 P4/H1 通过证据。当前指定科学验证案例为无掺杂 CaZrO3/Pnma，工况为 400–580 °C（673.15–853.15 K）、1 atm；该案例的生产 ABACUS 链仍受 P4 依赖约束，不代表通用系统仅支持这些材料和条件。

## 10 0.4.1 系统合同切片

Study条件、只读续接、显式结果依赖、ABACUS结果交付和Ni截断比较已实现并验证；不是完整通用生产建模或性质执行器。安装版48项测试及真实任务读取、原版非桌面runtime→MCP调用、job35调度与截断证据见[本轮验收](system-contracts-v041.md)。新增结果字段的实现范围以该文档为准；设计适配聚合、完整能力/案例验收及P5–P12仍待实现。七个MCP名称不变，任务列表新增next_action。

## 11 0.5.0 显式方法与能力参数

Study/Model/Method驱动ABACUS PW SCF/固定胞relax已实现，kpoints明确从方法输入。用户最新能力配置2³、scf_thr=1e-4在job37真实通过，不能替代精度资格。原生来源、task_id和静态条件归属检查共用；多元素/固定占据仅有输入测试。应变比较函数已有单测，真实三点标定尚未完成。安装与原版非桌面宿主证据见[0.5.0验收](system-contracts-v050.md)。

## 0.7.0 当前集成切片（历史记录）

方法资格、电子/DOS 和弹性规划/分析使用直接 Python/CLI 领域函数；七个 MCP 继续负责 Slurm 生命周期。UPF 头及科学数据在 workspace，Bundle 只携带代码/合同。资格检查重读原生头，电子和应力分析回溯同一任务的原生文件。没有新增后台服务、自动重试或引擎替代。全张量/剪切标定未实现时，分析输出 blocked 和 Cij=null；软件门通过不代表完整科学资格。安装、测试和调用证据见 [0.7.0验收](../workspace/reports/system-v070/acceptance.json)。

## 12 0.8.0 当前集成切片

0.8.0 沿用直接领域函数、轻量记录和薄 MCP 适配器。新增的模型派生记录父模型与原子谱系；弹性函数固定六个 Voigt 分量和 25-task 计划，重读原生来源并保留 blocked/Cij=null 的科学门；缺陷函数分开数学后处理和真实 ABACUS 中性任务适配，要求计量、方法、结构和结果谱系一致；性质交付与设计比较保持 `scientific_status`、`design_assessment` 分离。带电模型的结构保存不等于带电 ABACUS 执行器，FNV/eFNV 修正仍需独立生产者和介电屏蔽证据。

安装、测试和调用事实见 [0.8.0验收](../workspace/reports/system-v080/acceptance.json)；完整科学边界见 [0.8.0系统合同](system-contracts-v080.md)。没有产品规格时设计评估为 `not_assessed`；正常性能交付和异常机制分析按 study 选择的任务分别验收。下一切片是 P7 Phonopy 软件/力组装，ABACUS 原生力适配器单独验收；另一个交接线程已独占 LAMMPS 工作，本文不重复调度。
