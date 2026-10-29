---
name: mlcc-scalar-ferroelectric
description: Prepare and interpret MLCC phase_field steady/evolve or explicit-scale SI variants for scalar LGD in 2D/3D. Use for the registered P/phi model and its evidence, not arbitrary calibrated material prediction.
---

# 铁电相场方法

本文件是按需读取的方法细节；创建、提交、查询和读取以[顶层运行Skill](../../../../skills/run-mlcc-phase-field/SKILL.md)及[公共生命周期](../../../../skills/references/task-lifecycle.md)为准。专业输入/schema、物理定义与检查仍由本模块维护。

本 Skill 仅适用于下述四个旧标量操作。新增全矢量 `vector_*` 操作使用独立的 [矢量方法](../mlcc-vector-ferroelectric/SKILL.md)，不得把标量边界、RT0、固定系数或壁宽语义套用到矢量输入。

固定模块 `phase_field`，操作 `steady`（非线性稳态）、`evolve`（TDGL＋后向欧拉）。维度由 `dimension` 明确为 2 或 3。已有输入文件通过顶层任务参数的 `input_path` 引用；获明确许可的示例同样引用实际文件，不重抄或修改数值。缺少科学输入时澄清，不猜初态、阈值或材料参数。

新增可选`steady_si`、`evolve_si`用于明确有量纲输入；原steady/evolve仍完全无量纲。SI入口只接受`{value,unit,source:{kind,reference}}`，见[SI稳态schema](../../schemas/steady_si.input.schema.json)、[SI演化schema](../../schemas/evolve_si.input.schema.json)和[单位设计](../../UNITS_DESIGN.md)。必须给出正有限length、polarization、time、energy_density四个reference_scales及来源，缺项澄清/拒绝，不能猜材料尺度或复用合成例子作默认。参考[合成三维SI例](../../examples/evolve_si_3d.json)仅用于转换验证。

SI入口g为物理梯度系数κ（J*m³/C²），epsilon为绝对介电系数（F/m），applied_E为V/m；epsilon_r不支持，不能与旧epsilon*混淆。SI初态的极化值/幅值/reference、长度位置/宽度/半轴和演化时间均须明确量值与单位，网格计数/seed/modes仍裸整数。公共唯一单位核心先转canonical SI，模块再按显式尺度无量纲化，科学进程不重复按原单位换算。profile仍限制alpha*=-1、beta*=1、gamma*=0、L*=1，物理系数由尺度推导，不是支持任意Landau材料。

SI结果位于`results_si`，原始无量纲结果位于`solver_dimensionless`，映射与审计位于`unit_mapping`；原始量值/来源及canonical值不能混写。2D电焓是J/m，3D才是J；无厚度不生成2D总J。完整SI数据/历史/图在artifacts/si/，原始XDMF/HDF5/NPZ和数值QC仍为无量纲。禁止把nd绝对容差用于SI残差或把SI标签当材料标定。unit_mapping检查通过只证明映射，material_validity等仍not_checked。

旧入口输入以 [steady schema](../../schemas/steady.input.schema.json)、[evolve schema](../../schemas/evolve.input.schema.json) 为准；完整小例见 [二维演化](../../examples/evolve_2d.json)、[三维演化](../../examples/evolve_3d.json)。这些旧入口的所有科学量无量纲，`units=dimensionless`、`model_profile=lgd_scalar_y_v03`。profile 固定 alpha=-1、beta=1、gamma=0、L=1，矩形 [-8,8]×[0,4]，3D 再乘 [-2,2]。仅极化 y 分量 P 和电势 phi 为未知量。旧`epsilon`是模型无量纲系数，不是材料相对介电常数；旧时间、长度、场、能量不得直接贴SI标签。

网格 `nx,ny`，仅3D要求 `nz`；三角形/四面体、CG1、单MPI rank、直接LU。`g,epsilon` 为正；`applied_E` 给出固定 phi=-E*y 电极条件，其他面自然边界。来源固定电压电焓是包含 -epsilon|grad phi|²/2+P*phi_y 的泛函，不改写成正定电场储能。

四种初态在两维度均支持，各类型只允许对应字段：uniform(value)；wall(width,wall_center)；nucleus(center[x,y],radii[rx,ry]，3D另需zcenter,zradius)；random(seed,modes,amplitude,reference)。壁宽是绝对无量纲 tanh 宽度，不是倍数。核中心须严格在域内；余弦变形核不是任意几何组织。三维 random 是三维有限余弦展开，相同seed/谱在不同网格上定义同一连续函数，不是白噪声或二维挤出。预检拒绝奇异参数和欠解析的谱。

`evolution` 只用于 evolve：end、0<dt<1、max_halvings(0–7)。这是失败缩步，不是误差自适应；拒绝试步完整保留，只有接受态进入历史。源算法每段失败有限重试，模块另有总接受步/历史预算护栏。`output.rt0` 决定重构，`images` 决定图像，`history=all_accepted` 保留全部接受态。宿主显式绑定解释器、部署和资源预算；输入与模型不能生成这些部署设置。预算不足即拒绝，不自动粗化或改物理输入。

顶层create-task准备未提交任务，执行授权后由SiteRunner经Slurm执行一次；领域预检在Slurm内完成，Agent只选择与解释，不决定科学QC。read-result只读取保存证据。失败/中断时保留原任务与native证据；SCIENTIFIC_STATE_UNKNOWN 不证明Linux进程已停止，不能自动重提交。修改参数必须成为明确新任务。

解读先核对 execution，再逐项报告 numerical/scientific QC。稳态没有演化终止时间要求；Newton收敛不证明稳定极小态，演化到end也不证明稳态。失败试步不是最终任务失败，恢复成功仍保留失败日志。RT0 是约束后处理；其强制守恒不能使原始CG1通量成为局部强守恒。结合 gauss 中原始弱残差、反力、原始边界通量及重构修正量解释。

结果字段/产物见 [输出schema](../../schemas/result.schema.json)。P/phi平均值为体积积分平均；E_magnitude.mean为均匀单元的DG0幅值平均。wall.centerline_unique_x 仅代表 y=2、3D再加z=0中心线上的唯一交点；null表示缺失、多个交点或未解析，不能当全局壁位置。原生fields.xdmf与fields.h5须一起保留，NPZ包含完整2D/3D场和接受态历史。PNG是展示，3D切片标明位置，不代替体数据或原生读回；绘图失败只是警告。

单任务默认不检查网格/时间收敛、稳定性、材料标定和实物对照，保留not_checked。数值容差只沿用同一无量纲V0.3路径；不扩大成BaTiO3定量预测、多分量/90度畴、多晶、RVE、弹性、热、缺陷、任意波形、完整滞回、持久重启或MPI能力。模型解释与原始权威结果分开。模型服务及外发权限遵循当前宿主配置与用户授权，宿主接入验收不继承其他模块的结论。
