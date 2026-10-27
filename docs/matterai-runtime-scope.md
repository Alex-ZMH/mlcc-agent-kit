# MatterAI 运行入口与 H0 验收更正

温度条件更新（2026-10-21）：本文中的330/400 K属于当时记录，已由[烧制温区v002](temperature-conditions-v002.md)替代；历史工程证据保持。当前为CZO 400–580 °C、BTO 800–1350 °C。

日期：2026-10-21（Asia/Shanghai）。用户指出 MatterAI 不是桌面应用。
此前把本地参考树的 Electron 信任流程推广为 MLCC 的必需入口，是项目验收范围判断错误。
撤销“等待用户提供桌面启动路径”；本项目不要求安装或启动 Electron。

当前结果：H0已通过；原版runtime真实调用及0.3.0复验见 [非桌面宿主记录](h0-headless-host.md)。以下范围审计保留当时的错误和更正背景。

## 本地源码依据

- `MatterAI-main/MatterAI-main/README.md:3,82` 描述了参考树里的桌面实现，但这不能决定本项目必须采用该入口。
- `packages/local-runtime/package.json` 声明 `zeus-run`，入口为 `bin/zeus-run.mjs`；它加载 `src/main.ts` 的 `runHeadlessCli`。
- `packages/local-runtime/src/headless-run.ts:62-76` 提供可注入的 `resolveTrustedMcpServers`；`:340-359` 解析项目配置并取得受信任的配置子集，未注入解析器时默认有效 MCP 列表为空。
- `packages/local-runtime/src/headless-run.ts:398-402` 明确 headless 没有审批 broker，`approvalPolicy=never`。这不等于所有配置工具自动获准。
- 同文件 `:393-405` 的 `AgentRunInput.runtimeSettings` 没有传入 `mcpServers`，`:436` 的执行调用只使用 `plan.input`；`main.ts:58` 也没有注入授权解析器。因此仅提供 resolver 仍不能宣称这版 CLI 已将 MCP 接到模型会话，需要落实完整宿主调用链。
- `packages/mcp-adapter/src/mcp-gateway.ts:74-107` 的 gateway 提供工具配置和允许工具名映射；该类本身没有启动传输、执行工具或完成宿主授权。
- `apps/desktop/electron/ipc/mcp-execution-gate.ts` 的原生 dialog/truststore 属于桌面实现。已有 `scripts/platform/probe-matterai-mcp.ts` 只适用于这条可选路径，不是通用 H0 门。

以上路径除 README 外均相对本地 MatterAI 参考树；本次只读检查，没有修改上游、运行其安装/重启脚本、写信任记录或执行哈希校验。

## 修正后的验收范围

已完成的原版 Bundle 安装/registry、配置解析、已安装 stdio 服务握手、7 个工具发现及实际 Slurm 查询证据仍然成立。独立 MCP probe 不等于宿主会话接入；源码存在 headless 也不等于本机已跑通 headless 会话。

P1 剩余项更名为 **非桌面宿主的 MCP 授权解析与实际调用集成**。这是待落实的宿主接入工作，不是缺少桌面应用造成的用户阻塞。后续按实际采用的非桌面入口实现薄接线，使用其有效工具集合进行真实调用验收，不伪造 trusted record，不注入“无条件信任全部配置”的解析器。

完整 H0 保持 `false`，只更正阻塞原因，不凭本次文档修正增加完成项。P4 的 Ni 工程迁移准备不依赖桌面安装；生产温度等科学输入仍按原记录待定。

本次没有启动任何数值任务，没有新增 Slurm job ID；既有任务、退出状态、物理验收和原始失败日志不变。
本次属于源码与验收范围审计，没有执行 headless provider 会话，也没有将 fake runtime 作为真实接入证据。

## 当前执行记录（2026-10-21）

上面的“完整 H0 保持 `false`”和“没有执行 headless provider 会话”是本文件审计时的历史记录，保留其原始语境；随后已完成真实的非桌面宿主接线与验收。

- 当前宿主从已安装 Bundle registry、Agent/Skill profile 进入原版 `CodexCliRuntime`，再连接项目声明且路径核对通过的 MLCC MCP。会话隔离全局用户配置，使用只读 sandbox，仅授权 `mlcc_list_tasks`。
- [v003 报告](../workspace/reports/h0/matterai-headless-provider-session-v021-list-tasks-v003.json) 关联同一 provider session，记录 CLI 退出码 0、真实 `mcp__mlcc__mlcc_list_tasks` 的 `item.started/item.completed` 原始事件和 23 条任务结果。原版 mapper 的 MCP 事件仍是 `provider.raw`，未伪造 `tool.requested`。
- v002 断言失败、首次不支持 `default_tools_approval_mode="never"` 的配置错误和 direct stdio 范围报告均保留；v003 是同一会话 JSONL 的解析 resolution，没有重跑模型、没有覆盖失败为成功。
- H0 acceptance 与 `plans/stages.json` 已真实记录为通过。P4 Ni工程jobs32/33/34均完成且小闭环通过，P4/H1 仍未通过。生产研究参数已确认：无掺杂 CaZrO3、正交 Pnma、330 K、400 K、1 atm；这不替代 P4 的 ABACUS 迁移和生产方法验收。
