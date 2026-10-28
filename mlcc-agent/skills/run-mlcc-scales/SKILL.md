---
name: run-mlcc-scales
description: 在同一个MLCC对话中选择独立FEM、相场、RVE或SPICE操作，复用现有TaskRecord和SSH/Slurm生命周期，读取原始QC与产物。
---

# 四个独立科学尺度

本Skill接入已有内核，不进行尺度传参。用户可直接选择其中一个尺度，无需先运行DFT或MD。DFT/MD保留原有Skill和单位体系。

| 问题 | module | 当前操作范围 |
| --- | --- | --- |
| 器件静电、电热、AC-EQS、限定闭合端口电磁 | fem | 8个SI/quantity操作；二维限定模型 |
| 标量/全矢量铁电相场与静态介电切线 | phase_field | 10操作；ND或显式参考尺度的SI |
| 二维/三维静电或导热均质化 | rve | 4个quantity操作；不自动读取上游介电张量 |
| 常系数RLC AC阻抗或有限脉冲瞬态 | spice | 4个SI/quantity操作；不自动生成器件寄生参数 |

## 实际调用

先使用 `mlcc list-scales` 查看操作名，必要时用 `mlcc describe-scale --module MODULE --operation OP` 读取当前操作schema。不要预读所有schema或猜科学参数。完整Bundle也提供固定脚本 `tools/mlcc_scale.py`，动作、参数和实现与上述命令相同；它无需在客户端加载DFT科学依赖。使用宿主已配置解释器。

准备专业输入文件后，沿 `mlcc create-scale --module MODULE --operation OP --input INPUT.json --site SITE.json --request REQUEST.json` 创建任务。SITE是宿主私有配置；REQUEST明确task_id/resource_request，可带study_ref，格式见 `../../examples/scales/task-request.json`。几何、网格、电路等按专业schema提供，不伪造atom ID，不要求没有物理依赖的原子模型或上游材料包。

create-scale仅校验专业schema并冻结源码/输入，不探测远端科学环境、不SSH、不求解、不提交。领域预检在选定Slurm任务内运行，依赖或物理约束失败时返回blocked。命令受理不表示计算已开始。

明确执行授权后，复用既有 `prepare/transfer/submit/query/cancel/collect --site SITE.json --task TASK.json` 或原有MCP生命周期工具。一次TaskRecord只提交一次；提交不明须核对原始任务，禁止重新提交。科学运行在已有Slurm分配内，脚本不启动第二层SSH、另一个调度器或聊天Agent。返回task/job后结束当前轮，不持续轮询。

收集后用 `mlcc parse-scale --task TASK.json` 读取完整结果和原生产物。query查询真实调度状态；parse-scale只读取收回的记录，不解析求解器、重新拟合、推进worker或提交任务。失败任务也可读取完整原因；缺失文件须报告缺项，不能补造成功输出。

## 结果解释与边界

保留 `result.execution`、`quality.numerical`、`quality.scientific`、`provenance`、`errors`和artifacts。调度完成、执行成功、数值通过和材料科学资格分别说明；`not_checked`、null和未收敛保持原值。已保存科学文件的路径以delivery的runtime_directory为根，使用result中登记的相对产物，不猜内部目录。

quantity操作使用四模块原有唯一单位核心；旧SI/ND操作保持旧合同。相场的绝对F/m切线不等于相对εr，也不自动送到RVE/FEM。RVE是单独均质化问题，SPICE参数需用户明确提供。几何/参数/材料来源缺失时只问必要科学信息，部署解释器、预算和SSH参数由宿主管理。

目前源码已接入26操作；随Bundle的 `../../compute/VALIDATION.json` 记录本轮4个服务器小任务，角色仅为历史工程证据。完整仓库另有 `docs/four-scale-integration-2026-10-28.md`；不将26项登记或4项服务器验收误称26项新服务器或新对话验收。
