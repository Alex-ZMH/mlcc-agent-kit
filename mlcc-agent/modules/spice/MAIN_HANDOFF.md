# Main handoff — SPICE 0.2.0 and historical SI stage

## 2026-10-24 current Main receipt — supersedes the historical pending status

SPICE 0.2.0 registers ac_impedance_si / transient_si / ac_impedance / transient. The shared core1.0.0/catalog1.2.0 prerequisite is resolved; no second conversion table was added. Main's new acceptance has 25 module tests, 15 preflight rejections, 8 successful native tasks, three exactly equal SI/quantity raw-vector pairs, and real LLM execution with a hash-stable read-only follow-up. Physics and professional schemas are unchanged. See [full Main report](../../docs/verification/spice-closure-2026-10-24/report.md), [UNIT release sources](UNITS_SOURCES.json) and [machine index](../../docs/verification/spice-closure-2026-10-24.json).

Cold WSL startup may exceed the original 6-second preflight probe; the blocked attempts were preserved and environment readiness explicitly checked before the saved proposal was approved. Per-task sampling, material/device applicability and periodic steady state remain not_checked. The dated text below describes the original 2026-10-23 SI-only stage; it is retained as history, not a current blocker.

交付目录仅 `modules/spice/`。新增模块由自己的 module.json 自动发现，Main 无须中央注册。公共源码、Bundle、schema、其他模块、原型/其他实验均未修改；现场本来没有 Git 元数据，没有初始化或提交仓库。

可用操作：

- `ac_impedance_si`：单颗/受控并联线性 RLC 的真实 ngspice AC，含可选端口漏电、合法零 ESR/ESL，复阻抗/相位、采样最小值、插值虚部零点、分支 L/C 抵消和网络采样峰。
- `transient_si`：有限源 R、独立线路 L、基线 DC 工作点和规定有限沿的单次负载脉冲；可选无 C / 理想 C / 非理想 MLCC，输出带符号电流/功率、压降/过冲、有限脉冲恢复段 RMS、功率/能量诊断。

二者均 interface 1.0、queued + 显式 worker、真实计算证据，不是接口自检或 Python 参考公式替代求解。用户输入为明确固定 SI 兼容接口；尚不能称完整多单位交付。专业输入/output schemas、示例、方法 Skill、部署配置、轻量 tests、显式真实 harness、迁移矩阵和源码哈希均已提供。专业依赖仅在隔离 WSL 进程导入，无 FEM/PETSc/Core 依赖。

## 已完成的验收与证据

| 项目 | 实际状态 |
|---|---|
| 公共默认回归 | 90 项：89 pass，1 项 Windows symlink 权限 skip；基线/最终一致 |
| SPICE 默认轻量检查 | 21 项 pass，不调用 WSL/ngspice/在线模型 |
| check / describe / live preflight | 结构可发现、预检 ready；无计算副作用 |
| 完整新正式批次 | 27 Runtime→Windows Adapter→WSL→ngspice 分析成功 |
| 原阈值/新旧逐点对比 | 三阶段原判据全部通过，全部原生向量最大相对差 0，未放宽容差 |
| 查询/重复终态 worker | 27 个任务树 SHA256 前后不变 |
| 真实/结构负例 | 未知子电路、exit0 无输出、错终点/向量/起点/点数、损坏 raw 正确拒绝；多实例真实通过 |
| 理想无损精确共振 | 低层产生有限但病态数据；正式任务因数值对照失败而 failed，保留证据 |
| 漏电瞬态 | 最终目标小任务成功，ESR/漏电/总耗散分列，源/负载 CSV 电流独立回读 |
| full UNIT | blocked：公共 C/R/L kind 尚未发布；不宣称通过 |
| 材料/产品适用性、周期稳态 | not_checked / 范围外 |

完整结果、命令、阈值和开发故障说明见 [ACCEPTANCE.md](ACCEPTANCE.md)；27 个任务索引见 [index.json](work/runtime-qualification-20261023/index.json)，[原阈值与逐点对比](work/runtime-qualification-20261023/qualification/acceptance.json)。每个 task 的 artifacts 包含原始/canonical/solver 输入、UNIT 审计、真实 deck/raw/log/stdout/stderr/执行记录、CSV、PNG、metrics、独立回读、哈希和来源版本。Runtime/Agent 自动输出仍位于 Bundle outputs，不复制成伪新证据。

代表任务：

| 能力/边界 | task_id |
|---|---|
| 单颗细 AC | task-115abe589e2d4f2da364adc5e478e673 |
| 非理想 MLCC 细瞬态 | task-98d9a11d97a4475689750c8caf956898 |
| 并联细网格 | task-7c578346298f484d8d4903099db45f38 |
| 阻尼并联细网格 | task-6dd865de5bcf4571838d48fb0575675a |
| 正式理想 LC 病态失败 | task-a4da7c3383b14b3c90826bd1e55cff38 |
| 最终漏电能量/电流诊断 | task-9335bf1959504fad933839ca26d710bc |
| 真实 Agent 单次计算与同会话只读追问 | task-e38e0a7bda174eb8a5864c5f40e882cf |

环境已实查：Ubuntu-24.04；Python `/home/zhaoxiang/miniconda3/envs/spice-env/bin/python`，3.11.17；绝对 ngspice 路径 `/home/zhaoxiang/miniconda3/envs/spice-env/bin/ngspice`，41；NumPy2.4.6/Matplotlib3.11.2。未安装或升级任何环境。原型冻结前后均应保持 1185 文件一致；源证据在 SOURCES.json、final-audit.json。实际命令见 README 和 work 的 commands.json。原单次120s上限保留，客户端150s/适配器180s。

## Agent 对话与部署提醒

真实会话 `agent-fb38a8a651b344a0890aa118abc56e86`，使用固定 gpt-6.1-sol / low、正常登录、禁工具的现有公共宿主。仅发送已明确选中的合成示例、专业方法/schema 和结果，未发送源码/部署/凭据。**两轮真实闭环通过**：仅一次会话 task/worker、四次真实模型调用成功，后续 computed_this_turn=false，任务树哈希不变、记录输入与授权示例逐字段一致。最终核对见 `work/agent-e2e-current-host-20261023/acceptance.session-audit.json`。原 harness 把独立漏电目标任务误计入全目录新 task 而 FAIL，已保留并用实际会话事件归属复核，无模型/科学重跑。

完整真实对话：`outputs/agent/agent-fb38a8a651b344a0890aa118abc56e86/conversation.md` 和 `.json`，包括两轮原文、路由、宿主事件、结果解释与事实卡；不含内部推理。原始解释保留，模型把部分 limitations 称 warning 或说其事实卡没有独立输入一致性证据，不改变确定性 QC；验收脚本核对了记录输入。

首次在线尝试在启动前因公共 `config/local-codex.json` 指向已不存在的 Codex exe 而失败，未调用模型或建 task。当前机器的实际安装路径通过 Get-Command 发现，只写 `modules/spice/work/host.local.json`，未改公共配置/模型/供应商。Main 若需要其他模块使用现宿主，应自行审阅更新其本地绑定；不把机器路径当可移植默认值。原失败记录未删除。

## Main 后续必须处理

1. 在唯一公共 `mlcc/units.py` 发布电容、电阻、电感 kind/canonical 和有限词表/别名，补公共兼容回归；详见 [INTERFACE_PROPOSAL.md](INTERFACE_PROPOSAL.md)。当前 core1.0.0/catalog1.1.0 确认缺失。SPICE 未获得修改公共核心权限，没有复制倍率表。
2. 发布后按 [UNITS_DESIGN.md](UNITS_DESIGN.md)、[UNITS_ACCEPTANCE.md](UNITS_ACCEPTANCE.md) 完成 quantity 准入、全链路等价真实任务和拒绝验收，再登记已准备的 `ac_impedance`/`transient`，更新此阶段状态。当前 `_si` 两操作保持明确兼容语义。
3. 审阅本模块后由 Main 更新公共 docs/v1-scope、acceptance、v1-status 与总账。应记录“SI 真计算及数值迁移通过；完整 UNIT 待公共扩展”，不要沿用总账旧“SPICE 未接入”，也不要提前写“完整多单位/科学产品验收通过”。
4. 发布时固定源码 Bundle/部署配置并保留源清单；公共 queued 快照未冻结专业源码/部署内容。WSL 客户端超时仍声明原生终止未知，不自动重试。本轮无新调度/取消接口。

不需要先做材料标定或尺度互通才能接收当前数值开发成果；也不能把这些未实施项改为 passed。公共 UNIT 缺口解决后才可声称本次开发 prompt 的多单位交付完整。
