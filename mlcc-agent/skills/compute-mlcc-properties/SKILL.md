---
name: compute-mlcc-properties
description: 从同源 ABACUS 模型组织 MLCC 铁电介电、磁性、声子热学和电子热电四条性质链，明确跨链输入、可观测量与器件外推范围。
---

# 四条微观性质链

`compare-compositions --request <JSON> --output <比较产品JSON>`消费`mlcc.composition-comparison-request.v1`中的baseline、variants和selected_properties。每侧给出保存模型、产品、实际method文件与Study绑定；用保存模型谱系配对，调用共同方法比较接口保留共同/新增元素资源和方法差异。标量、3×3张量及显式Voigt/engineering-shear的6×6张量按声明单位、条件、坐标和逐侧组成归一；二阶张量可用显式旋转统一坐标，不支持的Voigt变换保留incomparable。缺真实掺杂物性或来源说明保留null与原因，裸总能不跨组成相减。`deliver-properties --study <baseline Study> --composition <比较产品JSON> --output <交付JSON>`交付完整保存比较；现有未收敛或未资格标记保留，不因此阻止可定义的差量。

`export-continuum --request <JSON> --output <SI参数包JSON>`将已保存来源转为`mlcc.continuum-parameters.v1`；`deliver-properties --study <同一Study> --continuum <SI参数包JSON> --output <交付JSON>`绑定保存包。`export-comsol --package <SI参数包JSON> --output-dir <新目录>`生成SI表、映射清单与COMSOL 6.3 Java API模板，介电映射由请求`comsol.permittivity_property`显式选定。来源、坐标、材料状态及缺项随包保留；当前出口不运行COMSOL或求解器件。转换与数值验收经Slurm，安装接入只消费已保存产品。

`dielectric-modes --request <request.json> --output <product.json>`消费同Study保存的Born、显式处理Γ和ionic三个JSON。请求schema为`mlcc.dielectric-modes-request.v1`，`study/born/gamma/ionic`路径相对请求文件解析，显式`displacement_gauge=euclidean_translation_free`。沿保存的完整光学本征基读模式，不重新对角化；保留原始Born和原始位移/耦合，同时计算`u0=P M^(-1/2)e`位移规范下的耦合、振子强度和模式介电贡献。λ只取保存的`eigenvalue_eV_per_A2_per_amu`，单位`eV/(angstrom^2*amu)`；`u0`不重归一或称新独立受约束本征模，raw耦合仅作规范敏感诊断。稳定完整空间的贡献和只与保存ionic作atol/rtol均1e-8的工程闭合比较；任何非正模或保存ionic未决时，各贡献及总和为null，全部模式/耦合照实保留。`deliver-properties --dielectric-modes <product.json> --study <Study.json> --output <delivery.json>`只保存交付，不重算。此功能限保存Γ本征基，简并空间单模分配随本征基，不生成有限q DOS、热容或阻尼谱；合同见`docs/p5-mode-resolved-response-v001.md`。

`interface-tangential --task <task.json> --output <product.json>`读取显式固定胞夹持/内部弛豫的切向路径；原始力沿显式切向投影，法向仍绑定保存的界面几何。`deliver-properties --interface-tangential <product.json> --study <Study.json> --output <delivery.json>`只交付保存响应、原生job/停止原因、单位、模型与界面来源，不重算。缺完成原生任务时响应null/unresolved；未收敛已有数值及原生原因保留。两周期界面的胞净响应不自动除2，返回夹持坐标不称物理恢复。输入`normal_cartesian`与`tangential_cartesian`需显式单位且正交，分组、面积、minimization和逐点q均显式；本切向路径待Slurm新检查。

`interface-electrical --study <Study.json> --request <request.json> --output <product.json>`消费已保存的界面ABACUS静电势产品，请求显式指定网格轴、方向、边界及两个整数半开区域。输出平面平均电子势能、正试探电荷电势、相邻面法向场、区域电势差及可选同模型参考差量，保留单位、符号和来源。`deliver-properties --interface-electrical <product.json> --study <Study.json> --output <delivery.json>`只将保存产品接到同Study，不重算或重读原生cube。缺界面势时请求显式`potential_path:null`与`missing_source_reason`，`selection:null`、响应null及未决原因原样交付；已有Ni/BTO结构和普通E/F势不充当静电势。新接线待Slurm验收，合同见`workspace/reports/interface-electrical-v001/handoff.md`。

`local-stress --task <task.json> --request <analysis.json> --output <product.json>`按显式原子ID组/窗口求逐原子virial之和，再按声明体积与来源得到局部GPa张量；缺体积保留广延量和null应力，不采用默认原子体积。`deliver-properties --local-stress <product.json> --study <Study.json> --output <delivery.json>`接同Study。全胞压力不作为局部数据，缺无应力参考和历史时不生成局部热应力。见`docs/p11-local-stress-contract-v001.md`。

P11 的 `interface-thermal --task <task.json> --request <analysis.json> --output <product.json>` 从热数据任务消费显式窗口内的热浴功率和空间温差，`deliver-properties --interface-thermal <product.json> --study <Study.json> --output <delivery.json>` 接同Study。周期双界面不自动平分热流；仅在请求明确分流来源和比例时计算相应的片区J/G/R。保留未提供窗口、温度片区、原生热数据或分流声明的缺项，不拿整体能量漂移代替热流。完整定义见 `docs/p11-thermal-response-contract-v001.md`。

P11 的 `interface-normal --task <task.json> --output <product.json>` 读取明确分组的固定胞刚性法向位移原生任务；输出 R=-F_B·n、R/A、逐区间刚度及坐标返回闭合残差。通过 `deliver-properties --interface-normal <product.json> --study <Study.json> --output <delivery.json>` 接同 Study。保留原始力/能量、unwrapped坐标、单位、两侧来源和真实Slurm状态；两个周期界面反向开口不除2。未运行实例响应为null，数值处理仍在站点Slurm，完整协议见 `docs/p11-normal-response-contract-v001.md`。

同一入口消费显式`fixed_cell_clamped_internal_relaxation`：R取最小化后受控夹持的原始力，A侧夹持反力、自由原子力、原生停止摘要和`relaxation_status`一并交付。未收敛点仍保留已有数值及停止原因，不写成调度失败或补造收敛；自由内部原子可移动，单个AB/BA开口没有从该夹持坐标中自动提取，面积不除2。新路径实现及待验收范围见`workspace/reports/interface-normal-relax-v001/handoff.md`。

`transport --request <JSON> --output <JSON>` 将已保存 ABACUS 完整均匀 k 网格能带接到固定 BoltzTraP2 26.3.1。温度、相对原生费米能的化学势、积分能窗、分箱和插值参数均显式传入。输出 S、sigma/tau、kappa_e/tau、PF/tau；PF 使用 `S.T @ sigma_over_tau @ S`。nspin2 先合并两自旋能带/积分再求总响应，显式磁对称输入缺失则该实例 unresolved；不自动用 seed 或总磁矩代替最终局域矩。`deliver-properties --study <JSON> --transport <保存产品> --output <JSON>` 交付同Study，不重算。请求字段见 `docs/p8-transport-data-contract-v001.md`；后端在站点 CPU Slurm 中按实际 API 运行，本地 CLI 使用 lazy import。没有 tau、ZT、晶格热导混合、新DFT/MD或材料精度矩阵。

`magnetic --task <保存的ABACUS任务目录> --output <JSON>` 消费现有共线自旋结果。可用 `--electronic <已有同任务电子结果JSON>` 附带保存的自旋通道数据。输出原生每胞总磁矩（muB）和按原子数归一的均值（muB/atom），初始种子、原生收敛和任务/模型/方法/Slurm 来源单列；均值不是逐原子局域磁矩。缺少输出不填零，未收敛观测保留未收敛，不据总磁矩判断 FM/AFM。`deliver-properties --study <JSON> --magnetic <保存产品JSON> --output <JSON>` 接入同一 Study。此入口不提交计算，不扩展初始磁态写入、SOC、MAE、交换或温度任务；数值消费在站点 Slurm 内执行。

`charge-correction --request <JSON> --output <JSON>` 使用固定发布版 pymatgen-analysis-defects 2026.3.20 从已绑定的 ABACUS 电子势网格计算标量 FNV。请求显式提供电荷、缺陷分数位置、标量介电及来源、QModel、积分参数和三轴中点采样宽度；不平均张量、不找缺陷、不把旧区域势差当修正。`charged-formation --request <JSON> --output <JSON>` 消费保存修正、同宿主化学参考交付及 EF 网格，复用已有形成能公式，原始宿主 VBM 与修正各计一次。`charge-transitions --request <JSON> --output <JSON>` 消费共同宿主/方法/μ/VBM 的已保存形成能与明确 EF 区间，接入已有稳定下包络函数。缺项保持 missing。`deliver-properties` 对应新增 `--charge-correction`、`--charged-formation`（缺陷 Study）及 `--charge-transitions`（共同宿主 Study）参数；三者互斥。数值处理经 Slurm，使用实际安装版本，不因此新增 DFT/MD。具体请求字段见 README。

NAC 的 `dynamical_hermitian_tolerance` 必须显式提供（eV/Å²/amu）；计划限 `is_symmetry=false`、`hermitianize_dynamical_matrix=false`。本机 Phonopy 4.8.3 需使用显式关闭 Hermitian 化的底层 Rust 接口；不通过 run_qpoints 的默认对称化掩盖原矩阵问题，残差超限即报错。

`phonon-nac --request <JSON> --born <JSON> --electronic <JSON> --output <JSON>` 消费已保存力常数、完整同模型 Born 和电子 ε∞，只算显式 Γ 极限方向的 Wang NAC。请求继承 phonon-gamma 保存源与容差字段，增加 `nac_method=wang`、`direction_basis=primitive_reciprocal_fractional` 和非零 `nac_q_direction`。不拟合力常数、不施加 ASR、不改固定 E=0 离子介电 Hessian。`deliver-properties --p5` 请求中的可选 `nac` 路径将其作为同 Study 的独立声子产品交付，需同一 born/electronic 来源；保留方向、单位、原子/质量映射、数学身份和未资格状态。单方向结果不是完整极性谱或材料资格，全部数值工作仍通过站点 Slurm。

`create-berry-strain`生成指定分量±应变的固定分数坐标模型和SCF输入；`create-berry-strain-nscf`只在该点SCF原生来源验证后接一个gdir，不提交任务。`polarization-strain --request <JSON> --output <JSON>`消费保存Berry结果，逐点按原生量子倍数恢复reduced charge，以参考胞求proper e，并独立求improper变化。`deliver-properties --study <父Study> --polarization-strain <结果> --output <JSON>`只交付。工程剪切gamma=2epsilon，gdir为晶格方向；完整Cartesian列需三个方向和显式分支，缺项不补零。该首切片无relaxed-ion、d或电致伸缩，不授予科学资格，全部数值运算经站点Slurm。

`polarization-energy --request <JSON> --output <JSON>`消费同父、固定胞、有序的保存SCF能量，输出每胞相对能量、端点差和采样最高点。请求字段见README；允许不同子Study/model，必须绑定各自来源和共同父关系。Berry附件只保留极化信息，缺分支不阻塞能量路径；禁止以NSCF能量替代SCF。`deliver-properties --study <父Study> --polarization-energy <保存结果> --output <JSON>`只交付，不重算。采样最高点不是NEB势垒、双阱证明或有限温度自由能，数值处理仍须站点Slurm。

`potential-alignment --request <JSON> --output <JSON>`计算显式同网格区域的defect-minus-host电子势能差及分布，绑定已保存的同task电子/势来源；`deliver-properties --study <缺陷Study> --potential-alignment <结果> --output <JSON>`只交付保存诊断。请求/index_boxes字段见README。缺网格或选区保留missing，不自动找平台；候选VBM移位不等于物理对齐，原始势差不等于形成能接口的potential_alignment_eV能量项，不自动乘q或叠加FNV。全部数值运算在站点Slurm执行。

化学参考使用`chemical-references --request <JSON> --output <JSON>`绑定已保存总能/组成，按显式参考角色、相和formula_stoichiometry归一化。经`deliver-properties --study <JSON> --chemical-references <集合JSON> --output <JSON>`接已有化学势域函数；`neutral-formation --chemical-reference-delivery <交付JSON>`仅消费其native chemical_point。请求字段见README。不得代选元素/竞争相、猜μ点或把host/defect总能差当μ；缺项保持null，数学点与native点分开。按共同物理字段及共同元素赝势比较，逐源保留实际method_set/数值协议；组名不能建立科学等价。只在站点Slurm做数值归一化/消费，复用保存电子源，不重解析能级。

`mlcc electrostatic-potential --task <SCF任务目录或task.json> --output <JSON>` 消费本任务的ABACUS3.10.1 `ElecStaticPot.cube`。生成任务时在方法配置顶层显式设置 `output_control: {"out_pot": 2}`；当前限PW/NC、固定胞SCF、非SOC共线nspin1/2，无外场/偶极/栅极/溶剂。未请求时保持原输入。输出保留Ry电子势能、Bohr网格/原子头、元素到源atom_id映射、实际Slurm任务与收敛证据；势为离子局域势加Hartree，不含XC。不得将它当正电荷电势、自动减EF/均值或把单宿主势当共同能标；对齐/FNV/带电形成能仍为null。解析在站点Slurm执行，单纯cube解析或软件样例不授予原生/GPU或科学资格。

缺陷电子参考使用`deliver-properties --study <缺陷Study.json> --defect-references <参考请求.json> --output <JSON>`，与`--tasks`和`--p5`互斥。请求指向保存电子JSON及缺陷model.json，字段见README；复用已有电子解析结果，保留host/defect的各自能标、方法、原生job和模型谱系。VBM/CBM/EF是采样参考，不能用费米差、总能差或电荷密度替代势对齐；缺势/μ/介电/修正时带电形成能等保持null。该后处理在站点Slurm执行，不重跑DFT，不把工程传递通过等同科学资格。

P5 Study最终交付复用`deliver-properties --study <JSON> --p5 <产物请求JSON> --output <JSON>`，与原`--tasks`互斥。请求及来源模式见README。保存的Born/Γ/电子/离子/总介电需绑定同父模型与物理方法，单位/原子映射/来源配对不符时拒绝；缺项逐项保留，数学例不变为材料结果。SCF/NSCF各自的数值协议原样记录，不把求解器阈值机械相同当作跨模块物理身份或精度资格。此交付不启动引擎计算。

0.30新增真实来源消费：`electronic-dielectric --request <JSON> --output <JSON>`读取ABACUS LCAO矩阵经PYATB direct-static得到的电子贡献；P5既有born/gamma/electronic路径也接受显式原生Born整数分支族、P5 LCAO原始Γ及保存电子产品。保留分支族系数、全模型原子顺序、独立位移位点、原文与Slurm来源；系数不当作已选物理Born，raw Γ不隐式对称化或ASR。未选物理分支或Γ条件不满足时仍交付来源与具体原因，离子/总介电保持null。所有数值消费经站点Slurm，使用用户提供的实际路径；不得为交付重跑源计算。原PW Berry创建器的限制仍按自身合同执行，不能把其输入标签改成LCAO。

P5已有分支审阅、Born汇总和固定胞介电消费入口，参数见README。`berry-branch-review/consume`不自动选分支；`born-charges`按稳定atom_id和位移列聚合，缺列不补零。`phonon-gamma`消费已有P7力常数和显式同胞映射；`ionic-dielectric`使用完整Born与固定E=0 Γ Hessian，在三平移模正交补求解，光学负/近零模保持未定。`dielectric`只将同方法电子epsilon_infinity与离子增量相加，不重复真空I；缺电子只阻止总量。软件数学正例不作为原生DFPT/完整Born或材料科学资格，全部数值消费在站点Slurm执行。

0.9.0 已有电子/DOS、六分量应变规划、完整张量标定/拟合门、缺陷热力学和性质交付/设计比较；四条专用性质链仍逐项实现。生产链以已验收 ABACUS 模型和方法为输入；缺数据标明未算，不借 VASP 结果冒充。

`mlcc electronic --task <完成的SCF任务目录> --output <新报告>` 读取原生 istate.info、kpoints、running_scf.log，核对任务/方法/模型归属、调度终态、电子数和占据，保留来源。只支持 nspin=1/2、完整 Gamma 零偏移均匀网格。fixed 整数占据输出 sampled-mesh KS gap，有限展宽返回 gap=null；不把它解释为基本带隙、路径能带、生产精度或缺陷费米能级参考。

`mlcc electronic-dos --task <目录> --emin <eV> --emax <eV> --points <数量> --sigma <eV> --output <新报告>` 对全部原生能级做显式 Gaussian 后处理，正确处理 k 权重/自旋简并，报告 states/eV/cell 和窗口积分误差。sigma 是后处理标准差，与 SCF 展宽及晶格温度分开；此入口不计算 PDOS。

`mlcc elastic-plan --model <目录> --amplitudes <h> <2h> --output <新计划>` 生成 25 点协议。`elastic-calibrate --reference-task <目录> --strained-tasks <24目录> --thresholds <JSON> --output <新JSON>` 用能量差分和功共轭应力确定全局符号。`elastic-analyze` 另外接 `--calibration`，重新核对全部原生数据与标定，检查两幅值、六方向成对覆盖、秩/残余应力/线性/斜率一致性/非对称性。阈值在 README 列出，必须预先明确。缺完整数据则 Cij=null，不因软件实现改写旧 Ni 失败结果。当前是静态 clamped-ion，不是 relaxed-ion 或烧制温度弹性。

`chemical-potential-region`、`formation-energy`、`binding-energy` 消费显式 JSON；`neutral-formation` 另需真实宿主/缺陷任务和派生 model.json，保持中性固定胞 SCF 路径。带电路径由独立 `charge-correction → charged-formation` 入口处理。`deliver-properties` 绑定保存来源与 Study；`assess-design` 使用显式指标，缺少指标时保留 not_assessed。

铁电/介电：Berry-phase 极化差需连续分支与参考路径；区分 ε∞、离子响应和器件有效介电。离子响应依赖力常数/Born。金属体与金属化超胞不能直接套绝缘体体极化。0 K 双阱不是 T 相关自由能；普通 E/F 势不自动预测极化/开关。

0.10.0 Berry 候选的 CLI 顺序是 `mlcc create-berry-reference --study <study.json> --model <模型目录> --method <method.json> --site <site.json> --request <SCF request.json>`、`mlcc create-berry-nscf --reference-task <SCF任务目录> --method <method.json> --site <site.json> --request <NSCF request.json>`、`mlcc parse-berry --task <NSCF task.json>`。参考 SCF 通过 `out_chg=1` 生成 `OUT.<suffix>/SPIN1_CHG.cube`；NSCF 必须绑定该真实电荷并显式使用 `init_chg=file`、`read_file_dir=./`、`berry_phase=1`、`gdir` 和 `pw_diag_thr`。当前输入合同严格限定 ABACUS 3.10.1 PW、nspin=1、fixed、非 SOC、共线、`symmetry=-1`，且只接一条方向。解析结果保留 `branch_status=not_unwrapped`，科学/数值/生产资格均为 false；没有 Born/DFPT/有限场/介电计算或分支解缠结论。CPU兼容任务的真实原生输出已通过候选解析/入口检查；历史GPU故障的定向修复已提供原生执行/解析证据；历史数值对照未过仍留档，具体版本以workspace发布记录为准。该证据不授予极化/介电生产资格，不再重算已有CPU任务。所有材料、方法和站点路径必须来自显式参数或配置，不能使用技能内默认值。

0.14新增P5消费入口：`mlcc deliver-polarization --study <JSON> --task <Berry任务目录> --output <新JSON> [--targets <JSON>]` 只读原生来源，交付单方向P、量子、方向、未解支状态与SCF/NSCF调度来源；无指标not_assessed，未资格数据不能判设计达标。`mlcc polarization-path --request <路径JSON> --output <新JSON>` 消费固定胞/同方法/组成/原子映射的保存原生结果，按显式整数分支和依据做P+nQ代数；单点、缺分支或无结构变化时ΔP=null，保持unresolved或ambiguous状态。请求合同见README。两命令均须在计算站点Slurm后处理作业中执行。不能复制单点充当真实路径，不能据此输出自发极化、Born电荷或介电张量。当前安装启用事实以workspace发布记录为准。

磁性：Ni、开壳层掺杂/缺陷比较合理自旋态，目标需要时增加 U/SOC、交换/各向异性。芯内 f 电子不能支持该 f 壳层磁性结论。非磁体做必要参考，不强行造磁序；磁性与铁电/热电分开。

声子/晶格热学：ABACUS 有限位移力交 Phonopy，位移态不再弛豫。极性非解析修正需 Born/ε∞。高温稳定相的 0 K 软模需相应非谐解释。热膨胀/QHA 只在适用相；κl 另需三阶力/BTE 或合格 MD，不由声子谱直接推导。Ni 总热导还含电子项。

热电：ABACUS 稠密均匀 k 能带到选定 BoltzTraP2 版本的数据桥需要实际实现与参考对照。记录晶格/k/能量零点/电子数/自旋/单位，输出 S、σ/τ、κe/τ、PF/τ。给定 τ 并取得 κl 才输出实际 σ/κ/ZT；说明刚性带/常 τ 近似及绝缘介质漏电代价。

四链共用模型但不无条件串行：力常数、Born 与 ZT 依赖由真实任务指向；没有这些输入不得提前输出结果。性质记录 T、E、f、应变、单位、方法、数据与任务来源/有效范围。

器件 C 还需要几何和有效响应；带隙不是额定耐压，声子频率不是 SRF，微观 ε 不是所有 T/V/f 下的量产器件 ε。


声子执行入口为 `phonon-plan`、`create-phonon`、`phonon-forces`、`phonon-qpoints`，准确输入合同见 README 的 0.9.0 节。计划固定 Phonopy 4.8.3，显式超胞/primitive/位移幅度/对称开关；复读真实母模型并检查每个结构及原子谱系。位移子模型和 Study 使用新身份，任务通过既有 ABACUS/Slurm 生命周期。原生力组装必须包含 reference 和全部正负位移、同方法/赝势/k 点/单位与模型谱系，缺数据不拟合；原始残力/漂移不自动扣除。指定 q 点采用 primitive reciprocal fractional 坐标。当前软件结果保持未获科学资格，不能据此声明烧制温度相稳定、介电离子项或晶格热导。
