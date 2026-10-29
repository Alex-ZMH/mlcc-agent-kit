# 四个 Python 科学模块的公共任务生命周期

适用于 FEM、phase_field、RVE、SPICE 顶层运行 Skill。DFT/MD 继续使用各自已声明的创建器和原生解析流程，共用同一个 SiteRunner；本说明不要求它们改单位或部署环境。

## 准备与创建

先选择模块、操作和专业输入。`mlcc list-capabilities` 读取能力目录；`mlcc describe-scale --module MODULE --operation OP` 读取该操作的 schema。只加载相关方法文档。输入缺失时澄清必要字段；有权威输入文件时保持原值，合成示例需用户明确允许。

宿主提供 SITE.json（SSH、工作目录、显式后端绑定）及 REQUEST.json（安全 task_id、明确 resource_request，可带 study_ref）。参考 [任务请求格式](../../examples/scales/task-request.json)。部署信息不进入科学输入。

ARGS.json 的字段是路径，不嵌入第二套科学参数：

```json
{
  "input_path": "/workspace/inputs/case.json",
  "site_path": "/workspace/configs/site.json",
  "request_path": "/workspace/requests/case.json"
}
```

示意路径需由宿主解析为实际文件；不能照抄成存在的文件。

```sh
mlcc create-task --module MODULE --operation OP --arguments ARGS.json
```

创建只校验专业 schema 并准备 task.json、源码和输入，不连接 SSH、探测求解器、提交或求解。领域预检在 Slurm 分配内进行。TaskRecord 的真实路径、状态和 task_id 取自返回记录，不推测目录。

## 执行与查询

明确执行授权后，依次 prepare、transfer、submit：

```sh
mlcc prepare --site SITE.json --task TASK.json
mlcc transfer --site SITE.json --task TASK.json
mlcc submit --site SITE.json --task TASK.json
mlcc query --site SITE.json --task TASK.json
mlcc collect --site SITE.json --task TASK.json
mlcc read-result --task TASK.json
```

0.60.1 的对话入口优先使用实际绑定的 MCP：`mlcc_describe_scales(module_id, operation)` 读取契约，`mlcc_create_scale_task(module_id, operation, input, request)` 接收科学输入和任务请求对象，仅创建任务；站点来自运营配置，不接收用户指定的站点路径。按返回的 task_id 调用 prepare/transfer/submit/query/collect 生命周期工具，`mlcc_read_scale_result(task_id)` 读取保存结果。当前用户明确禁止提交时，只做创建、准备与只读核查，不能调用 submit。

原有 CLI 命令用于已经安装 `mlcc` 的操作环境；不要在没有 CLI 的公网 Worker 上把命令文字当作已执行。标准库客户端也可通过 Bundle 的固定 `tools/mlcc_scale.py` 启动相同动作。科学执行统一使用选定后端和 Slurm，不再运行内层 run/worker 队列。

提交后返回实际 task/job 与状态，不持续轮询。query 显式查询真实调度状态；collect 收集任务列明文件；read-result 仅验证和读取已保存结果，不推进计算、重新后处理或提交。缺结果时报告待查询/待收集/原错误，不能靠重新创建获得结果。更改科学参数需明确新任务，并保留原任务来源。

## 结果与失败

当前 read-result 的 `result` 是公共结果壳；其 `results` 才是专业结果。依次读取 `result.execution`、`result.quality.numerical/scientific`、`result.provenance` 和 `result.results`。这些结果已由模块确定性计算；LLM 负责解释，不裁定科学合格或重算指标。

产物使用 `result.artifacts` 的已登记相对路径，以 TaskRecord 的 local_workdir 为根。历史 bridge 的专用 delivery 可能声明 runtime_directory，按其原引用处理。只打开所需的指标、张量、曲线或场文件，大数组不复制到对话中；图片不替代原生数据。

区分调度终态、执行成功、数值检查和科学适用性。null、未收敛和 not_checked 保持原值。依赖缺失、原生失败或 interrupted 时保留原始错误和日志，停止自动推进；通信中断不证明远端科学进程已停止。提交结果不明时核对原任务与调度收据，不重提、不删执行收据、不换后端。
