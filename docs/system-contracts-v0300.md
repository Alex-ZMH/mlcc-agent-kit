# 0.30 CZO 原生响应同 Study 交付与安装合同

2026-10-23：0.30.0 已完成安装路径验收并正式启用冻结；0.29.0 为回退版，源码下一版为 0.31.0。Registry、MCP 路径和 Python 绑定均指向 0.30.0，发布事实以 `workspace/reports/czo-native-response-v030-install-v001/release-acceptance.json` 为准。

## 交付范围

0.30 保留既有 `deliver-properties --study STUDY.json --p5 REQUEST.json --output DELIVERY.json` 公共入口。P5 请求直接消费保存的 Born 分支族、原始 Γ 力响应和电子介电结果，按同一 Study、父 Model、20 原子顺序、方法来源、单位和原生任务来源交付；交付过程不启动 DFT、MD、PYATB，也不重建力常数或响应数据。

本切片验证的是软件路径和安装副本消费能力。验证输入来自 CaZrO₃ Pnma 工程验证 Study `cazro3_firing_validation_v003`，不是普适产品规格或材料生产资格判定。候选 Bundle 只包含代码，不包含科学 workspace。

## 原生来源和安装验收

job355 是源码消费结果，job356 是真实 0.30 安装副本的唯一消费验收。两者均为 `COMPLETED/0:0`。安装副本从 v100 的
`/home/v100/projects/mlcc/development/0.30.0/installed/0.30.0` 导入模块，并复用 job355 保存的 request、Study 和全部 producer 文件。

| 项目 | 结果 |
| --- | --- |
| job355 同 Study 源码交付 | `COMPLETED/0:0` |
| job356 安装副本 `deliver-properties` | `COMPLETED/0:0`，只执行 1 次公共命令 |
| 原生角色条目 | 81 |
| 唯一原生调度 job | 54 |
| 跨产品完整原子绑定 | 20 个原子，顺序一致 |
| 原始数值和来源数组 | 与 job355 完全复现 |
| 安装副本模块路径 | `.../development/0.30.0/installed/0.30.0/src/mlcc/` |
| 旧测试、DFT、MD、PYATB 重跑 | 0 |

54 个唯一来源 job 和 81 个角色绑定保存在安装验收 JSON 中，不能把角色条目数解释成新增计算次数。安装路径验证保留 `epsilon_infinity` 的原生数值、Born/Γ 的原始数据及其来源，不将缺失项改成零或其他估计值。

## 科学状态和边界

当前结果不授予材料科学或生产资格。物理 Born 张量保持 `null`，因为连续极化分支和整数极化量子尚未由科学证据选定；原始 Γ 矩阵保持未投影的非对称诊断状态；离子介电增量和完整静态介电保持 `null`。`epsilon_infinity` 已有保存的电子贡献，但不能单独代表静态介电常数。`scientific_qualification`、`numerical_qualification` 和 `production_qualification` 均为 `false`，`design_assessment` 保持 `not_assessed`。

本合同不自动施加 ASR、Hermitian 投影、Born 对称化或最近极化分支选择，也不以软件安装通过替代目标量收敛和物理资格。CaZrO₃ 的材料差异和未决响应继续作为科学状态保留，不阻塞正确的系统参数传递和下游消费。

## 证据

- [发布验收](../workspace/reports/czo-native-response-v030-install-v001/release-acceptance.json)
- [候选安装验收](../workspace/reports/czo-native-response-v030-install-v001/candidate-install-acceptance.json)
- [安装副本详细验收](../workspace/reports/czo-native-response-v030-install-v001/installed-delivery-356/acceptance.json)
- [安装副本交付结果](../workspace/reports/czo-native-response-v030-install-v001/installed-delivery-356/delivery.json)
- [job356 调度终态](../workspace/reports/czo-native-response-v030-install-v001/job356-scontrol.txt)
- [job355 同 Study 验收](../workspace/reports/czo-native-dielectric-consumer-v001/response-public-355/acceptance.json)

## 下一最小 0.31 范围

具体字段、函数签名、独占文件分工和后续最小验收已冻结于[0.31公共LCAO创建器合同](p5-v031-lcao-public-creator-contract.md)。这仅完成定义，不表示公共LCAO创建器已实现或已验收。

0.31 只明确现有 CZO LCAO 生产脚本接入公共创建器的最小范围，不提交计算。接线必须保留模型、Study、method set、ABACUS 版本、赝势/数值轨道、原子 ID、`STRU.atom-map`、输入文件、原生任务记录和 Slurm 来源；创建器只负责生成可审阅的 task/model/Study/INPUT/STRU/`job.sbatch`，实际提交仍由主线控制。

创建器的输入前置条件只包括 Study/Model、method set、ABACUS 版本、赝势与数值轨道、任务参数、资源配置、原子 ID 与 `STRU.atom-map` 所需的结构来源；它生成可审阅的 SCF/响应任务输入时，不要求已有 Gamma、Born 或分支审阅结果。Gamma 和 branch 依赖属于后续响应消费入口，必须显式进入请求与来源绑定：原始 Gamma 力响应、位移清单、Born 分支族、极化量子及外部物理分支审阅结果分别记录。缺失或未选择时继续输出 `null` 与原因；不得自动投影、自动选支、借用数学夹具或把 LCAO/PW 原始标签混合。该范围不提交新的 DFT，也不扩大温度、相、掺杂或材料精度矩阵。

