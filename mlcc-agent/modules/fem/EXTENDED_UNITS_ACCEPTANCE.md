# FEM 0.4.0 器件多单位接入验收

2026-10-22。Windows接收带单位科学输入，调用唯一公共units核心，交付SI副本给既有WSL科学内核。本轮只增加输入表示与确定性准入，不扩展物理模型或改科学方程。三个原SI操作、schema、示例及旧任务保留。

## 实际运行与比较

| 操作 | 新真实任务 | 已保存SI基线 | 单元 | 代表结果 |
| --- | --- | --- | --- | --- |
| electrothermal_2d_quantities | task-344eedd76013465d8bb88a402927306c | task-2bd9b855fa29416dbedafc7b60900200 | 10198 | P=0.009707675872676841 W，最高温升1.918243721052335 K |
| ac_eqs_2d_quantities | task-27b2b2392ee74043a0782042d33f043a | task-557af8194a224f25a15fcac71ef00d72 | 10198 | Z=[2.7123763812199995,-123.38292012945416] Ω；P=0.0178086104461793 W |
| electromagnetic_2d_quantities | task-dedb1b61ad724deab2a9ce3dac19b960 | task-ead43fba81944f888e2b3eb366d8ac24 | 59414 | Z=[0.8732039062402032,-73.7977859483542] Ω；最高温升5.3247555979661225 K |

各入口仅一个新真实任务，Windows公共preflight→run(defer)→worker→result/status/artifact，既有Ubuntu-24.04/fenicsx-env，DOLFINx0.11.0，无安装/升级、无LLM调用、无扫描、无SI基线重算。示例使用mm/um、kV、kHz、mA、S/cm及26.85°C等；对应原值300 K。

三个任务分别保留26、26、31条单位审计。公共输入/原值/单位/source保持不变，canonical SI与既有SI输入数值完全相同，native operation为原SI操作，输入digest正确。**完整results和quality与各自基线完全相同**；不是仅比退出码或图片。

每任务14项接入断言通过：原始输入保持、SI副本一致、审计一致、native仅SI、摘要、完整结果等价、质量状态不升级、原生产物hash、产物引用唯一、三份审计各登记一次、只读查询不改record/结果、原基线record不改、无failed检查、科学检查仍not_checked。实际记录：

- 首次ET已成功，但验收脚本尝试重复独占写summary后停止。保留 `work/extended-units-e2e-19f61f04d0914977b61153db1e585eb6/` 诊断，不把它当科学执行失败。
- 修复脚本为编号进度及独占最终汇总；复用已完成ET，只继续AC/EM：`work/extended-units-e2e-d0856261d6484043b2eab924c49f0b8c/summary.json`，passed。
- 最终catalog兼容检查修改后，三个任务仅只读复核，未再求解：`work/extended-units-e2e-c5bc0b853e5747fd8751ed5a4eb262d0/summary.json`，passed。

上述目录均位于本模块；公共任务证据位于项目 `outputs/tasks/<task_id>/`。VTU/XDMF/HDF5/NPZ使用产物引用，规范化记录在artifacts/unit_normalization.json；不手抄原始数组。

## 确定性测试与兼容

`python -B -m unittest discover -s modules/fem/tests -v`：71项通过，覆盖原实现和新增多单位测试。新增15项方法涵盖全部三入口等价、混合单位、绝对温度、复数分量、RMS/peak语义、计数/无量纲类型、raw保持、幂等/replay、直接Adapter、公共预检、执行派发、错误输入、核心缺失、后端不可用、科学失败和无效响应拒绝。

单位core_version为1.0.0；本次实际catalog1.1.0。不精确锁词表版本：新增无关kind且版本变1.2.0时仍接受原能力；缺必需kind、改canonical单位/维度或删除实际输入单位登记则拒绝。FEM无单位倍率/别名/温度偏移表、无fallback。公共核心先解析拼写/别名，FEM检查返回unit_key在catalog登记。

离线测试、结构检查及交付检查记录存放于最终只读复核工作目录：tests-final.stderr.log、delivery-final.json（35份Python AST、schema/本地链接/Skill元数据有效）、source-audit-final.json（来源hash与13个关键科学函数AST一致）和compatibility-final.json。旧SI schema/示例hash对照 `work/extended-unit-compatibility-before.json`；科学内核/source清单未因本轮单位接入而修改。不重写旧任务，不把0.3.0历史记录冒充0.4.0运行。

## 尚未检查与边界

- 本轮真实验证是单位等价与运行链验收；新参数矩阵、新AC/EM真实Agent对话为not_checked，由main独立负责，未复制测试或新增模型调用。
- 单任务网格收敛、独立解析参考、原始通量工程精度、端口工程接受性、实际模型/材料/安装适用性、独立实测器件对照继续not_checked。继承已有数值检查不新增产品科学阈值。
- EM原始梯度热流误差约7.3%仍未验收，不因单位等价升级。EM固定mu_r=1、规定闭合引导端口，无商业ESR/ESL/SRF认证。
- 无温度反馈、瞬态、热力声、非线性磁性、3D或COMSOL。词表追加兼容不代表任意引擎协议可替换；core协议/版本不匹配仍拒绝。
- 无新增公共接口阻断；queued部署冻结、远端终止确认/取消仍是已有公共增强建议。超时不声称科学进程已经停止，保留原任务且不自动重提。
- Windows缺PyYAML，独立打包Skill验证器前置条件未满足，not_checked；标准库frontmatter/链接检查另行通过，不安装依赖。

调用与字段见 [多单位交接](EXTENDED_UNITS_HANDOFF.md)、[运行指南](EXTENDED_GUIDE.md)；既有物理模型和有来源数值检查依据见 [0.3.0验收](EXTENDED_ACCEPTANCE.md)。
