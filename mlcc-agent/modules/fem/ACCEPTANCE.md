# fea 0.1.0 实施与验收记录

日期：2026-10-21（Asia/Shanghai）。本轮用户确认基础二维电场闭环；多物理未确认，未实施/未注册。**Windows 公共入口→Windows Adapter→已有 WSL 科学入口→Windows 结果/产物管理已真实运行完成**。数值执行完成不等于实际器件科学资格通过。

## 实施内容

- module.json实现状态为implemented，仅electrostatics_2d操作；专业输入/输出正式schema、正常/非法例、固定adapter.py、方法Skill、宿主部署样例与Windows启动脚本已就位。
- device_fem/validation.py、adapter_api.py、deployment.py均为Windows标准库：校验、固定外部科学调用、结果规范化。不导入FEniCS，不接收用户命令，不新增公共任务系统。
- science_entry.py和device_fem/fenicsx.py仅在WSL做科学工作。自有参数化OCC几何、语义区域/BC、Gmsh P1网格、DOLFINx静电、能量/电荷/场导出；不导入旧fem_agent，不使用来源绝对路径或sys.path注入。来源归属/hash及改写见SOURCES.json。
- 额外保存总量/单位深度量、外位移通量、assembled residual、三角形面积/形状观察、实际环境/选项/产物hash；Windows验证摘要与文件一致性，公共层登记产物。

## 实际运行命令与证据位置

Windows解释器为项目README已核实的Codex Python3.12.14。WSL实际Python3.11.15/DOLFINx0.11.0及其他包版本见ENVIRONMENT及各任务method_environment.json。无安装、升级、环境替换或旧Web/LLM调用。

```powershell
& $FeaPython -B -m unittest discover -s modules/fem/tests -v
& $FeaPython -B -m mlcc check
& $FeaPython -B -m modules.fem.harness.verify_small --deployment D:/Zhaoxiang/code/mlcc-main/modules/fem/deployment/example.json --run-real
```

真实验收工作目录为 `modules/fem/work/qualification-214e76d95a7545b1b3973c7e364e2311/`。其cli-*.json保留每次Windows CLI argv/退出码/响应，summary.json保存数据与证据等级。公共原始任务在 `outputs/tasks/<下表task_id>/`，由公共Runtime创建/管理。没有直接编辑公共record或源代码。

| 实际小算例 | Windows公共task_id | 单元 / DOF | 能量电容 |
| --- | --- | --- | --- |
| MLCC基线：6间隙、εr1500、10/0V、深度1mm、目标网格5µm | task-7c844b17e90a4a168f65bb8e2b1f037c | 7392 / 5354 | 12.8931222502 nF |
| 仅A端改20V | task-5df9e312d4e84503a900ef0f15c81c24 | 7392 / 5354 | 12.8931222502 nF |
| 仅εr改2000 | task-032675d2c9794bb68910cf363a2f243c | 7392 / 5354 | 17.1908296669 nF |
| 仅深度改0.7mm | task-a5a2280410db4be6bfa21651de547d26 | 7392 / 5354 | 9.02518557512 nF |
| 仅网格改2.5µm | task-17e6d36f506a4ec68d6ddb83dd3883c7 | 23544 / 15080 | 12.8822326502 nF |

五例均queued→worker→succeeded，evidence_kind=real_computation。public result/schema、artifact路径/大小登记、只读status/result/artifact、终态worker不重执行均在脚本中断言。缺部署/非法输入预检明确拒绝且不新增task；actual deployment SHA与argv在各task/native/launch.json。宿主配置并未被新增到科学input。

基线QA=+1.2845111988790371e-7 C、QB=-1.2848189410149258e-7 C，U=6.446561125083377e-7 J；端电荷相对不平衡0.0002395217926（约0.02395%）；raw-flux与能量电容相对差0.003723711018（约0.3724%）；外绝缘有符号向外位移通量约-4.2478332733e-12 C。保留这些离散误差，没有用能量法替换/掩盖通量诊断。

基线PETSc reason=4，真实assembled residual norm约2.126e-21；A/B/outer外界facet覆盖3314/3314，未知/重复/内部错标均0。三角形非退化、坐标及字段有限，VTU回读通过；最小面积约2.165e-12 m²、最小归一化形状指标约0.76834。数值观察不自动授予残差/形状科学合格阈值。

## 解析与缩放/网格观察

额外运行**原生平行板参考**：宽0.4mm、高0.1mm、深度1mm、εr100、10/0V；使用同一模块弱式/求解/积分代码，几何明确标为harness parallel_plate，**不是注册的MLCC几何操作**。原生VTU/MSH/日志/指标在上述工作目录parallel_plate/artifacts。

独立公式 C=ε0εr L t/g 给出3.5416751251200005e-12 F，实际FEM为3.5416751251199993e-12 F，相对误差约3.421e-16。按来源 `experiments/mlcc_electrostatics/spike.py:350–370` 已有平行板2%参考线通过；该线仅用于此数值基准，未转成MLCC一般产品容差，也未把解析公式自身输出当真实求解。

- V翻倍：C不变、Q两倍、U四倍，在所存双精度结果中对应相对差为0。
- εr由1500到2000：C比例相对误差约3.157e-14。
- 深度1mm到0.7mm：Q/U/C按0.7比例，场不变，对应相对差在所存结果中为0；未重复乘层数。
- 网格5µm到2.5µm：能量电容相对变化0.0008446053（约0.08446%）。这是两级网格稳定性观察，**不是普遍网格收敛证明**。

## 合同、失败与检查结果

| 检查 | 本轮实际结果 | 范围 |
| --- | --- | --- |
| Windows模块unit tests | 23 tests通过 | 含输入/字段/单位、部署缺失、后端不可用、坏JSON、科学失败/无效响应、超时不确定、同目录禁止重启、路径越界、边界集合错误；故障/超时mock不算真实求解 |
| 公共结构检查 | valid=true，8个模块 | 当前真实项目的mlcc check；不授科学覆盖 |
| Windows公共真实调用 | 5个小任务均完成 | 正式run/worker/result/artifact；没有把直接科学脚本成功冒充端到端 |
| 原生真实失败路径 | 通过，且没有发布结果 | work/native-budget-failure-1b25a9a62d314cf0835c9129b1cad29b；故意把原生max_cells设1，Gmsh生成7392单元后在预算检查处返回RESOURCE_OR_MESH_LIMIT/exit1，未进入求解，没有metrics/VTU；不是PETSc不收敛案例 |
| 公共回归（隔离副本） | 37项执行，36通过、1跳过 | work/public-regression-da978e90b86441a2b25692ad2f64d1af：逐字节复制当前mlcc/schemas/tests及两个原有fixture模块到本模块工作目录，执行默认unittest命令；源文件hash见snapshot_files.json。跳过宿主不允许的symlink创建。公共源文件未修改，未把其固定tmp写入其他thread目录 |
| 前端/LLM | not_checked / 不在本轮实现范围 | Skill是宿主可读说明，无新Web或MCP服务 |
| 原生远端终止/取消 | not_checked | 仅验证控制逻辑不误称已停止；未对正在计算的真实Linux进程做强制超时/取消实验 |

图片已从当前基线产物查看：电场细节图单位/色条清楚，注明纵向放大，电极槽为空白；图片不作为数值验证证据。

另以真实native response的内存副本验证5种Windows拒绝路径：错input digest、能量/深度不一致、伪造平衡摘要、hash不符、缺原始场登记，全部以INVALID_SCIENTIFIC_RESULT拒绝；原公共任务文件只读。记录在work/normalization-checks-c8105c73f0b74dcfa3b7006305fe72d5/checks.json。当前规范化器也重新验证全部5份真实公共结果的专业schema和量纲关系。

交付检查脚本harness/check_delivery.py核对Python语法、公共支持schema子集、入口/Skill引用和方法元数据。Skill的两字段frontmatter与链接检查通过；skill-creator自带quick_validate在Windows缺PyYAML时尚未进入校验，因此其结果为not_checked，未为此安装依赖。该工具前置条件失败不影响已完成的科学或端到端检查。

起初普通Codex沙箱的Windows→WSL probe被WSL服务访问权限拒绝，记录在work/bootstrap/preflight.json；使用工具批准的WSL访问后，完整相同Windows入口成功。没有通过移动框架到WSL绕过，未改变系统权限/环境。work/bootstrap_v2是正式公共验收前的一次Windows Adapter直接基线烟测，单独保留，不计入上表5个公共任务。

## 明确未验收项

每个成功任务的公共QC仍将以下项目写为not_checked：产品残差接受阈值、三角形形状接受阈值、通用电荷平衡/两电容容差、该单次任务的网格收敛/独立解析参考、模型适用性、材料工况来源核验、实物器件对照。验收harness的基准和两级网格观测单独记录，没有追写/升级原任务QC。

真实PETSc不收敛、真实运行中的超时/取消后的远端进程回收、MPI并行、高阶、其他机器环境重建、COMSOL、多物理均not_checked或未实现。分区ε/金属域/外空气/3D/AC等不在支持范围，未注册。

main无需修改公共层才能复现当前闭环。剩余公共增强是受信部署配置的queued快照/漂移检测及将来原生进程协调（见INTERFACE_PROPOSAL）；不宣称这些已经实现。提交到worker期间应固定部署文件，用户/科学负责人仍需确认真实材料/工况和科学容差，main维护公共覆盖总账。


2026-10-22 新增真实 Agent→二维纯电→结果解释与同会话只读追问验收，完整对话及新任务证据见 [AGENT_E2E_ACCEPTANCE.md](AGENT_E2E_ACCEPTANCE.md)。不升级原科学适用性状态。


2026-10-22 模块0.2.0新增显式多单位入口，复用唯一公共核心并完成一次真实等价计算；详见 [UNITS_ACCEPTANCE.md](UNITS_ACCEPTANCE.md)。旧SI输入/输出与历史记录保持兼容，科学not_checked状态不升级。


2026-10-22 用户确认并完成0.3.0器件扩展接入，原静电/多单位操作保留。新8个扩展成功任务、1个旧静电精确回归及首次电磁交接失败，详见 [EXTENDED_ACCEPTANCE.md](EXTENDED_ACCEPTANCE.md)；未将旧数值或实物科学检查升级。


2026-10-22 增量：fem 0.4.0新增三个器件多单位入口，旧SI能力与证据保持。真实等价任务、单位核心兼容性及未检查项见 [EXTENDED_UNITS_ACCEPTANCE.md](EXTENDED_UNITS_ACCEPTANCE.md)。
