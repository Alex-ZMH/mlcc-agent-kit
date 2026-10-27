# 0.31 公共 LCAO 创建器工程验收与启用合同

状态：工程验收通过并正式启用冻结。当前启用版本为 0.31.0，回退版本为 0.30.0，下一源码版本为 0.32.0。0.29.0 的三个软件副本已按 [retirement-v029](../workspace/reports/lcao-public-creator-v031-v001/retirement-v029.json) 退役；历史报告仅作来源追溯。正式发布事实以 `workspace/reports/lcao-public-creator-v031-v001/release-acceptance.json` 为准。

## 已完成的工程路径

v100 Slurm job357 以安装副本 `/home/v100/projects/mlcc/development/0.31.0/installed/0.31.0` 完成公共 LCAO 创建器验收，终态为 `COMPLETED/0:0`。新增 29 项检查，其中 writer 17 项、creator 12 项。验收复用真实原生来源 job269 和 job284，没有新 DFT、PYATB、旧测试或旧宿主重跑。

本次路径覆盖：

- Model/Study、方法、站点和请求的显式绑定；
- ABACUS 3.10.1 LCAO 参数与 GPU/cusolver 资源透传；
- UPF/NAO 来源、配套记录、输入输出字段和轨道文件复制指令；
- 20 原子顺序、`STRU.atom-map`、TaskRecord、方法资格与来源记录；
- `runner.prepare` 生成 `job.sbatch`，但创建出的任务保持 `scheduler_job_id=null`，没有隐式提交。

证据为 [0.31 发布验收](../workspace/reports/lcao-public-creator-v031-v001/release-acceptance.json) 和 [job357 安装验收记录](../workspace/reports/lcao-public-creator-v031-v001/run-357/acceptance.json)，监督记录见 [0.31 实施监督](../workspace/reports/supervision-v031-20261023.md)。0.30 的同 Study 原生响应交付仍保留为回退版本证据。

## 有效边界

0.31 公共创建器当前只允许中性、非 SOC、nspin=1、fixed occupation、固定胞 SCF、GPU/cusolver 的 LCAO 输入。LCAO relax、NSCF、Berry、带电、自旋 2 和 CPU 其他求解器不由本切片放行。公共创建通过表示输入、参数传递、原子映射、来源和失败状态符合合同，不表示 DFT 物理结果或材料生产资格成立。

创建器前置条件只包括 Model/Study、method set、ABACUS 版本、赝势和数值轨道、任务参数、资源配置以及结构原子 ID/`STRU.atom-map` 所需的数据。Gamma 力、位移清单、Born 分支族、极化量子和外部物理分支审阅属于后续响应消费的显式输入，不阻塞通用 SCF 创建，也不得自动选支、投影或混用 PW/LCAO 原始标签。

## 科学状态

本工程验收不改变 CaZrO₃ 的科学状态。物理 Born 张量仍为 `null`，原始 Γ 矩阵保留未投影的非对称诊断，离子介电增量和完整静态介电仍为 `null`；科学资格、数值生产资格和材料生产资格均为 `false`。这些缺项必须继续以 `null` 和原因传递，不能用零、数学夹具或外部常数补齐。

## 最短系统剩余队列

| 顺序 | P 阶段 | 当前状态 | 下一动作 |
| --- | --- | --- | --- |
| 1 | 0.32/P5/P12 | 公共 NAO 快照获取入口缺失 | 补公共 NAO 快照获取入口；当前只有 `inspect-upf` 和 0.31 harness 生成的 `mlcc.nao-header-snapshot.v1`，不增加 SSH 自动探测或材料资格门 |
| 2 | 0.32/P5/P12 | 已保存原生输出尚未接入公共解析/响应 Study 链 | 显式复用已有 job、方法、Study、原子映射和响应来源，接入 0.30 消费合同；不伪造新任务或 job ID，不默认重算 |

P0/P1/P3 的系统包、站点 Slurm 和基础引擎路径继续复用既有证据。P4 完整带电缺陷原生参考与修正链、P5 物理 Born/介电、P7 完整 BZ 声子/热输运与科学资格、P9 材料势资格、P10/P11 生产 MD/统计/聚合物界面、P6/P8 完整磁性/热电输运流程仍是独立的科学或后置工程积压；中性 host/vacancy 原生 E/F 已有部分证据。这些不作为当前 0.32 系统门，也不宣称 P6/P8/P11 已完成。完整进度仍见 [PLAN.md](../PLAN.md)、[当前任务](../CURRENT_TASK.md) 和 [P0–P12 监督记录](../workspace/reports/supervision-v031-20261023.md)。

<a id="next-0-32-scope"></a>

## 下一 0.32 范围

0.32 只列出两个当前就绪的工程缺口：补充公共 NAO 快照获取入口，并把已保存原生输出与公共解析/响应 Study 链建立显式绑定，复用 0.30 响应交付合同。NAO 快照必须沿用 `mlcc.nao-header-snapshot.v1` 和已声明的库配套来源；原生接线必须复用已有 job、方法、Study 和原子映射，不伪造新任务或 job ID。不得默认重新运行 DFT/PYATB，不自动生成物理 Born、Gamma 或静态介电结果；详细实现合同待主线单独冻结。
