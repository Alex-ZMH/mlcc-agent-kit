# phase_field 0.4.0：标量、全矢量与静态切线介电张量

新增 **dielectric_tangent / dielectric_tangent_si**：二维完整 2×2、三维完整 3×3 的静态 ∂⟨D⟩/∂Ē，UFL AD + 完整耦合 Jacobian + 多右端线性灵敏度；含背景/极化贡献、冻结极化对照、局部约束稳定性、独立原生回读及可选新 FD/分支回算。旧八个操作和其输入 schema 保留。SI 为明确四尺度下的绝对 **F/m** 张量，不自动称为相对 εr；未稳定/近奇异态不输出有效张量。见 [张量设计](TANGENT_DESIGN.md)、[张量方法](skills/mlcc-tangent-dielectric/SKILL.md)、[本轮验证](../../docs/verification/phase-tangent-2026-10-27/README.md)。当前源码以 `TANGENT_SOURCES.json` 为准，旧索引保留原日期。

新增 **vector_steady / vector_evolve / vector_steady_si / vector_evolve_si**：2D 双分量与 3D 三分量 LGD–TDGL–静电、90°/180° 畴壁及恒场/三角波/阶梯加载。原四个标量入口、schema、RT0 和历史证据保留。新增矢量入口复用 Scientific Core 0.1.0 和唯一 UNIT core1.0.0/catalog1.2.0，独立原生回读和 SI 视图；见 [矢量设计与单位约定](VECTOR_DESIGN.md)、[Agent 矢量方法](skills/mlcc-vector-ferroelectric/SKILL.md)、[当前源码索引](VECTOR_SOURCES.json)。

日常开发/真实回归使用本地 WSL。native Linux 配置保留，各开发节点的服务器验证使用 `/home/v100/projects/mlcc/zhaoxiang/` 独立目录。合成模型与显式尺度不代表真实 BaTiO₃ 标定、铁弹耦合或一般多畴准静态滞回。

## 已保留的标量能力及历史验收

Scientific Core V0.1：本模块 0.2.1 显式消费共享数值包 0.1.0，operation/物理模型/专业 schema 不变。部署须携带 Bundle 中的 `scientific_core/`。见 [本次接入与等价验收](SCIENTIFIC_CORE_ACCEPTANCE.md)。

公开操作 **steady**、**evolve**，两者均支持明确dimension=2/3。Windows公共框架→本模块标准库Adapter→已有WSL/FEniCSx→结构化结果、质量与原生数据。真实证据见[ACCEPTANCE](ACCEPTANCE.md)和[evidence.json](evidence.json)，给main摘要见[MAIN_HANDOFF](MAIN_HANDOFF.md)。本轮只写本模块，experiments只读。

0.2.0新增可选 **steady_si**、**evolve_si**，使用公共唯一单位核心、显式参考尺度与SI结果视图。旧入口和历史记录保持原样。当前单位增量证据与交接以[UNITS_ACCEPTANCE](UNITS_ACCEPTANCE.md)、[units-evidence.json](units-evidence.json)、[UNITS_HANDOFF](UNITS_HANDOFF.md)为准；原迁移验收未重写。

## 有单位的新入口

SI输入schema见[steady_si](schemas/steady_si.input.schema.json)、[evolve_si](schemas/evolve_si.input.schema.json)，示例[evolve_si_3d.json](examples/evolve_si_3d.json)和[等价单位表示](examples/evolve_si_3d_equivalent.json)。所有有量纲值为`{value,unit,source:{kind,reference}}`，units=SI；新入口不接受裸量值、归一化记录或重复转换标记。网格计数、seed、modes、max_halvings仍是裸整数。

reference_scales明确给出length[m]、polarization[C/m²]、time[s]、energy_density[J/m³]四个正有限独立尺度及来源。g是物理κ[J*m³/C²]，epsilon是绝对介电系数[F/m]，applied_E是V/m；不支持epsilon_r，也不猜ε0或材料常数。初态尺寸/位置、极化值/幅值、时间均有各自单位。公共mlcc/units.py先确定转换为canonical SI，模块再按[UNITS_DESIGN](UNITS_DESIGN.md)推导无量纲输入，仍调用原内核，不安装专业库或改其他模块。

四尺度限定profile的一族物理系数：a=-f0/P0²、b=f0/P0⁴、gamma=0、M=P0²/(f0*T)；phi0=f0*l/P0、E0=f0/P0。不是支持任意SI Landau材料，也不把合成尺度当BaTiO3标定或默认参数。缺完整尺度即拒绝。

SI专业结果见[si.result.schema.json](schemas/si.result.schema.json)：results_si为物理视图，solver_dimensionless为原始nd结果，unit_mapping保留原输入、规范输入、公共quantity审计、求解器输入、尺度/系数和两份输入hash。artifact_dir/si保存完整fields_si.npz、history_si.csv/json、标注SI的静态图、mapping/summary/fields_units/readback/quality，以及独立original_input/normalized_input/normalization_report/solver_input/reference_scales JSON。原始XDMF/HDF5/NPZ、RT系数与数值QC仍是nd，不改标签。二维积分电焓为J/m，三维才为J；没有面外厚度不生成2D总J。

SI路径预算保守计入双份历史/数据工作量。unit_mapping passed只证明转换/映射与读回，Gauss/RT/能量等阈值仍在nd域；不把原绝对容差直接用于SI残差，不升级材料/实物/稳定性检查。

```powershell
# 先按下文配置PhasePython和MLCC_PHASE_FIELD_DEPLOYMENT
& $PhasePython -B -m mlcc preflight phase_field evolve_si --input modules/phase_field/examples/evolve_si_3d.json
$q = & $PhasePython -B -m mlcc run phase_field evolve_si --input modules/phase_field/examples/evolve_si_3d.json | ConvertFrom-Json
& $PhasePython -B -m mlcc worker $q.task_id
& $PhasePython -B -m mlcc artifact $q.task_id artifacts/si/fields_si.npz
# 显式小型单位回归：2D/3D各旧nd对照及两种等价SI输入，不是默认测试
& $PhasePython -B -m modules.phase_field.harness.verify_units --deployment $env:MLCC_PHASE_FIELD_DEPLOYMENT --run-real
```

## 模型与接口

旧入口model_profile=lgd_scalar_y_v03、units=dimensionless。固定alpha=-1、beta=1、gamma=0、L=1，极化向量(0,P,0)。3D是P(x,y,z,t)，仍只有一个极化分量和自洽phi。域固定[-8,8]×[0,4]，3D再乘[-2,2]；y=0/4电极phi=-applied_E*y，P自然边界，其余面自然位移通量。旧g、epsilon显式为正无量纲系数；旧epsilon不是材料相对介电常数。旧输入的时间、长度、场、电焓不直接贴SI标签。

三角形/四面体CG1、单MPI rank、UFL Jacobian、SNES Newton线搜索、preonly/LU，可选RT0/DG0约束L2重构用MUMPS。固定电压电焓积分为-P²/2+P⁴/4+g|grad P|²/2-epsilon|grad phi|²/2+P*phi_y。初始phi先求解与P一致的Gauss问题。Newton收敛不证明稳定极小态，到达end不证明达到稳态。

[steady输入](schemas/steady.input.schema.json)执行一次非线性稳态，无evolution字段。[evolve输入](schemas/evolve.input.schema.json)执行TDGL＋后向欧拉；end、dt、max_halvings全部明确，0<dt<1、max_halvings为0–7。每段连续失败有限缩步，恢复P/phi/old、时间、上次接受dt、固定场与电极值，失败试步不进入历史；另有总接受步数资源上限ceil(end/dt)*2^max_halvings+1，超过停止并保存最后接受态，不改变科学输入。这不是误差自适应。

四种初态在两维度均可用，各类型只能携带对应字段：uniform(value)；wall(width,wall_center)；nucleus(center[x,y],radii[rx,ry]，3D另需zcenter,zradius)；random(seed,modes,amplitude,reference)。wall宽度为绝对无量纲tanh宽度。核为来源余弦变形椭圆/椭球，中心严格在域内；奇异参数拒绝。3D random用三维有限余弦谱，固定seed/谱/幅值，每方向至少2*(modes-1)网格单元；不是节点白噪声、二维挤出或实测组织。MMS、验证时变边界、pin_wall和故障注入不在公开接口。

output.rt0、images为显式开关，history固定all_accepted。[输出schema](schemas/result.schema.json)包含网格/DOF/环境、接受拒绝计数与残差、P/phi/E指标、电焓、Gauss、读回和产物引用。P/phi平均是积分平均，E_magnitude.mean为等体积DG0单元幅值平均。wall.centerline_unique_x仅是y=2（3D再z=0）中心线唯一零交点，null为缺失/多交点/未解析，不是全局壁位置。JSON拒绝NaN/Infinity，CSV缺失交点留空。

## Windows调用

从项目根PowerShell执行：

```powershell
$PhasePython = 'C:/Users/Xiang/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
$env:PYTHONDONTWRITEBYTECODE = '1'
$env:MLCC_PHASE_FIELD_DEPLOYMENT = (Resolve-Path modules/phase_field/deployment/example.json).Path
& $PhasePython -B -m mlcc describe phase_field
& $PhasePython -B -m mlcc preflight phase_field evolve --input modules/phase_field/examples/evolve_3d_nucleus.json
$q = & $PhasePython -B -m mlcc run phase_field evolve --input modules/phase_field/examples/evolve_3d_nucleus.json | ConvertFrom-Json
& $PhasePython -B -m mlcc worker $q.task_id
& $PhasePython -B -m mlcc status $q.task_id
& $PhasePython -B -m mlcc result $q.task_id
& $PhasePython -B -m mlcc artifact $q.task_id artifacts/fields.xdmf
```

run只排队；worker推进一次；status/result/artifact与终态worker都不求解。路径、解释器、资源由宿主[部署样例](deployment/example.json)决定，不进入科学输入，不依赖fem私有状态。未配置/后端不可用即拒绝，无mock回退。Codex沙箱的WSL访问可能需正常工具审批，不迁移公共框架、不安装Windows FEniCS或升级共享环境。超时/通信中断不证明Linux求解已停止，保留任务与日志，禁止未核实自动重提交。

样例环境Ubuntu-24.04、既有fenicsx-env、1线程；最多6000单元、4,000,000单元加权工作量、64MiB未压缩两场历史估计，科学客户端180秒、公共Adapter240秒。工作量计入最坏缩步试次数，RT另加8倍单元权重。发布输入界限nx≤48、ny/nz≤12、modes≤8。它们是保守操作预算，不是性能或精度保证，超限拒绝，不自动粗化。来源最大已测规模不是本部署承诺。

产物都在artifact_dir：fields.xdmf与关联fields.h5必须一起保留；fields.npz保存完整2D/3D网格、P/phi/E、全部接受态P/phi历史；initial_fields.npz、history.csv/json、nonlinear.json、metadata/initial/environment/diagnostics/metrics/quality.json；可选flux_reconstruction.npz。native保存请求/响应、实际argv、部署hash和日志，任务内编译缓存不登记为公开科学产物。2D有P/phi/E及时间曲线，3D为标明位置的切片或单元中心层，另有真实体数据与读回。绘图失败单独warning，大数组不塞入LLM摘要。

RT0是约束后处理，保留原始弱残差、反力、通量、跳跃及重构修正量，不能因此声称CG1局部强守恒。任务QC沿用同模型V0.3的残差1e-8、电压1e-12、无源接受态电焓增量1e-8与实际RT指标1e-8；稳态不套瞬态终止/能量单调检查，无拒绝步则rollback不适用，未请求RT为not_checked。单任务网格/时间收敛、稳定性、材料标定、实物对照不自动通过。

## 验证与边界

```powershell
& $PhasePython -B -m unittest discover -s modules/phase_field/tests -v
& $PhasePython -B -m mlcc check
& $PhasePython -B -m modules.phase_field.harness.check_host
# 以下是显式真实小型求解，创建新任务
& $PhasePython -B -m modules.phase_field.harness.verify_small --deployment $env:MLCC_PHASE_FIELD_DEPLOYMENT --run-real
& $PhasePython -B -m modules.phase_field.harness.verify_final --deployment $env:MLCC_PHASE_FIELD_DEPLOYMENT --run-real
```

模块默认测试无WSL/LLM。harness将公共源码逐字节复制到模块内，再由Windows公共CLI --project调用；全部outputs/tasks仍由公共Runtime管理，没有手改record。公共默认unittest在独立副本执行，深路径用Windows长路径前缀避免MAX_PATH；原公共源码未改。方法[Skill](skills/mlcc-scalar-ferroelectric/SKILL.md)已由现有AgentHost离线核查；[LLM闭环命令](LLM_ACCEPTANCE.md)已提供，真实外发因本chat未授权而not_checked，不新增宿主/provider/Web。公共增强见[INTERFACE_PROPOSAL](INTERFACE_PROPOSAL.md)。

不支持完整BaTiO3定量预测、多分量/90度畴、多晶/RVE、弹性/电致伸缩/热/缺陷、任意波形、完整滞回、持久重启、大规模MPI或未经验证预条件器。材料适用性和实物对照为not_checked；许可证/对外分发另由来源所有者确认。来源与必要改动见[SOURCES.json](SOURCES.json)。


## 2026-10-26 可选 native Linux 部署接口

新增显式 `transport=native_linux` 的独立部署 schema 与 `deployment/native.example.json`，保留原 WSL 配置和科学输入。依赖在所选 Deployment 预检中确定验证，module.json 不再无条件要求 wsl.exe；这不表示后端已安装或科学预检已通过。使用同一 science_entry.py、独立 Conda Python 和原 UNIT/QC，不经 shell/SSH/自动回退。

配置、版本、检查和临时服务器验证后清理边界见 [main 交接](../../docs/server-deployment-2026-10-26/main-handoff.md)。新增接口未在本机运行科学求解，也不表示服务器永久部署或远程 Agent 已上线。当前源码指纹见 `NATIVE_LINUX_SOURCES.json`；旧 SOURCES / SCIENTIFIC_CORE_SOURCES / UNITS_SOURCES 继续保留为历史冻结。
