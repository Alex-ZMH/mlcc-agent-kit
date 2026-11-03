# MLCC 公网统一操作入口

设计方案或遇到执行冲突时，结合[当前能力边界](calculation-boundaries.md)与所选方法 Skill 解释当前实现范围；目录/schema 不代表全部内核关系条件已通过。网格资源软推荐不阻断，未知/未检查事项如实保留。

Bundle 内所有顶层与模块方法 Skill 共用三个已绑定的操作入口；入口只负责把
已选 Skill/operation 路由到现有 CLI、模块 ops 和 TaskRecord，不复制科学逻辑。入口支持
从任务创建到结果读取的既有生命周期；DFT 生产默认使用 ABACUS，只有用户明确要求 VASP
时才选择 VASP，且不自动回退或混用 method/provenance。

| 入口 | 用途 | 约束 |
| --- | --- | --- |
| `mlcc_describe_operations(skill_id?, operation?)` | 读取动态能力目录、Skill 和 operation 的参数 schema | 只展示 catalog 和契约，不代表求解器、站点或科学验收已通过 |
| `mlcc_create_operation_task(operation, arguments, request)` | 依照 CLI parser 的 schema 创建一个 host 绑定的 v100-local Slurm 控制任务 | `arguments` 使用目录返回的 schema；`site`、`workspace` 由宿主注入；路径必须留在项目工作区；创建阶段只写任务和输入，不隐式提交 |
| `mlcc_read_result(task_id)` | 读取已有 TaskRecord 及已保存的 execution、quality、专业结果和 artifacts | 只读已有结果，不重算、不补缺项、不把缺失结果改成成功 |

DFT 资源查询使用已注册的 `mlcc_describe_dft_resources(elements?)`。省略 `elements` 时先查看
运行时周期表摘要；摘要若返回 118 项，仅代表目录检查范围，不承诺 118 项都有可用 PP/NAO。
传入所需元素后再查看对应详情，创建输入只引用详情返回的
`selected[].pseudopotentials[].id` 与 `selected[].orbitals[].id`，不能猜测文件名或
拼接站点路径。Og 来源缺失、f-core/f-valence 限制和其他兼容性结论必须原样采用目录实际返回。
LCAO 方法的 `numerical_orbital_library_id` 使用轨道详情返回的 `library_id`；库说明与
PP 映射路径由宿主站点解析，用户无需提供服务器私有路径。效率轨道的未占据态用途限制保留。

## 建模控制任务与科学输入

`mlcc_create_operation_task.request` 使用 `mlcc.operation-task-request.v1`，包含 `task_id` 和显式 `resource_request`；可选 `study_ref`、`required_results`。正确的 `schema` 可填写，不能把 `mlcc.operation-request.v1` 或四尺度请求信封填到这里。`arguments` 的键使用 CLI dest 名，例如 `request`、`parent`、`output`，不带 `--`。

对 `import-model`、`derive-supercell`、`derive-defect`，按 operation 查询目录会同时返回 `request_file_contract`，说明 `arguments.request` 文件的必填字段和约束。该文件与控制任务外壳分别填写；导入字段为 `source_path`，并须保留明确相和来源。创建只校验控制参数，不读取结构或运行科学预检。

执行失败会保存 `operation-result.json` 中的原始 CLI 错误、退出码及 stderr；先 collect 再 read-result。调度 FAILED 和领域未计算分别保留；不要把执行器在无分配环境下的拒绝误认为原作业缺少 Slurm 分配。

## 能力目录

`mlcc_describe_operations()` 动态汇总 8 个顶层 Skill、7 个模块方法 Skill 和 CLI
catalog 中的 114 个命令。目录是运行时事实，不在 Agent 文档中复制一份可能过期的
操作列表；传入 `skill_id` 或 `operation` 时只返回对应的条目和 schema。

目录的 `arguments` 描述 CLI 参数。`route=slurm_control` 时用于统一任务入口的
`arguments`；`route=existing_mcp` 或 `existing_mcp_lifecycle` 时按 `mcp_tool`
指定工具的 MCP input schema 调用，不能把 CLI 参数直接传给该 MCP 工具。

四尺度的 `mlcc_describe_scales(module_id, operation)` 同时返回科学 `input_schema`
和平台 `task_request_schema`。创建工具 `mlcc_create_scale_task` 的 `request` 严格使用后者：

```json
{
  "schema": "mlcc.scale-task-request.v1",
  "task_id": "NEW_READABLE_TASK_ID",
  "resource_request": {
    "nodes": 1,
    "ntasks": 1,
    "cpus_per_task": 1,
    "mem_mib": 2048,
    "time": "00:05:00"
  },
  "study_ref": "USER_STUDY_REFERENCE"
}
```

资源预算由实际任务确定，示例不构成材料或提交授权。`module_id`、`operation`、`input`
是创建工具的独立参数；`platform_task_id` 和 `mlcc.scale-execution-request.v1` 属于
内部执行信封，不能填入创建 `request`。输入错误按返回的字段原因修正，不通过改科学
参数猜测恢复，也不自动循环重试。已有任务先读取，不重复创建或提交。

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
2. 在创建前按 schema 收齐必要科学输入并解析站点安装资源；缺项一次列出，不能编造占位
   输入或把任务标为 ready。参数由 CLI parser 校验，宿主注入计算站点和工作区。FEM、相场、
   RVE、SPICE 的四尺度 describe/create/read 仍复用各模块已有 operation/ops 实现，不另起
   一套逻辑。
3. 用户明确请求创建时调用 `mlcc_create_operation_task`。创建后由宿主沿现有 `prepare`、
   必要的文件 copy/transfer 和 `submit` 继续；提交需要当前对话中的明确执行授权，或同一任务
   已记录的授权，已授权任务不重复索要许可。`create`、`prepare` 和 `transfer` 不等于提交。
4. 提交后用既有 `query`/`collect` 读取实际调度状态和产物；已有保存结果时调用
   `mlcc_read_result(task_id)`，按返回的来源、单位、状态和 artifact 引用报告，追问同一任务
   只读同一结果，不重提或重算。

安装资源可用、输入兼容、数值收敛和材料科学资格是四个独立状态，必须分别展示；工程链路通过
不等于材料具备生产资格，也不自动追加收敛矩阵。

Worker 只负责公网会话、路由、任务控制和产物回传，不在 Worker 进程上运行科学数值。站点
绝对路径、凭据、许可证和资源策略只由宿主注入，不写入可移植 Skill 或用户请求。

各领域的单位、输入条件、求解范围、数值收敛和科学资格继续以对应顶层/方法 Skill 及
模块 schema 为准；统一入口不改变这些边界，也不自动跨尺度传参。
