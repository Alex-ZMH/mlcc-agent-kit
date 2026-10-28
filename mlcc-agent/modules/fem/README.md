# 二维 MLCC 器件有限元模块 fem 0.4.1

Scientific Core V0.1：本模块 0.4.1 显式消费共享数值包 0.1.0，operation/物理模型/专业 schema 不变。部署须携带 Bundle 中的 `scientific_core/`。见 [本次接入与等价验收](SCIENTIFIC_CORE_ACCEPTANCE.md)。

Windows公共框架、Agent/Skill、Adapter、输入校验和任务/产物管理调用既有WSL Conda/DOLFINx科学环境。原五个操作保留，新增三个多单位器件入口；真实等价验收见 EXTENDED_UNITS_ACCEPTANCE.md；材料/实物适用性等科学检查仍逐项保留not_checked。

## 当前操作

| 操作 | 能力 | 输入例子 | 宿主部署例子 |
| --- | --- | --- | --- |
| electrostatics_2d | 原二维均匀线性无损静电，SI数字 | [normal.json](examples/normal.json) | [v1](deployment/example.json) |
| electrostatics_2d_quantities | 显式量值/单位/来源经唯一公共核心转SI，复用原静电 | [quantities-mm.json](examples/quantities-mm.json) | [v1](deployment/example.json) |
| electrothermal_2d | DC/规定AC损耗→陶瓷+Ni单向稳态热 | [electrothermal.json](examples/electrothermal.json) | [v2扩展配置](deployment/extended.example.json) |
| ac_eqs_2d | 真正复电势EQS、Y/Z/Cp、介质损耗，可选稳态热 | [ac_eqs.json](examples/ac_eqs.json) | v2扩展配置 |
| electromagnetic_2d | Ex/Ey/Hz Maxwell、有限Ni、闭合引导端口Z/磁能/分区损耗，可选稳态热 | [electromagnetic.json](examples/electromagnetic.json) | v2扩展配置 |
| electrothermal_2d_quantities | 多单位规范化后执行同一电热 | [electrothermal-quantities.json](examples/electrothermal-quantities.json) | v2扩展配置 |
| ac_eqs_2d_quantities | 多单位规范化后执行同一AC-EQS | [ac_eqs-quantities.json](examples/ac_eqs-quantities.json) | v2扩展配置 |
| electromagnetic_2d_quantities | 多单位规范化后执行同一EM | [electromagnetic-quantities.json](examples/electromagnetic-quantities.json) | v2扩展配置 |

新增多单位入口 `electrothermal_2d_quantities`、`ac_eqs_2d_quantities`、`electromagnetic_2d_quantities`，各使用 `examples/<analysis>-quantities.json`，均沿用v2部署。接口与来源字段见 [多单位交接](EXTENDED_UNITS_HANDOFF.md)。

新三项的严格输入、端口/散热条件、结果语义和运行预算见 [EXTENDED_GUIDE.md](EXTENDED_GUIDE.md)。概览见 [CAPABILITIES.md](CAPABILITIES.md)。所有示例是合成验证输入，不是材料/器件标定。

## Windows 调用

在项目根PowerShell使用已存在的Python3.11+；本机可用解释器如下。部署文件由宿主审查，不从科学输入或LLM接收机器命令。

```powershell
$FemPython = 'C:\Users\Xiang\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$env:PYTHONDONTWRITEBYTECODE = '1'
# 原静电、多单位静电使用v1配置
$env:MLCC_FEA_DEPLOYMENT = (Resolve-Path modules/fem/deployment/example.json).Path
& $FemPython -B -m mlcc describe fem
& $FemPython -B -m mlcc preflight fem electrostatics_2d --input modules/fem/examples/normal.json
# 以下会创建一次计算任务，仅在需要执行时运行
$r = & $FemPython -B -m mlcc run fem electrostatics_2d --input modules/fem/examples/normal.json --defer | ConvertFrom-Json
& $FemPython -B -m mlcc worker $r.task_id
& $FemPython -B -m mlcc result $r.task_id
& $FemPython -B -m mlcc artifact $r.task_id artifacts/fields/fields.vtu

# 新电热/AC/EM使用v2配置；此示例只预检，不执行
$env:MLCC_FEA_DEPLOYMENT = (Resolve-Path modules/fem/deployment/extended.example.json).Path
& $FemPython -B -m mlcc preflight fem ac_eqs_2d_quantities --input modules/fem/examples/ac_eqs-quantities.json
```

run排队，worker明确执行一次；status/result/artifact与终态worker不重算。也可用 [run-windows.ps1](deployment/run-windows.ps1)，指定-Python/-DeploymentFile/-Command/-Operation及输入或task。旧默认Operation保持electrostatics_2d。

## 模型、单位与质量

原静电是单一均匀线性各向同性无损介质、理想等势电极、自然外绝缘；显式面外深度，P1串行直接LU。陶瓷保护区/边距同材；电极从介质中扣除，不含金属实体或外空气。输出电位/E、端子有符号Q、U、能量/通量C，区分总量与单位深度量。有效间隙已在几何中体现，不额外乘层数。详见[原输入](schemas/electrostatics.input.schema.json)、[原输出](schemas/electrostatics.output.schema.json)及[静电方法Skill](skills/linear-electrostatics/SKILL.md)。

多单位静电使用[独立schema](schemas/electrostatics.quantities.input.schema.json)，raw量值/单位/source及canonicalSI、规则/版本完整保留，旧SI schema不放宽。见[单位设计](UNITS_DESIGN.md)。电热/AC/EM各自新增独立 *_quantities schema，用户可显式输入mm、μm、kHz、mA、S/cm、°C等公共白名单单位，统一经normalize_fields转原SI契约。原三个SI入口/schema保持严格兼容。没有模块私有换算表或fallback；未知/错单位、重复损耗、不适定热边界在求解前拒绝。

数值完成real_computation不等于科学资格。原始电流/热流误差与离散反力闭合分开保留；当前单任务网格收敛、解析对照、材料/模型适用性、独立器件对照等仍为not_checked。EM没有商业ESR/ESL/SRF验收、磁性材料、辐射或三维包装能力。没有温度反馈、瞬态、热力声或COMSOL。

方法说明见[器件扩展Skill](skills/mlcc-device-coupling/SKILL.md)。旧静电已完成真实Agent两轮对话；新三项已验证公共Runtime而未新增真实模型对话调用，相关对话验收为not_checked。Skill不代替计算与QC，也不产生执行授权。

## 产物、环境与故障

公共任务在outputs/tasks/<task_id>/保存输入快照、执行状态、provenance、结果、QC、错误与artifact登记。原生native/含请求/响应/启动参数/环境绑定/日志及任务内缓存；大数组留在VTU/XDMF/HDF5/NPZ。新操作solution/保存完整复场、热场和映射；可选PNG注明二维/纵向放大，不作为科学验收。

[ENVIRONMENT.md](ENVIRONMENT.md)记录现有环境，不安装Windows FEniCS、不移动公共框架到WSL。新v2仅授权新操作最大150000单元/240秒客户端预算；旧v1仍最大50000单元/最长120秒，旧操作拒绝v2。资源预算不是科学准确性阈值。

缺依赖/部署或非法输入明确拒绝；没有mock回退。超时/通信中断返回SCIENTIFIC_STATE_UNKNOWN或公共interrupted，不能保证Linux进程已停止；保留任务且不自动重提。没有取消API、后台调度或科学进程回收。queued期间须固定宿主配置，见[公共增强建议](INTERFACE_PROPOSAL.md)。

## 检查与证据

```powershell
& $FemPython -B -m unittest discover -s modules/fem/tests -v
& $FemPython -B -m mlcc check
& $FemPython -B -m modules.fem.harness.check_delivery
```

默认测试不启动WSL/LLM。真实测试由显式--run-real触发，不自动扫频或全量重放：

- [原静电及缩放/解析验证](ACCEPTANCE.md)
- [真实Agent完整对话](AGENT_E2E_ACCEPTANCE.md)
- [多单位真实等价验证](UNITS_ACCEPTANCE.md)
- [本轮电热/AC/EM接入验收](EXTENDED_ACCEPTANCE.md)
- [器件多单位等价验收](EXTENDED_UNITS_ACCEPTANCE.md)
- [原实现来源](SOURCES.json)、[扩展来源与哈希](EXTENDED_SOURCES.json)

## 历史资料

[REVIEW](REVIEW.md)、[迁移矩阵](MIGRATION_MATRIX.md)、[V1_PLAN](V1_PLAN.md)、[旧接口草案](INTERFACE_DRAFT.md)、[旧实施prompt](NEXT_IMPLEMENTATION_PROMPT.md)、[review_work说明](review_work/README.md)是历史审阅快照；当前以module.json、正式schema及本README/验收为准，不重复执行旧首次移植计划。

目录/模块ID由fea更名为fem；v1数据标识及MLCC_FEA_DEPLOYMENT保持兼容，历史任务/审阅证据不改写。所有来源和其他模块保持只读。


## 2026-10-26 可选 native Linux 部署接口

新增显式 `transport=native_linux` 的独立部署 schema 与 `deployment/native.example.json`，保留原 WSL 配置和科学输入。依赖在所选 Deployment 预检中确定验证，module.json 不再无条件要求 wsl.exe；这不表示后端已安装或科学预检已通过。使用同一 science_entry.py、独立 Conda Python 和原 UNIT/QC，不经 shell/SSH/自动回退。

配置、版本、检查和临时服务器验证后清理边界见 [main 交接](../../docs/server-deployment-2026-10-26/main-handoff.md)。FEM 扩展操作使用 `deployment/extended.native.example.json`，保持与原静电配置的 profile 边界。新增接口未在本机运行科学求解，也不表示服务器永久部署或远程 Agent 已上线。当前源码指纹见 `NATIVE_LINUX_SOURCES.json`；旧 SOURCES / SCIENTIFIC_CORE_SOURCES / UNITS_SOURCES 继续保留为历史冻结。
