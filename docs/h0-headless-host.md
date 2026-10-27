# H0 非桌面 MatterAI 宿主

本入口只覆盖非桌面 MatterAI 宿主的 Bundle/Agent/Skill → 原版 provider runtime → 项目 MCP 会话接线。它的验收范围是只读 `mlcc_list_tasks`；不准备、传输、提交、查询、取消或回传数值任务。

入口是 [`scripts/platform/headless-matterai-mcp.ts`](../scripts/platform/headless-matterai-mcp.ts)。它读取项目 `.zeus` registry 和 `mcp.json`，核对已安装 `mlcc-agent` Bundle 的 Agent、Python 解释器、Bundle entry、site/workspace 参数与授权工具，然后调用 core-engine 的 `startAgentRun` 和私有副本的原版 `CodexCliRuntime`。宿主只用 `node:child_process.spawn` 注入 `--ignore-user-config`，捕获实际命令参数、完整 prompt 参数、stdout JSONL 和退出码。

私有 runtime 位于 `workspace/runtime/matterai/packages/codex-runtime`。其中 `codex-cli-runtime.ts`、`codex-image-proxy.ts`、`matcore-identity.ts` 和 `scientific-task-policy.ts` 是从 MatterAI 上游直接复制的原版文件；宿主默认不启用 image proxy。MCP parser 位于 `workspace/runtime/matterai/packages/mcp-adapter`。上游树没有改动，也没有引入 trust、hash、内容寻址缓存或另一套 JSON-RPC/provider 循环。

CLI 会话使用 `--ignore-user-config` 隔离全局配置，Codex sandbox 为 `read-only`，`approval_policy=never`，并通过本版本实际支持的 `mcp_servers.mlcc.default_tools_approval_mode="approve"` 只放行已声明的只读 `mlcc_list_tasks`。没有启用其他 MCP server。项目配置核对出的实际命令是 `workspace/.venv/Scripts/python.exe`，entry 是已安装 Bundle 内的 `tools/mlcc_mcp.py`。

## 真实验收

实际执行命令如下；只运行过一次 provider 会话：

```powershell
workspace\runtime\matterai\node_modules\.bin\tsx.cmd scripts\platform\headless-matterai-mcp.ts `
  --workspace workspace `
  --report workspace\reports\h0\matterai-headless-provider-session-v021-list-tasks-v002.json
```

原始会话的 CLI 退出码为 0，provider session 为
`01a15c9f-37ba-7b60-9e2e-eeb248f810d0`。Codex 0.163 原始 JSONL 中的真实 MCP 记录是：

```text
record.item.type = mcp_tool_call
record.item.server = mlcc
record.item.tool = mlcc_list_tasks
record.item.status = in_progress → completed
```

完成结果的 `content` 文本解析出 23 个任务；原始输出还保留了结构化任务列表、状态和 scheduler job ID。原版 runtime 将这些 MCP 记录交付为 `provider.raw`，因此验收直接解析保存的原始 JSONL，不把 `tool.requested` 或助手总结当作工具调用证据。

`v002` 保留首次宿主断言失败及完整 stdout JSONL：[matterai-headless-provider-session-v021-list-tasks-v002.json](../workspace/reports/h0/matterai-headless-provider-session-v021-list-tasks-v002.json)。修正原始字段解析后，`v003` 从同一 provider session 的已保存 JSONL 重放，没有再次调用模型：[matterai-headless-provider-session-v021-list-tasks-v003.json](../workspace/reports/h0/matterai-headless-provider-session-v021-list-tasks-v003.json)。

首次配置试验错误地传入了 `default_tools_approval_mode="never"`；本机 CLI 明确报错，支持值为 `auto`、`prompt`、`writes`、`approve`。该错误没有重试或回退；后续入口使用实际支持的 `approve`，范围仍限制为本次只读 MCP 工具。

## 局部验证

- `headless-matterai-mcp.test.ts`：5/5 通过，包含对 v003 保存 JSONL 的回归重放、真实 `server/tool/status/result` 字段、非错误结果和 23 条 task 列表检查。
- 宿主 TypeScript 检查通过。
- 私有 `codex-runtime` 和 `mcp-adapter` TypeScript 检查通过。

这份验收不改变 `plans/stages.json`、`PLAN.md` 或根项目状态，也不代表任何新的 Slurm/VASP/ABACUS 数值作业已提交。

## 0.3.0 安装后真实复验（2026-10-21）

新增ABACUS薄适配器后，原版安装器启用 `mlcc-agent@0.3.0`，项目MCP入口指向该安装目录。用同一宿主入口、显式报告路径 `workspace/reports/h1/matterai-headless-provider-session-v030-list-tasks.json` 运行了一次新的真实provider会话。根代理复核原始 `item.completed/mcp_tool_call`：server=mlcc、tool=mlcc_list_tasks、status=completed、error=null，结果24条任务，CLI退出0；Bundle registry版本0.3.0。范围仍为只读模型→已安装MCP接线，不将列表返回的RUNNING当作数值收敛。

原0.2.1的v002失败断言、v003同会话重放及首次配置错误均保留；本节是0.3.0交付版本的新执行证据。

## 0.4.1 系统合同版本复验（2026-10-21）

原版非桌面宿主加载0.4.1，真实调用mlcc_list_tasks，provider原始item.completed事件返回26条记录和next_action，error=null、CLI退出0。见[原始会话报告](../workspace/reports/system-v041/matterai-headless-session.json)。安装版MCP另行查询job35得到COMPLETED/0:0；没有重跑H0数值任务。
