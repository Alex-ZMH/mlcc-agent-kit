# MLCC 公网统一操作入口

Bundle 内所有顶层与模块方法 Skill 共用三个已绑定的操作入口；入口只负责把
已选 Skill/operation 路由到现有 CLI、模块 ops 和 TaskRecord，不复制科学逻辑。

| 入口 | 用途 | 约束 |
| --- | --- | --- |
| `mlcc_describe_operations(skill_id?, operation?)` | 读取动态能力目录、Skill 和 operation 的参数 schema | 只展示 catalog 和契约，不代表求解器、站点或科学验收已通过 |
| `mlcc_create_operation_task(operation, arguments, request)` | 依照 CLI parser 的 schema 创建一个 host 绑定的 v100-local Slurm 控制任务 | `arguments` 使用目录返回的 schema；`site`、`workspace` 由宿主注入；路径必须留在项目工作区；创建不提交数值任务 |
| `mlcc_read_result(task_id)` | 读取已有 TaskRecord 及已保存的 execution、quality、专业结果和 artifacts | 只读已有结果，不重算、不补缺项、不把缺失结果改成成功 |

## 能力目录

`mlcc_describe_operations()` 动态汇总 8 个顶层 Skill、7 个模块方法 Skill 和 CLI
catalog 中的 114 个命令。目录是运行时事实，不在 Agent 文档中复制一份可能过期的
操作列表；传入 `skill_id` 或 `operation` 时只返回对应的条目和 schema。

目录的 `arguments` 描述 CLI 参数。`route=slurm_control` 时用于统一任务入口的
`arguments`；`route=existing_mcp` 或 `existing_mcp_lifecycle` 时按 `mcp_tool`
指定工具的 MCP input schema 调用，不能把 CLI 参数直接传给该 MCP 工具。

顶层 Skill 为：

- `model-mlcc-structures`
- `run-mlcc-dft`
- `run-mlcc-md`
- `run-mlcc-phase-field`
- `run-mlcc-rve`
- `run-mlcc-fem`
- `run-mlcc-spice`
- `compute-mlcc-properties`

模块方法 Skill 为：

- `mlcc-linear-electrostatics`
- `mlcc-device-coupling`
- `mlcc-scalar-ferroelectric`
- `mlcc-tangent-dielectric`
- `mlcc-vector-ferroelectric`
- `mlcc-static-rve`
- `spice-linear-circuits`

## 调用顺序

1. 先用 `mlcc_describe_operations` 取得 canonical `operation`、输入 schema 和方法边界。
2. 只在用户授权创建任务时调用 `mlcc_create_operation_task`；参数由 CLI parser 校验，宿主
   注入计算站点和工作区。FEM、相场、RVE、SPICE 的四尺度 describe/create/read 仍复用
   各模块已有 operation/ops 实现，不另起一套逻辑。
3. 创建后由宿主沿现有 `prepare`，以及确有必要的文件 copy/transfer 控制路径继续；这些
   步骤不等于提交。真实求解仍由用户权限和站点策略决定。
4. 有已保存结果时调用 `mlcc_read_result(task_id)`，按返回的来源、单位、状态和 artifact
   引用报告；追问同一任务只读同一结果。

本轮联调只允许 catalog、create、prepare、必要 copy 和 read；不调用 `submit`，新任务的
`scheduler_job_id` 必须保持 `null`。这是一条当前验证策略，不是永久关闭产品能力；submit、
query、cancel、collect 仍由既有实现和用户/租户权限控制，后续获授权时沿同一 TaskRecord
生命周期执行。

Worker 只负责公网会话、路由、任务控制和产物回传，不在 Worker 进程上运行科学数值。站点
绝对路径、凭据、许可证和资源策略只由宿主注入，不写入可移植 Skill 或用户请求。

各领域的单位、输入条件、求解范围、数值收敛和科学资格继续以对应顶层/方法 Skill 及
模块 schema 为准；统一入口不改变这些边界，也不自动跨尺度传参。
