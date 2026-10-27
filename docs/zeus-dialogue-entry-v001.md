# Zeus 原生 MLCC 对话入口

当前结果：原生浏览器界面与真实安装绑定已通过，模型＋工具对话待 provider。实际截图、检查与边界见 `workspace/reports/zeus-dialogue-entry-v001/README.md`、`acceptance.json`（路径相对项目根）。Windows 已采用 `USERPROFILE/.mlcc-zeus/web-v001` 专用根并通过实际绑定；下方为实施合同，原待适配事项已由此状态更新。

2026-10-27。对应用户已核实的要求：页面应像光刻胶智能体一样以真实对话为主，同时保留已经开发的 MLCC 能力。

## 本轮交付与边界

- 沿原 `agents/catalog → openAgentNaming → AgentThread → startRun → SSE → Composer/Transcript`，不建第二套聊天服务或关键词路由。
- `agentName=mlcc`，安装能力来源为实际启用的 0.57.0。科学包和 0.56 回退不变；107 CLI、4 Skill、7 MCP 的原入口保留。
- 首次模型实验只调用现有 `mlcc_list_tasks`，读取保存任务。工具结果必须是真实返回；保存状态不能解释成实时 Slurm 状态。无新计算、查询调度器或重解析。
- 原任务／Study／参数查看器作为辅助 dialog，聊天组件保持挂载；返回、关闭或 Escape 回到原对话。参数的 null、false、单位、来源和原 JSON 保留。
- 首次入口只开放只读 MCP 工具，并不删除冻结包中其他六项工具。全面对话调度及后续 FEM 接入按已有迁移计划另行分阶段实施。

## 文件所有权

- root：`apps/server/src/agent`、`index.ts`、启动配置、根依赖、集成与浏览器验收。
- 原实施聊天：`apps/server/src/mlcc/` 中最薄安装配置解析 helper，返回既有 `AgentRuntimeMcpServer`；不新增第二 MCP server。
- 第三聊天：`apps/web` 原生聊天与保存数据 dialog。已完成 typecheck 并交回 root，后续仅定点修复。
- Luna：root 指定的 Windows workspace resolver 适配；不修改共享入口或科学目录。

## 真实验收

在 Edge 原认证页面选择 MLCC，发送中文请求列出保存任务；原 runtime 连接明确的 Responses 模型服务，展示真实 `mlcc_list_tasks` 工具活动和回答。随后从辅助查看器打开既有 CZO Study 与参数 JSON，关闭后回到同一对话。失败保留原错误，不以静态页面、模拟回答或类型检查代替模型验收。

## 当前依赖

Zeus process-backed Codex runtime 需要明确的 `OPENAI_BASE_URL`、`OPENAI_API_KEY` 与模型选择。当前 shell 未配置；Codex 账号登录不自动等于 Zeus provider。已向用户询问，密钥仅在本机环境中配置，不进入报告或日志。已定向核查三个已知光刻胶目录，没有发现可复用的模型启动配置。

Windows 工作目录需适配原 POSIX 权限逻辑；不得跳过原认证、目录归属和路径边界来冒充兼容。当前无真实模型运行证据，最终状态由后续验收记录更新。

本地 unpacked Agent 沿宿主已有无远程 deployment 时的 host 分支，直接读取当前启用版本的 Agent/Skill，并按原镜像函数放入项目工作区。没有新增远程发布 pin、摘要或快照校验。初版接线曾调用宿主 capability snapshot 取得摘要，审阅后已撤除；最终本地入口不再调用这条路径，远程原合同未变。

模型配置可由启动 shell／用户环境提供 `OPENAI_BASE_URL`、`OPENAI_API_KEY`、`ZEUS_CODEX_MODEL`，或放入私有 `config/model.local.env`（本轮未创建该密钥文件）。启动脚本只记录进程及日志路径，不打印配置值。使用本机已安装 Codex 原生 exe；`app-server --help` 已确认支持原运行时所需 `--stdio` 与 `--strict-config`，未发模型请求或读取其登录凭据。
