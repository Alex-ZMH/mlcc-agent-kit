# H0 / P0 MatterAI Bundle 实测记录

> 2026-10-21 范围更正：下文 2026-10-20 的桌面 trust 调查是历史记录，仅适用于 Electron 宿主。将其作为整个 H0 的必需入口是错误的，已撤销“等待用户提供桌面路径”；当前剩余项为非桌面宿主 MCP 接入。见 [运行入口核查](matterai-runtime-scope.md)。原始执行事实不变。

日期：2026-10-20（Asia/Shanghai）  
范围：P0.01–P0.05、P0.09、P0.11 的独立 Bundle 安装与真实 registry 发现。计算工具、MCP 服务和 P1/P3 数值任务仍未宣称完成。

## 运行副本与边界

参考树 `MatterAI-main/MatterAI-main` 没有 `node_modules`。遵循项目规则，在
`workspace/runtime/matterai/` 建立了隔离运行副本：复制平台安装器
`scripts/install-bundle.mjs`、`@zeus/core-engine`（含 Bundle registry）和
`@zeus/shared-types` 的源文件，运行时依赖安装到该副本自己的 `node_modules`。
没有在两个上游目录安装依赖，也没有修改上游文件。

实际运行环境：

| 项目 | 实测值 |
| --- | --- |
| Node | `v24.19.0` |
| npm | `11.17.0` |
| tsx | `tsx v4.23.15 node v24.19.0` |
| 运行副本 | `D:\project\mlcc\workspace\runtime\matterai` |
| 原版安装器 | `workspace/runtime/matterai/scripts/install-bundle.mjs` |
| registry 源 | `workspace/runtime/matterai/packages/core-engine/src/bundles/bundle-registry.ts` |
| 安装目标 | 隔离沙盒 `workspace/runtime/matterai/project` 与实际项目 `workspace`（分别验收） |

安装依赖命令（仅运行副本）：

```powershell
cd D:\project\mlcc\workspace\runtime\matterai
npm install --ignore-scripts --no-audit --no-fund
```

结果：退出码 `0`，`added 8 packages in 46s`。

## Bundle 契约对照（0.1.0 首次快照）

平台安装器使用 `parseBundleManifest` 和 `loadBundleRuntimeRegistry`，实际校验了
`matterai.bundle.v2`、精确三段版本、Agent 入口、四个 Skill、harness 格式和风险字段。
MLCC 源清单与平台要求的关键值如下：

| 字段 | MLCC 实际值 | 结果 |
| --- | --- | --- |
| `schemaVersion` | `matterai.bundle.v2` | 通过安装器和 registry 校验 |
| `name` / `version` | `mlcc-agent` / `0.1.0` | 通过；目标版本目录不可覆盖 |
| `agent.name` / `entry` | `mlcc` / `agents/mlcc/AGENT.md` | registry 发现 `mlcc` |
| `agent.skills` | `model-mlcc-structures`, `run-mlcc-dft`, `compute-mlcc-properties`, `run-mlcc-md` | 四项全部发现 |
| Agent frontmatter | 非空 `title`、`description`、4 条 `starters` | registry 返回并保留 |
| `mcpServers` | `[]` | 无计算工具权限；不宣称 MCP 可用 |
| `requirements.capabilities` | `chat`, `files` | 文档型能力 |
| `harness.format` | `matterai.case.v2` | 8 个案例随 Bundle 安装；无统一平台案例执行器 |
| `risk` | `docs-only` | 与当前能力范围一致 |

## 隔离沙盒安装（第一目标）

首次执行时目标目录不存在，平台原版命令先明确拒绝不存在的 workspace（退出码
`1`），随后创建目标目录后重跑。该失败记录保留在
`workspace/reports/h0-p0/installer-output.txt`；没有自动重试逻辑。

成功命令：

```powershell
cd D:\project\mlcc\workspace\runtime\matterai
npm run bundle:install -- D:\project\mlcc\mlcc-agent `
  --workspace D:\project\mlcc\workspace\runtime\matterai\project --enable
```

真实 stdout：

```text
Installed mlcc-agent@0.1.0
  D:\project\mlcc\workspace\runtime\matterai\project\.zeus\bundles\mlcc-agent\0.1.0
Enabled for this project in .zeus/bundles.json.
```

成功退出码：`0`。安装器生成的启用配置为：

```json
{
  "bundles": [
    { "name": "mlcc-agent", "version": "0.1.0", "enabled": true }
  ]
}
```

安装目录包含 `bundle.json`、Agent、四项 Skill、8 个 harness 案例以及当时源目录中
已有的 MLCC Python 源/测试；运行结果仍留在私有 workspace，不进入 Bundle 源码。

## 实际项目 workspace 安装（第二目标）

在隔离运行副本已完成依赖安装后，使用同一份 MatterAI 原版安装器，把当前
`mlcc-agent@0.1.0` 安装到真正的项目 workspace `D:\project\mlcc\workspace`。该目录在
执行前已存在，因此没有创建新的项目目录，也没有覆盖隔离沙盒中的旧安装。命令执行日为
2026-10-20（Asia/Shanghai）；安装启用文件的文件系统时间戳为 `16:06:58`，随后在
`16:07:07` 完成 registry 探测。

```powershell
cd D:\project\mlcc\workspace\runtime\matterai
npm run bundle:install -- D:\project\mlcc\mlcc-agent `
  --workspace D:\project\mlcc\workspace --enable
```

原版安装器 stdout 与退出码：

```text
Installed mlcc-agent@0.1.0
  D:\project\mlcc\workspace\.zeus\bundles\mlcc-agent\0.1.0
Enabled for this project in .zeus/bundles.json.
```

退出码：`0`。实际项目启用文件为：

```json
{
  "bundles": [
    { "name": "mlcc-agent", "version": "0.1.0", "enabled": true }
  ]
}
```

两个目标的安装与验收时间、目录和状态保持分开：

| 目标 | 安装目录 | `.zeus/bundles.json` 时间戳 | registry 状态 |
| --- | --- | --- | --- |
| 隔离沙盒 | `workspace/runtime/matterai/project/.zeus/bundles/mlcc-agent/0.1.0` | `16:03:06` | `0.1.0`、启用、4 Skill |
| 实际项目 | `workspace/.zeus/bundles/mlcc-agent/0.1.0` | `16:06:58` | `0.1.0`、启用、4 Skill |

这两个目录都是同一版本在不同 workspace 的安装快照；安装成功不意味着后续并行编辑会
自动进入已安装快照。按安装器的版本不可覆盖约束，若源内容需要再次装载，应先形成新的
明确版本，而不是覆盖 `0.1.0`。

## 两个目标的真实 registry 发现（0.1.0 首次快照）

使用副本的 `@zeus/core-engine` registry 读取安装目标，而不是自行扫描目录：

```powershell
cd D:\project\mlcc\workspace\runtime\matterai
npx tsx -e "import { loadBundleRuntimeRegistry } from '@zeus/core-engine'; ..."
```

完整探测命令及 stdout 见 `workspace/reports/h0-p0/registry-output.txt`。关键结果：

```text
bundleCount=1
bundle=mlcc-agent@0.1.0
agent=mlcc
agentTitle=MLCC 原子建模与界面仿真智能体
agentEnabled=true
starters=["规划顺电与铁电材料的选相掺杂模型","打通 VASP 并迁移到 ABACUS","比较陶瓷和 Ni 的局部界面失配","设计保留高分子层与临时粘结剂的对照"]
skills=["model-mlcc-structures","run-mlcc-dft","compute-mlcc-properties","run-mlcc-md"]
discoveredSkillTitles=["显式原子建模","同源扩胞与局部界面 MD","四条微观性质链","VASP 接线与 ABACUS 生产迁移"]
mcpServers=[]
```

registry 同时为四项 Skill 生成了 Bundle 版本隔离的运行时名称，并将它们全部标记为
`enabled=true`。这证明 P0 的能力装载/发现门 G0 已有真实证据；它不证明 VASP、ABACUS、
LAMMPS、MPI、Slurm runner 或任何 MCP 工具可调用。

同样的 `loadBundleRuntimeRegistry` 探测随后以实际项目的
`workspace/.zeus/bundles` 和 `workspace/.zeus/bundles.json` 为输入，结果为：

```text
target=workspace
bundleCount=1
bundle=mlcc-agent@0.1.0
agent=mlcc
agentEnabled=true
skills=["model-mlcc-structures","run-mlcc-dft","compute-mlcc-properties","run-mlcc-md"]
discoveredSkillTitles=["显式原子建模","同源扩胞与局部界面 MD","四条微观性质链","VASP 接线与 ABACUS 生产迁移"]
mcpServers=[]
P0 real-workspace registry assertions passed
```

完整命令和 stdout 保存在 `workspace/reports/h0-p0/real-workspace-registry-output.txt`；
隔离沙盒 registry 输出仍保存在 `workspace/reports/h0-p0/registry-output.txt`。

## 0.2.0 实际 workspace 更新装载与 registry 发现

根代理随后使用同一隔离运行副本的原版安装器，将明确的新版本
`mlcc-agent@0.2.0` 安装并启用到实际项目 `D:\project\mlcc\workspace`。这次安装没有覆盖
`0.1.0`：实际 workspace 的 Bundle 目录同时保留两个版本快照，当前
`.zeus/bundles.json` 选择 `0.2.0`。

安装输出和退出码见 [`installer-v020-output.txt`](../workspace/reports/h0-p0/installer-v020-output.txt)：

```text
Installed mlcc-agent@0.2.0
  D:\project\mlcc\workspace\.zeus\bundles\mlcc-agent\0.2.0
Enabled for this project in .zeus/bundles.json.
```

退出码：`0`。当前实际项目启用配置为：

```json
{
  "bundles": [
    { "name": "mlcc-agent", "version": "0.2.0", "enabled": true }
  ]
}
```

使用实际隔离 runtime 的 `workspace/runtime/matterai/node_modules/.bin/tsx.cmd` 调用
`@zeus/core-engine` 的 `loadBundleRuntimeRegistry`，没有从上游目录执行 `npx`，也没有
自行扫描 Bundle 目录。完整命令、断言和 stdout 见
[`registry-v020-output.txt`](../workspace/reports/h0-p0/registry-v020-output.txt)。真实结果：

```text
target=workspace
bundleCount=1
bundle=mlcc-agent@0.2.0
agent=mlcc
agentEnabled=true
skills=["model-mlcc-structures","run-mlcc-dft","compute-mlcc-properties","run-mlcc-md"]
mcpServerName=mlcc
mcpEntry=tools/mlcc_mcp.py
mcpArgs=["--site","zeus://workspace/current/configs/site.v100.json","--workspace","zeus://workspace/current"]
mcpAllowedTools=["mlcc_list_tasks","mlcc_prepare_calculation","mlcc_transfer_calculation","mlcc_submit_calculation","mlcc_query_calculation","mlcc_cancel_calculation","mlcc_collect_calculation"]
mcpAllowedToolCount=7
P0 0.2.0 real-workspace registry assertions passed
Exit code: 0
```

这次 registry 发现证明 `0.2.0` 的实际项目 Bundle 已启用 1 个 stdio Python server，声明
7 个允许工具、workspace-write 文件权限和 network 权限；它只证明 Bundle registry 的
解析和发现，不证明 stdio 子进程已经握手、信任 review 已批准或 `tools/list` 已成功。
前文 `0.1.0` 的 `mcpServers=[]`、4 Skill 和旧启用版本仍作为历史安装快照证据保留，不能
与此前 `0.2.0` 的 MCP 声明混写。

## `.zeus/mcp.json` 与信任/允许工具合同

只读检查脚本为 [`scripts/platform/inspect-mlcc-runtime.ts`](../scripts/platform/inspect-mlcc-runtime.ts)。
它只读取项目的 `.zeus/bundles.json`、Bundle 目录和 `.zeus/mcp.json`，不会注册服务、启动
MCP server 或修改配置。前文对两个 `0.1.0` 安装目标的检查显示 `.zeus/mcp.json` 均不存在，
输出 `mcpServers=[]`；这与当时 `0.1.0` Bundle registry 返回的 `mcpServers=[]` 一致。
在 `0.2.0` 阶段 Bundle registry 已声明 `mlcc` server，项目 `.zeus/mcp.json` 和真实
stdio `tools/list` 已有历史证据；原生 trust 审批仍按平台流程单独记录，不能把 registry
声明本身当作 trust 成功。当前启用版本由后面的 0.2.1 记录覆盖。

### 历史 0.2.0 项目配置解析与已安装 stdio 证据

根代理随后在实际 workspace 写入了真实的 `workspace/.zeus/mcp.json`。本次只读配置验收
使用隔离 runtime 的
`workspace/runtime/matterai/node_modules/.bin/tsx.cmd`，直接动态导入上游
`MatterAI-main/MatterAI-main/packages/mcp-adapter/src/zeus-mcp-config.ts` 的
`parseZeusMcpConfig`，没有调用 trust、fingerprint 或执行 gateway。完整原始配置和解析结果
见 [`mcp-config-v020-parse.json`](../workspace/reports/h0-p0/mcp-config-v020-parse.json)。

原函数返回 1 个 `stdio` server `mlcc`，保留 7 个 `allowedTools`，并原样保留以下
`zeus://workspace/current` 字符串：

```text
command = zeus://workspace/current/.venv/Scripts/python.exe
args[0] = zeus://workspace/current/.zeus/bundles/mlcc-agent/0.2.0/tools/mlcc_mcp.py
args[2] = zeus://workspace/current/configs/site.v100.json
args[4] = zeus://workspace/current
```

因此 `parseZeusMcpConfig` 本身只做配置语法/字段解析，不展开 workspace 占位符；证据中
明确记录 `placeholderExpansion.expandedWorkspaceRoot=null`。占位符的实际展开属于后续
MatterAI runtime 装载/stdio 启动层，不能把解析函数的原始返回值误称为已展开路径。

独立的已安装 v0.2.0 stdio probe 已完成 initialize、`tools/list` 和
`mlcc_list_tasks` 调用；原始 JSON 见
[`mcp-installed-v020-probe.json`](../workspace/reports/h0/mcp-installed-v020-probe.json)。
该报告显示 server `mlcc-agent@0.2.0`、协议 `2025-06-18`，`tools/list` 返回 7 个工具，
`mlcc_list_tasks` 返回当前 workspace 的任务状态和 Slurm job ID。配置解析证据本身没有
启动 Electron、写 truststore 或进行原生 trust review；原生 trust 状态仍按平台流程单独
保留为待验收项。

上游 MatterAI 源码给出的配置合同为：`.zeus/mcp.json` 顶层必须有 `servers` 对象；stdio
项使用 `type`, `command`, `args`, `allowedTools`，远程项使用 `type`、`url`、
`allowedTools`；服务器名和允许工具名遵守 `[A-Za-z0-9_-]{1,80}`。来源：
`packages/mcp-adapter/src/zeus-mcp-config.ts:188-237` 和
`packages/shared-types/src/agent.ts:457-492`。stdio 的
`zeus://workspace/current` 占位符在装载时展开为 workspace 绝对路径，来源：
`apps/desktop/electron/runtime/runtime-container.ts:309-335`。
headless 装载路径也对 `command` 和每个 `args` 做同样展开，来源：
`packages/local-runtime/src/headless-run.ts:212-242,328-350`。当前合同没有 stdio `env` 或
`cwd` 配置字段：stdio 子进程实际以规范化 workspace 为 `cwd`，并使用固定的最小环境键表，
来源：`apps/desktop/electron/ipc/agent-ipc.ts:1234-1256` 和
`apps/desktop/electron/ipc/mcp-execution-gate.ts:100-133`。该最小表不包含 `PYTHONPATH`。
上游 headless 单测 `packages/local-runtime/src/headless-run.test.ts:876-895` 直接断言：只有
stdio `command`/`args` 会把占位符替换为 workspace 路径，HTTP URL 不变；环境过滤单测
`apps/desktop/electron/ipc/mcp-execution-gate.test.ts:290-308` 也确认注入变量不会传给子进程。
因此本机现状只能确认占位符会解析到 `D:\project\mlcc\workspace`（例如
`zeus://workspace/current/mlcc_agent/mcp_server.py` 会解析到该 workspace 下的相对路径）；
不能把 `PYTHONPATH` 或任意 cwd 作为 `.zeus/mcp.json` 字段写入并宣称已生效。site override
需要待真实服务与平台支持路径确认后，再用实际 `.venv` 可执行文件/包装器验证。

桌面运行时把配置解析出的 server 交给信任门；有效结果必须是配置 server 的有序、精确子集，
来源：`apps/desktop/electron/runtime/runtime-container.ts:383-435,946-977`。信任摘要包括
workspace、server、transport、stdio command/args/cwd、`minimal-v1` 环境策略、
`allowedTools` 和能力集合；stdio 能力是 `local-process`、`filesystem`、`network`，来源：
`apps/desktop/electron/runtime/mcp-trust-policy.ts:47-49,540-573`。首次使用、配置变化、撤销
等状态在 `McpExecutionGate` 中要求 review；未通过信任时执行分别保留为
`mcp_execution_blocked`、`mcp_consent_stale` 或 `mcp_review_required`，来源：
`apps/desktop/electron/ipc/mcp-execution-gate.ts:307-328,434-470`。

信任记录文件名是 `mcp-trust-v1.json`，桌面主进程把它放在 Electron `userDataRoot`，不在
项目 `.zeus` 下；来源：`apps/desktop/electron/runtime/mcp-trust-store.ts:28,659-687` 和
`apps/desktop/electron/main.ts:346,412-414`。前述 `0.1.0` 快照只证明当时的配置/Bundle
没有声明 MCP；在 `0.2.0` 阶段 registry 已发现 `mlcc` 声明，且项目
`.zeus/mcp.json` 已存在，独立 stdio probe 已证实 initialize/`tools/list`/`mlcc_list_tasks`
成功；这不等于原生 trust review 已批准。允许工具还会由 gateway
按 configured 或 `safe-read-only` 暴露，来源：`packages/mcp-adapter/src/mcp-gateway.ts:61-103`。

项目配置也没有隐藏的 site MCP override：`workspace/configs/site.v100.json` 没有 `mcp` 键；
参考配置 `configs/site.v100.example.json` 的 `mcp.endpoint` 为 `null`、状态为
`not_deployed`。因此当前没有经 MatterAI 原生 trust review 批准的 trusted server；独立
stdio probe 的真实握手证据见上文，不把两条路径混为一谈。

为需要原生 trust 路径的后续验收保留 probe 是 [`scripts/platform/probe-matterai-mcp.ts`](../scripts/platform/probe-matterai-mcp.ts)。
它在配置存在时调用 MatterAI 的 `loadZeusMcpServers`、`McpExecutionGate` 和
`listMcpTools`，因此会复用平台的 `.zeus/mcp.json` 解析、信任门和 stdio
initialize/`tools/list` 传输。它先用平台的 security summary 与 `McpTrustStore.find` 做
精确的只读信任查找，再调用 `McpExecutionGate.requireTrustedServer`；不调用
`evaluateSnapshot`、approve、deriveReduction、revoke，不写入 truststore，也不自行声明
trusted server。未信任时退出码为 `3`，打印正式入口
`renderer zeus.mcp.review -> IPC mcp:review -> McpExecutionGate.reviewWithNativeDialog`，
并在确认前不启动子进程。此前无配置运行结果和使用命令见
`workspace/reports/h0-p0/mcp-probe-contract.txt`；当前实际 stdio 握手和
`mlcc_list_tasks` 结果见 `workspace/reports/h0/mcp-installed-v020-probe.json`。
probe 不硬编码 `tools/mlcc_mcp.py` 或 tool 名称；当前 `slurm_runner` 已提供该入口，命令、
参数和实际工具清单仍必须来自 `.zeus/mcp.json` 与真实握手。

## 0.2.1 实际 workspace 更新装载与最终 P0 registry/配置验收

根代理已将修复绝对任务路径的代码冻结为 `mlcc-agent@0.2.1`，并使用同一份 MatterAI
原版安装器安装到实际项目 workspace。安装输出和退出码见
[`installer-v021-output.txt`](../workspace/reports/h0-p0/installer-v021-output.txt)：

```text
Installed mlcc-agent@0.2.1
  D:\project\mlcc\workspace\.zeus\bundles\mlcc-agent\0.2.1
Enabled for this project in .zeus/bundles.json.
```

退出码：`0`。当前实际项目启用配置为：

```json
{
  "bundles": [
    { "name": "mlcc-agent", "version": "0.2.1", "enabled": true }
  ]
}
```

0.2.1 的唯一代码修复是 `mlcc-agent/src/mlcc/site_runner.py` 的 `prepare()` 在保存
`local_workdir` 和 `prepared_script` 前对任务目录执行 `Path.resolve()`。配套测试验证了
CLI 使用相对 task 路径时，切换 cwd 后仍指向同一绝对目录；没有修改 Bundle 契约、Agent、
Skill、MCP 工具名、调度策略或旧 task 数据。冻结版本的 13 个 Python 单测全部通过，原始
输出见 [`unit-tests-v021.txt`](../workspace/reports/h0/unit-tests-v021.txt)：
`13 passed, 11 warnings in 1.11s`。

### 0.2.1 原版 registry 实际发现

使用隔离 runtime 的
`workspace/runtime/matterai/node_modules/.bin/tsx.cmd`，直接调用原版
`@zeus/core-engine` 的 `loadBundleRuntimeRegistry`，输入真实项目的
`workspace/.zeus/bundles` 和 `workspace/.zeus/bundles.json`；没有从上游目录运行 `npx`，
没有调用 trust、fingerprint 或其他安全批准入口。完整输出见
[`registry-v021-output.txt`](../workspace/reports/h0-p0/registry-v021-output.txt)。实际结果：

```text
target=workspace
bundleCount=1
bundle=mlcc-agent@0.2.1
agent=mlcc
agentEnabled=true
skills=4 discovered
mcpServerName=mlcc
mcpEntry=tools/mlcc_mcp.py
mcpAllowedToolCount=7
P0 0.2.1 real-workspace registry assertions passed
Exit code: 0
```

registry 同时发现 4 个 Skill 和 1 个 `stdio` Python server，允许工具仍为既有的 7 个
`mlcc_*` 工具；这只证明 0.2.1 Bundle 的实际安装、启用和 registry 发现，不证明新的
MCP stdio 进程已经由 MatterAI native trust 批准，也不替代后续 installed MCP→Slurm
调用验收。

### 0.2.1 `.zeus/mcp.json` 纯配置解析

当前真实配置已指向 0.2.1：

```text
command = zeus://workspace/current/.venv/Scripts/python.exe
args[0] = zeus://workspace/current/.zeus/bundles/mlcc-agent/0.2.1/tools/mlcc_mcp.py
args[2] = zeus://workspace/current/configs/site.v100.json
args[4] = zeus://workspace/current
allowedTools = 7
```

使用隔离 runtime 的 `tsx.cmd` 动态导入上游
`MatterAI-main/MatterAI-main/packages/mcp-adapter/src/zeus-mcp-config.ts` 的
`parseZeusMcpConfig`，只读取并解析当前配置；没有启动 stdio、调用 `tools/list`、调用
trust/fingerprint/hash 或启动 Electron。完整证据见
[`mcp-config-v021-parse.json`](../workspace/reports/h0-p0/mcp-config-v021-parse.json)。
解析结果为 1 个 `stdio` 的 `mlcc` server、7 个允许工具，`zeus://workspace/current`
在 parser 返回值中保持未展开，`expandedWorkspaceRoot=null`；这不是已完成 native trust
审查的声明。随后 0.2.1 已安装入口实际完成 initialize、7 项 tools/list 和
`mlcc_query_calculation(h0-ni-strainplus-v005)`，返回原生 Slurm job 29 的
`COMPLETED/0:0`。证据：[installed MCP→Slurm](../workspace/reports/h0/mcp-installed-v021-query-job29.json)。
该命令直接启动已安装 stdio 服务；非桌面宿主 MCP 接入仍待验收；原先要求桌面入口的判断已于 2026-10-21 撤销。

## Harness 与剩余边界

随 Bundle 安装的案例为：`project-discovery`、`phase-and-dopants`、`vasp-roundtrip`、
`abacus-migration`、`four-route-dependencies`、`same-parent-expansion`、
`MD-boundary-and-interfaces`、`device-handoff`。当前本地 MatterAI 源只提供案例字段/格式
校验，没有统一的案例内容执行器；本记录不把 manifest 接受误报成案例通过。项目局部测试和
真实 H0 断言的案例状态保存在 `workspace/reports/harness/h0-results.json`，科学运行记录
不写入 Bundle 安装模板。

未做的事情：没有通过原生 review 批准或手工注册 MCP trust、没有复制 ACS 服务、没有安装 PostgreSQL/Web/Worker、没有修改
上游树。版本发布和最终阶段状态由主代理根据实际证据更新。`inspect-mlcc-runtime.ts` 的
`trustState=not-created-by-this-read-only-inspection` 仅表示本次检查没有创建桌面信任记录；
它不替代桌面主进程的真实 review/approval 流程。

## 当前启用0.3.0（2026-10-21）

新增ABACUS 3.10.1 Ni PW直接输入/解析，原版安装器已在实际workspace安装并启用0.3.0；历史0.2.1安装目录不改写。证据：`workspace/reports/h1/installer-v030-output.txt`、`unit-tests-v030.txt`（20项通过）。新安装版本通过原版MatterAI runtime真实模型调用mlcc_list_tasks（24条，CLI0）及独立MCP→Slurm job33查询（COMPLETED/0:0）；见 [宿主记录](h0-headless-host.md) 与 `workspace/reports/h1/mcp-installed-v030-query-job33.json`。仍为1 Agent、4 Skill、7个MCP生命周期工具，没有宣称增加了生产性质或MD能力。
