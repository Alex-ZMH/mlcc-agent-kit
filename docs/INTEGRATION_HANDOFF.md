# MLCC 多尺度联调交付清单

交付版本：0.60.0。分支：`integration/four-scale-compute-20261028`。代码基线：`21dbc19`。尚未合并main。本文件之后的文档提交不改变该代码基线。

面向同事及其Agent：先阅读本文，再读取实际Bundle和对应Skill；历史报告用于追溯，当前接口以本分支源码为准。

## 1. 接收与保全

- [ ] 获取上述分支，在独立联调目录或现有合适工作区检查，不覆盖本地修改。
- [ ] 核对 `mlcc-agent/bundle.json` 版本0.60.0及八个Skill绑定。
- [ ] 保留原DFT/MD、建模、势训练、性质交付入口和历史计算记录。
- [ ] 完整交付源码Bundle，包括src、modules、schemas、scientific_core、agents、skills及tools；不要只复制Python包或Skill。

## 2. 新增独立计算功能

以下26个操作已有实现和历史真实小算例。当前各模块独立计算，不自动传参；示例为合成验证输入，不是材料/产品默认值。

| 模块 | 操作与范围 | 主要已有结果 |
| --- | --- | --- |
| FEM，8操作 | electrostatics_2d、electrothermal_2d、ac_eqs_2d、electromagnetic_2d，以及各自_quantities入口；限定二维静电、单向稳态电热、AC-EQS、闭合引导端口电磁 | 电容、电荷、能量、场；electrical/thermal端口及热结果、原生文件 |
| phase_field，10操作 | steady/evolve及_si；vector_steady/vector_evolve及_si；dielectric_tangent及_si。标量或全矢量LGD，2D/3D，静态分支完整切线 | P/phi/E、能量、接受态历史、场文件；切线张量、分支/稳定性诊断 |
| RVE，4操作 | homogenize_electrostatics_2d/3d、homogenize_thermal_2d/3d；明确组织和材料的静态均质化 | 2×2/3×3有效介电或导热张量、有效材料文件、逐载荷场和回读 |
| SPICE，4操作 | ac_impedance/transient及_si；受控线性RLC并联频响、有限源/负载单脉冲 | summary、metrics、曲线、原生raw/CSV、回读 |

性质提取与检查由模块确定性代码实现。相场切线SI为绝对F/m，不自动成为εr；RVE输入相对介电率与输出绝对张量分开；FEM端口量不自动等于商业ESR/ESL；SPICE需明确给定电路参数。未做的材料、收敛或适用性检查继续为not_checked。

DFT/MD科学实现、方法与势由原负责人提供和验收，原生单位保持，不强制SI。

## 3. 架构改动

- 删除嵌套compute框架及其Runtime、Store、内层队列和私有包别名。四模块科学代码归入 `mlcc-agent/modules/`，与DFT/MD清单同级。
- 沿用原TaskRecord和SiteRunner作为公共任务及唯一SSH/Slurm生命周期。新Python适配器在已有Slurm分配内执行一次，平台task_id贯穿全过程，不另建runtime_task_id。
- `capabilities.py`提供六领域清单；`task_service.py`分派创建和保存结果读取；四个新*_tasks.py与原abacus_tasks.py/lammps_tasks.py并列。ModuleContracts只校验描述/schema，不管理任务。
- `result_views.py`提供只读公共视图，保留专业结果、QC、来源和产物引用；任务链允许没有原子model_id的任务。历史bridge结果保留只读兼容。
- engine记录真实后端abacus/lammps/dolfinx/ngspice。站点保留abacus/lammps，新增dolfinx/ngspice；旧scales配置显式兼容，冲突拒绝。参考configs/site.backends.example.json。
- 同事原有科学输运transport.py保持原文件；新增adapter_transport.py负责JSON子进程通信。
- 同一多尺度Agent绑定建模、DFT、MD、phase-field、RVE、FEM、SPICE和properties八个Skill；旧run-mlcc-scales已撤销。七份深层方法Skill保留并更新调用流程。
- properties只补结果导航，模块已有后处理继续负责性质。没有新增统一性质包、非原子Study交付适配或自动尺度耦合。

## 4. 实际入口

在已绑定的宿主环境、完整Bundle中使用：

```sh
python -m mlcc list-capabilities
python -m mlcc describe-scale --module fem --operation electrostatics_2d_quantities
python -m mlcc create-task --module fem --operation electrostatics_2d_quantities --arguments ARGS.json
python -m mlcc prepare --site SITE.json --task TASK.json
python -m mlcc transfer --site SITE.json --task TASK.json
python -m mlcc submit --site SITE.json --task TASK.json
python -m mlcc query --site SITE.json --task TASK.json
python -m mlcc collect --site SITE.json --task TASK.json
python -m mlcc read-result --task TASK.json
```

四模块ARGS.json含input_path/site_path/request_path三个实际路径。请求格式见mlcc-agent/examples/scales/task-request.json；科学输入由所选schema规定，站点/资源由宿主提供。create只准备，不提交；执行须在明确授权范围内。

DFT/MD公共创建的operation为create，参数保持原创建函数签名和Skill要求；原create-abacus/create-lammps及专业命令继续可用。原生解析仍用原显式解析器；read-result不会代替缺失的解析步骤。标准库客户端可使用固定tools/mlcc_scale.py启动相同公共动作。MCP仍为原七个生命周期工具，不存在新增create/read MCP工具。

## 5. 已验证与未验证

| 项目 | 结论 |
| --- | --- |
| 四模块新架构服务器闭环 | jobs689–692分别完成FEM、相场、RVE、SPICE，实际执行成功、产物收集及公共只读视图通过；不是26项全部重新验收 |
| 初次路径问题 | jobs685–688因产物目录越界拒绝；保留失败证据，修正单任务release边界后用新任务验证 |
| DFT/MD非计算探针 | 二进制存在且可执行、SSH/Slurm准备/提交/查询/收集已验证；未启动科学引擎 |
| DFT/MD任务模块导入 | 探针所选公共Python缺numpy；另一已核对Python具备NumPy/ASE但缺pymatgen，导入未通过。693–696原结果保留 |
| Skill包装 | 4项绑定/操作覆盖/链接/命令解析检查及5份Skill格式检查通过；父项目119项公共回归通过 |
| 私有Zeus宿主 | 未现场验收安装、在线LLM路由或对话驱动计算 |

原创建器/解析器可以运行在同事本地宿主，服务器只执行原生命令。上述服务器Python导入缺项不证明原工作台失效；应确认并复用正式宿主环境，不强求求解器环境安装整个公共包。

证据：docs/verification/unified-architecture-2026-10-28/、docs/verification/skill-packaging-2026-10-28/。架构详解：docs/unified-architecture-2026-10-28.md；技能说明：docs/skill-packaging-2026-10-28.md。

## 6. 建议联调顺序与验收清单

- [ ] 在现有Zeus工作台安装本Bundle，核对Agent标题、六领域入口及八Skill，确认深层文件可按需读取；复用原界面和宿主。
- [ ] 先只读验证能力目录、历史任务、结果和产物。重复追问不得创建任务或提交作业。
- [ ] 核对正式宿主Python、领域依赖、SSH/Slurm和各后端显式绑定；账号/密钥/许可证放私有配置，勿提交。
- [ ] 用已有合法输入或明确授权的合成例子，按需验证四模块对话路由和创建；创建阶段scheduler_job_id应为空。若需实际执行，再按授权提交，保留task/job和产物证据。
- [ ] DFT/MD先验证正式宿主能导入原创建器，使用负责人提供的模型、方法、势和协议创建未提交任务。原生求解与科学验收由负责人决定，不因联调自动运行。
- [ ] 如负责人执行DFT/MD，用原解析器生成保存结果，核对公共读取与原命令一致，检查已有DFT→训练→MD路线未受影响。
- [ ] 区分代码接口、宿主路由、调度执行、数值检查和科学适用性。记录通过、失败及not_checked，完整Study性质交付和尺度传参不作为本轮完成项。
- [ ] 合并前审阅分支diff、保留历史入口/证据，并由双方确认实际联调范围；不要直接覆盖或强推main。

服务器本用户新增文件统一置于/home/v100/projects/mlcc/zhaoxiang/，不写共享项目根或同事目录。日常测试优先本地WSL，科学环境显式选择，不自动回退。重复提交或状态不明时停止推进并核对原记录。

## 7. 给接手Agent的指令

请先只读审阅本分支的AGENT.md、bundle.json、对应运行Skill及本清单。保留同事原有实现、工作台、任务和历史证据，按实际能力选择深层方法。先验证安装绑定、目录、保存结果及正式宿主依赖，形成缺项清单；创建、提交和真实计算分别按用户授权执行。DFT/MD没有提供明确模型/方法/势/协议时不猜默认值，不自动提交；四模块也不自动读取上游参数。查询不求解、不拟合、不重提，不把COMPLETED或退出0写成科学合格。联调变更留在分支，记录修改、验证方法、原错误和仍未检查项，交双方审阅后再决定合并。
