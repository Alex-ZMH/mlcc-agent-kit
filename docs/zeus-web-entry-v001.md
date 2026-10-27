# Zeus 网页入口首次接入

2026-10-27 用户已授权三个既有窗口并行实施，复用 MLCC 0.57 Bundle、MCP 和计算链路。首轮交付：网页选择 MLCC、查询已有任务、展示已有 Study 和领域参数 JSON。每小时监督，有实际功能交付再汇报。

## 首次完成边界

实际启动 Zeus 网页宿主，浏览器选择已安装的 MLCC 0.57，列出真实 TaskRecord 并调用现有 MCP 查询，打开真实 Study 和参数 JSON。保存网页地址、启动/停止命令及这一条浏览器流程证据，即完成首轮功能。原生计算、解析、统计全部复用，不提交或重跑 DFT/MD/NEB/训练。

当前 `workspace/runtime/matterai/package.json` 仅有 `bundle:install`，已有 core-engine/mcp-adapter/codex-runtime/shared-types。`MatterAI-main/MatterAI-main/` 中现成 apps/web、apps/server、packages/ui 等仅作只读源，复制所需文件到 MLCC 私有运行时后接线；不得修改上游。复用真实 Zeus 界面、Agent 选择和宿主能力，不创建独立演示页冒称已接入 Zeus。

MLCC 0.57/0.56 计算软件保持现有绑定。本批可以增加独立网页运行时文件和配置；仅确有 MCP 查询缺陷才作最薄领域修改，不为网页入口重做科学软件发布或旧安装验收。

## 三窗口独占分工

| 窗口 | 独占范围 | 交付 |
|---|---|---|
| 规划 | 私有运行时根 package/lockfile、启动/停止脚本、依赖安装、站点配置、server 主入口/路由挂载与最终浏览器集成；当前计划头部 | 可启动的实际 Zeus 宿主、MLCC 0.57 Bundle/MCP 绑定、可访问地址与一次完整浏览器流程 |
| 推进MLCC H0闭环实施 | 私有运行时 `apps/server/src/mlcc/` 新目录，必要独立配置/样例清单；仅需修改 MLCC Python 时先同规划明确所有权 | 复用真实 MCP 的任务列表/查询；已有 Study 和参数文件读取；提供可挂载 handler，不并改 server/index.ts 或根依赖 |
| 接入abacus-deepmd-lammps | 私有运行时 `apps/web/` 的 MLCC 展示/交互和该 app 内必要接线；复用 Zeus web/UI 样式与选择机制 | 网页可选择 MLCC、任务查询、Study 与参数表/原始 JSON 展示；不改后端目录、根依赖和启动脚本 |

三方不是唯一开发者，不回退或覆盖别人的改动。规划先建立最小私有宿主目录并告知两侧；其后不再覆盖 worker 持有的后端/前端文件。各 app 的清单依赖变更由所属窗口提出，规划统一改根 lockfile 并安装。需要扩展独占范围时由规划串行确认，不自发并改。没有必要再派独立重复审查。

## 最薄接口约定

优先复用 Zeus 已有 agent catalog/工具网关/文件接口。若现有宿主不能直接提供以下只读功能，由后端提供薄的 `/api/mlcc` 路由，前后端按该共同约定并行；规划可以映射到已有等价路由并一次通知两侧，不建第二套任务系统。

| 路由 | 首轮行为 |
|---|---|
| `GET /api/mlcc/agents` | 从已安装 Bundle/Agent 元数据投影实际 MLCC 名称与版本，供现有选择机制使用 |
| `GET /api/mlcc/tasks` | 通过现有 `mlcc_list_tasks` 获取任务清单 |
| `GET /api/mlcc/tasks/:id` | 返回对应已保存 TaskRecord 详情 |
| `POST /api/mlcc/tasks/:id/query` | 调用现有 `mlcc_query_calculation`，返回真实工具结果或原始错误；不提交计算 |
| `GET /api/mlcc/studies` | 从明确配置的现有 Study 入口列出可展示实例 |
| `GET /api/mlcc/studies/:id` | 返回原 Study JSON 与参数文档引用 |
| `GET /api/mlcc/parameters/:id` | 返回指定已有领域参数文档，供参数表和原始 JSON 查看 |

清单用 `{items:[...]}`，文档用 `{id,data,source}` 即可；MCP 查询返回实际结果。身份用现有 ID，来源用原路径/任务记录，不加哈希、摘要或来源框架。列表/文档引用由 site/project 配置指定，原科学目录保持原位，不将所有历史目录复制到新的 workspace，不全盘扫描。相对路由使用同一个宿主或 dev proxy，运行时地址/端口不写进便携 Bundle。

现有 MCP 已有七工具，首轮只使用 `mlcc_list_tasks` 和 `mlcc_query_calculation`。Study/参数显示可直接读取原已交付文件；不为了这个首轮给 MCP 重造全部文件工具。选择能被当前实际 MCP workspace 查到的真实任务；查询历史任务时若 Slurm 已不再保留，显示原始查询错误与有时间标注的保存状态，不伪装成实时状态，不重新提交任务。

## 界面内容

沿用 Zeus 当前界面风格和 Agent 选择组件，不重设计网站。只补：MLCC 选择、任务列表/状态/查询、Study 列表/详情、参数的名称/数值/单位/条件/坐标/映射/来源/状态以及原始 JSON。`null` 和原未决/失败状态按原文保留，不隐藏或补值；大数组引用已有文件，不为展示重算数据。已有选择组件若依赖后端 catalog，由两侧通过薄适配连接。

## 运行与最小验收

- 网页宿主、依赖构建、MCP 连接和浏览器交互可在本地运行；这不是科学数值计算。所有真实数值计算和科学后处理仍仅 v100 Slurm，本批不增加这些任务。
- 规划选择可用本地端口，复用现有 Zeus 本地项目/认证模式和所需最小依赖。后台 helper 默认隐藏窗口，用户实际浏览器可见；不结束无关进程或修改别的项目配置。
- 一条实际浏览器流程即可：启动网页 → 选择 MLCC 0.57 → 列出真实任务并查询一项 → 打开已有 Study → 展示至少一个真实领域参数文档及原 JSON。API 可通和静态页面不能替代这一条实际流程。
- 首次流程中只修真实阻断节点，成功节点不反复验证；禁止哈希、校验和、全对象比较、新资格门或框架。不要为每个 UI 字段写重复测试，不全套重跑上游/MLCC 旧测试。
- 交付 `workspace/reports/zeus-web-entry-v001/` 下简短运行说明、地址、所用真实 task/Study/参数源、浏览器证据与停止方式。不要保存凭据，不把脚本准备、HTTP 返回或版本变更说成浏览器闭环已完成。

当前不扩展网页计算提交、自动编排、有限元或新材料计算。三个窗口直接执行以上功能，规划自行跟进交接，不等监督每小时唤醒。
