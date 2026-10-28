> 历史接入记录：其中总入口Skill已在0.60.0撤销，由四个独立运行Skill接替；原计算证据与本文历史描述保留。当前组织见 [技能包装](skill-packaging-2026-10-28.md)。

# 四尺度接入：候选0.58.0

本分支把FEM 0.4.2、phase_field 0.4.0、RVE 0.1.3和SPICE 0.2.1的26个独立操作接到现有MLCC能力包。DFT/MD源码、原生命令与单位处理不变；本轮不做尺度传递。候选包尚未合并或替换同事已启用的0.57。

## 已实施

- 计算源码随Bundle放在 `mlcc-agent/compute/`，包括唯一UNIT核心、Scientific Core和完整运行资产，排除work、实验输出、私有配置与凭据。`SOURCE_MANIFEST.json`同时记录原始/导入哈希，导入仅统一LF换行。
- 对外沿用 `mlcc` 命名和现有TaskRecord。新增 `list-scales`、`describe-scale`、`create-scale`、`parse-scale` 四个命令，原prepare/transfer/submit/query/cancel/collect及7个MCP生命周期工具继续共用。
- 固定子进程入口在已有Slurm分配内运行native_linux内核；不启动第二层SSH、Slurm作业、LLM或常驻队列。内部Python包私有加载，不覆盖平台 `mlcc`。
- create-scale只做schema和宿主配置校验并冻结输入/源码，不求解、不提交。远端领域预检与求解在同一Slurm任务内完成。
- parse-scale只读收回的记录，核对platform/runtime/job、模块/操作、原始输入、专业输出schema和注册产物；不把COMPLETED/0升级为科学合格。
- 同一Agent挂载新增 `run-mlcc-scales` Skill，原DFT/MD Skill保留。新尺度的模型可为几何/网格/电路，不伪造原子模型，也不要求不相关的上游Study或参数。

## 对接命令

先将 `configs/site.scales.example.json` 的 `scales` 段合入宿主现有私有site配置，显式替换local/remote_root。account仅在站点有实际账户时显式填写；没有配置时不猜。模块deployments沿用已有native配置，linux_root由本次任务的payload根确定。FEM扩展操作可通过operation_deployments选择原扩展profile。

```text
mlcc list-scales
mlcc describe-scale --module fem --operation electrostatics_2d_quantities
mlcc create-scale --module fem --operation electrostatics_2d_quantities --input INPUT.json --site SITE.json --request REQUEST.json
mlcc prepare --site SITE.json --task TASK.json
mlcc transfer --site SITE.json --task TASK.json
mlcc submit --site SITE.json --task TASK.json
mlcc query --site SITE.json --task TASK.json
mlcc collect --site SITE.json --task TASK.json
mlcc parse-scale --task TASK.json
```

REQUEST格式见 `mlcc-agent/examples/scales/task-request.json`；它给task_id和显式CPU/内存/时限，可选study_ref，不承载科学默认值。INPUT严格遵循所选操作schema。完整Bundle也提供固定 `tools/mlcc_scale.py`，调用同一注册/创建/读取函数和SiteRunner，适合客户端未安装DFT依赖的宿主；不是另一套调度服务。

部署必须提供完整Bundle，Python wheel本身不包含Agent/Skill/compute资产。当前每个任务冻结一份源码payload再传输，优先保证可审阅和任务独立；未做共享源码分发或缓存优化。

## 本轮验证

精确记录见 `verification/four-scale-integration-2026-10-28/summary.json`。本地新增接入测试14项、既有SiteRunner测试13项通过；公共框架回归单独记录。它们不是科学验收。

FEM量值静电与相场全矢量SI分别通过真实Slurm作业673、677的新建/传输/提交/查询/收集/解析。结果为real_computation，保留各自numerical/scientific的not_checked项。真实四模块完成情况以summary中逐任务状态为准，不以26个操作登记数推断全部服务器验证通过。

RVE 675、SPICE 676暴露源码导入遗漏：缺少SOURCES/单位来源/数值协议文件，在启动科学求解前失败。已补齐17个运行资产并加入打包检查，保留原失败记录；以新任务680、679验证，未改科学输入、算法、阈值或资源。

四模块最终均完成真实服务器小任务：FEM 673（25个注册产物）、相场677（34个）、RVE 680（39个）、SPICE 679（30个）。均保存原生COMPLETED/0:0、Runtime succeeded、real_computation、原始单位审计、完整结果及逐产物哈希；numerical/scientific汇总中的not_checked保留。679/680一度显示InvalidAccount，实际分区AllowAccounts=ALL、AccountingStorageEnforce=none；未填账户或更改配置，随后正常完成。

同一保存任务的重复读取及workflow续接已核对，读取前后TaskRecord哈希不变。26个操作中只有上述4个在本轮新增服务器任务验证，其余操作有完整源码/schema接线，但未标为本轮服务器通过。

本地复现接入检查（完整源码Bundle、Python3.12、WSL）：

```bash
PYTHONPATH=mlcc-agent/src python3 -m unittest discover -s mlcc-agent/tests -p test_scale_tasks.py -v
PYTHONPATH=mlcc-agent/src python3 -m unittest discover -s mlcc-agent/tests -p test_site_runner.py -v
```

来源项目公共回归119项亦重新通过，原始日志随验证目录交付；该套测试需要来源项目完整目录，本Bundle保留最小执行子集与新增接入测试，不把缺失的来源测试环境伪装成完整平台回归。

参考Kit的Bundle manifest/Agent/Skill/MCP结构检查通过；完整Kit校验仍报告57项Harness错误，全部来自同事基线已有8个案例的旧格式，与本分支修改前完全一致。本轮不重写这些DFT/MD案例。完整上游科学/CLI回归因本地缺少原子尺度依赖没有运行，不将其记为通过。

## 工作台交接与未覆盖部分

实际Zeus调试工作台源码仍在同事私有workspace；本分支提供完整能力包和原有CLI/Skill调用方式，可由既有宿主加载。尚未在该实际工作台做同会话六尺度切换或真实LLM端到端验收，状态为not_checked，不把本地合同测试或CLI服务器任务冒充聊天验收。

原始大体积场/网格/轨迹和全部任务目录保留在本次个人工作区；公开验证目录只放分层结果和摘要。科学适用性、材料标定、每点网格/时间收敛与跨尺度传参均未新增承诺。取消仍由既有Slurm runner负责，突然终止后的内部任务锁/进程需先对账，禁止删除锁或重提交来掩盖不确定状态。
