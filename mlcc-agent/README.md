# MLCC Agent

新增源码入口：`charge-correction`、`charged-formation`、`charge-transitions`，均使用 `--request REQUEST.json --output NEW.json`。实际启用版本以 workspace 发布记录为准。

`charge-correction` 请求 schema 为 `mlcc.charge-correction-request.v1`，字段为 `correction_id`、`host_electronic_path`、`defect_electronic_path`、`descriptor_path`、`host_potential_path`、`defect_potential_path`、`parameters`。参数包含整数 `q`（正值移除电子）、`defect_frac_coords`、`dielectric:{value,unit:"dimensionless",source}`、`q_model:{beta,gamma,expnorm,unit:"Bohr"}`、`integration:{energy_cutoff_eV,mad_tol,step}`、`sampling:{policy:"midpoint_after_defect_shift",axes:[0,1,2],width_angstrom}`。固定后端为 pymatgen-analysis-defects 2026.3.20 的标量 FNV，显式保存图像能、轴向/平均对齐位移、q 乘数、对齐能和总修正；不平均介电张量、不自动定位缺陷。路径相对请求文件解析，明确缺失的势或参数写 null。

`charged-formation` 请求 schema 为 `mlcc.charged-formation-request.v1`，字段为 `formation_id`、`correction_path`、`chemical_delivery_path`、`ef_grid_eV`。消费已保存修正及同宿主化学参考交付，调用现有形成能公式；使用宿主原始 VBM，图像项和对齐项只计一次。`charge-transitions` 请求 schema 为 `mlcc.charge-transition-request.v1`，字段为 `transition_id`、`formation_paths`（记录名到形成能路径）、`ef_interval_eV`；绑定共同来源后调用既有稳定下包络函数。任一输入缺失时保持 missing，不推断 EF 区间或补零。

`deliver-properties --study STUDY.json` 增加互斥参数 `--charge-correction RESULT.json`、`--charged-formation RESULT.json`、`--charge-transitions RESULT.json`。前两者绑定缺陷 Study，后者绑定共同宿主 Study；保留完整来源、原始 job 和状态。数值处理均经所选站点 Slurm。外部公开 VASP 对照与软件数学夹具明确标注，不混入 ABACUS 原生标签。

0.33 新增 `mlcc born-affine --family FAMILY.json [--review REVIEW.json] --output NEW_BORN.json`。消费保存的原生 LCAO affine 分支族，按外部审定的完整整数向量计算 `Z=base+sum(n_k*C_k)`；Cartesian 轴、单位 e 和原子顺序保持原样。审定 schema 为 `mlcc.native-born-affine-review.v1`，须绑定 family_path/context/完整 integer_labels，并提供 reviewer、reviewed_at、rationale、decision 和每个独立位移组的 continuous_branch_evidence。accepted 时 integer_shifts 必须逐标签为整数；连续证据逐组提供 atom_id、direction_index、kind=continuous_polarization_path、source_refs 和理由。无审定、deferred/rejected 或缺连续证据继续 unresolved，Born 张量为 null。外部审定并不等于软件证明物理连续性；科学/生产资格仍 false，不自动选支、换轴或投影。结果沿用 born-charge-columns，可进入现有 ionic-dielectric、dielectric 和同 Study deliver-properties；原始族与审定依据保留，交付时从源重建比对。数值运算仍必须通过所选站点 Slurm；实际发布状态以 workspace 验收记录为准。

0.32 新增站点内公共 `inspect-nao --method METHOD.json --site SITE.json --output NEW_SNAPSHOT.json`，在计算站点经Slurm执行。方法用 `numerical_orbital_library` 明确库的name/version/functional、配套说明pairing_source和逐元素UPF文件名记录pseudopotential_map；读取已选NAO原生头并保存原配套说明/映射，输出已有 `mlcc.nao-header-snapshot.v1`。将该输出设为方法的 `input_qualification.orbital_header_snapshot` 后调用既有qualify-method/create-abacus。只读显式路径，不扫描资源库或更换选择；PBE依据标记为库配套声明，输入和材料资格分别判断。保存结果继续用原始TaskRecord及job ID走既有parse-abacus/electronic/响应交付；未执行的新任务不接收历史job ID。

0.31 将真实 LCAO producer 接入既有 `create-abacus --study ... --model ... --method ... --site ... --request ...`，随后仍显式执行 `prepare`，创建器不会提交计算。方法顶层选 `basis_type="lcao"`、`numerical_orbital_ids` 和可选 `lcao_output`（out_chg/out_bandgap/out_mat_hs2/out_mat_r四项显式0/1），站点用 `abacus.numerical_orbital_files` 解析资源；`input_qualification.orbital_header_snapshot` 绑定原生NAO头及库配套来源。首切片仅中性、非SOC、nspin1/fixed、GPU/cusolver固定胞SCF。生成NUMERICAL_ORBITAL、完整原子映射、轨道复制脚本及请求产物记录；PW保留原有路径。Gamma/Born/物理分支不作为创建前置。创建成功不表示引擎已运行、矩阵已观察或材料生产资格已通过。

0.29 增加指定 Γ 极限方向的 NAC：`mlcc phonon-nac --request REQUEST.json --born BORN.json --electronic ELECTRONIC.json --output NAC.json`。请求使用 `phonon-gamma` 已有的保存力常数/计划、父模型、方法、source_binding 和四项容差，另显式指定 `nac_method="wang"`、`direction_basis="primitive_reciprocal_fractional"`、`nac_q_direction=[1,0,0]`（或所需非零方向）。输入必须有完整同模型 Born 与电子相对 ε∞；质量和原子顺序以同胞 primitive 映射为准。保存无 NAC 基线及方向修正后的动力学矩阵、频率和单位转换，保留负频、不重新拟合力常数、不施加 ASR。

已有 `deliver-properties --study STUDY.json --p5 REQUEST.json --output DELIVERY.json` 的请求可增加 `nac` 结果文件路径，连同显式 `born` 和 `electronic` 输入接入同一 Study。NAC 是单独的声子产品，不替换 `gamma`，也不送入固定 E=0 离子介电 Hessian。全部计算与数值交付通过站点 Slurm。软件数学夹具只验收接口及矩阵计算，科学与生产资格仍为 false；真实材料输入缺失不能补零或借用数学数据。实际发布状态见 workspace 验收记录。

NAC 请求还须明确 `dynamical_hermitian_tolerance`（eV/Å²/amu；本次工程验收 1e-12）。当前限 `is_symmetry=false`、`hermitianize_dynamical_matrix=false` 的保存计划；底层 Phonopy Rust 调用显式关闭 Hermitian 化，先记录并检查原矩阵残差，再求带符号频率。不会借对称化隐藏不一致输入。

0.25增加固定晶胞离子弛豫来源桥。`create-abacus`的`calculation=relax`请求显式提供`ionic_constraints={coordinate_basis:"cartesian",atom_ids:[...],move_flags:[[1,1,1],...]}`，覆盖每个原子ID且至少一个自由分量；不带应变变换。使用ABACUS3.10.1新CG实现；部分坐标冻结仅支持正对角轴对齐正交胞，全原子自由/冻结支持一般固定胞。SCF请求不携带离子约束。解析保留原生电子/离子停止原因和自由分量最大力，未收敛时的最终STRU可能是尚未评估的下一构型，不可晋升。

`derive-relaxed-structure --task TASK.json --parent-model MODEL_DIR --study STUDY.json --request REQUEST.json --output NEW_DIR`仅消费已保存且可晋升的弛豫结果。请求明确新的`model_id/version/study_id`，输出`model/`、`study.json`和`bridge.json`，保留原子ID、约束、相/掺杂、原生job和结果来源。`create-relaxed-scf --bridge bridge.json --method METHOD.json --site SITE.json --request SCF_REQUEST.json`使用该新模型和Study调用现有SCF创建器；请求含`berry.role=reference_scf`时走现有Berry参考SCF资格检查。它不复用relax电荷、不提交、不自动授予绝缘/铁电/材料资格。后续Berry NSCF必须使用该参考SCF自身的新电荷。变量晶胞、NEB和完整relaxed-ion响应不在此切片。所有建模和解析仍在站点Slurm。

0.24候选增加固定分数坐标的极化—应变链：`create-berry-strain --study ... --model ... --method ... --site ... --request ... --output ...`物化显式单分量±应变模型和未提交SCF任务；其自身SCF完成后，`create-berry-strain-nscf --manifest ... --point-id ... --site ... --method ... --request ...`接续一个指定gdir。创建器不提交任务，DFT资源必须显式time=0。`polarization-strain --request REQUEST.json --output RESULT.json`消费保存的Berry来源；`deliver-properties --study PARENT.json --polarization-strain RESULT.json --output DELIVERY.json`交付保存结果。

工程Voigt顺序xx,yy,zz,yz,xz,xy，剪切gamma=2epsilon，行晶胞C'=C@F.T。每点按自身量子及显式分支恢复reduced charge，再用参考晶胞计算proper e；独立保留improper极化差，单位C/m²。非正交胞的gdir是晶格方向，完整Cartesian列需要三个方向。缺来源/分支逐项保持null，不补零；只生成所选分量，不生成全矩阵。首切片限clamped-ion、无外场，不输出relaxed-ion、d或电致伸缩，不授予材料资格。实际启用状态以workspace验收记录为准。

0.23增加固定胞有序SCF能量路径：`mlcc polarization-energy --request REQUEST.json --output RESULT.json`。请求schema `mlcc.polarization-energy-request.v1`，明确`path_id/path_basis/parent_study_file/parent_model_path`、`path_coordinate={name,unit}`、`mechanical_constraint={kind:fixed_cell,description}`、`reference_point_id`，以及至少两个按`coordinate`严格递增的`points`。每点包含`point_id/scf_task_file/scf_result_file/berry_result_file`，最后一项可为null。只读保存的charge-producing SCF结果，不使用Berry NSCF能量。

同组成、原子谱系、物理方法和固定胞的完整输入得到每胞eV相对能量、端点差和采样最高点。允许具有显式共同父关系的不同子Study/model。缺Berry或极化分支不阻止能量曲线；不输出NEB势垒、有限温度自由能或铁电翻转资格。`deliver-properties --study PARENT_STUDY.json --polarization-energy RESULT.json --output DELIVERY.json`只交付保存结果，不重算。全部数值处理经站点Slurm；工程数据和数学fixture不授予材料资格。

0.22新增显式选区势差诊断：`mlcc potential-alignment --request REQUEST.json --output RESULT.json`消费已保存的同胞、同网格host/defect势与同任务电子来源。请求schema为`mlcc.potential-alignment-request.v1`，明确`alignment_id`、`host_electronic_path`、`defect_electronic_path`、`descriptor_path`、`host_potential_path`、`defect_potential_path`及`selection`；缺势或选区写null。选区使用`kind=index_boxes`、三维半开整数边界`lower/upper`的`boxes`并集，附`reason/source`，不自动选远场或平台。

完整输入计算区域内defect-minus-host电子势能差及分布统计。可得的`candidate_host_vbm_on_defect_gauge_eV`只是同区域参考移位候选；`potential_alignment_eV`在形成能接口中是能量项，不能把原始势差直接填进去。本入口不生成qΔV、FNV或带电形成能。`deliver-properties --study STUDY.json --potential-alignment RESULT.json --output DELIVERY.json`绑定defect Study并原样交付保存诊断，不重新计算。全部数值运算仍在站点Slurm；软件数学样例不建立原生或材料资格。

0.21新增化学参考来源接线。`mlcc chemical-references --request REQUEST.json --output REFERENCES.json`消费已保存、来源绑定的中性固定胞ABACUS总能记录，按显式参考角色/相/化学式核对整胞组成与每式量分母，不重解析能级或计算DFT。请求schema为`mlcc.chemical-reference-request.v1`，包含`reference_set_id`、`elements`、`host_reference_id`、`elemental_reference_ids`（逐元素ID或null）、`competing_reference_ids`（未选择为null，明确无竞争相才为[]）、`selected_delta_mu`及`references`。每项reference明确`reference_id`、`role`（host/elemental/competing）、`phase_id`、`phase_selection_source`、`formula_stoichiometry`、`task_path`和`electronic_path`；相对路径以请求文件目录为基准。

`mlcc deliver-properties --study STUDY.json --chemical-references REFERENCES.json --output DELIVERY.json`接保存集合到Study，并在来源齐备时调用已有化学势域函数。逐源保留实际method_set和数值协议，参考组reference_method_id不替代共同物理字段/共同元素赝势比较。元素参考按eV/atom、相按eV/formula_unit；不会把整胞总能差当μ。缺元素/竞争相/μ点明确保留；不自动选富氧贫氧点。完整软件数学例只输出mathematical_chemical_point，native chemical_point仍为null。

`neutral-formation --chemical-reference-delivery DELIVERY.json`与原`--chemical-point`互斥，核对host任务后把交付的native chemical_point传给原中性形成能函数。没有真实点则形成能继续null，不把测试μ送入真实缺陷。上述归一化、域求解及数值消费均在计算站点Slurm运行；生产科学资格不由接口通过授予。

0.20新增ABACUS3.10.1静电势来源入口：`mlcc electrostatic-potential --task TASK_DIRECTORY --output POTENTIAL.json`（任务也可指向task.json）。方法配置顶层显式使用`"output_control": {"out_pot": 2}`；仅固定胞PW/NC SCF、非SOC共线nspin1/2，无外场/偶极/栅极/溶剂。输入未请求则原行为不变，误放控制项会报错。解析在站点Slurm执行，消费该任务自己的`OUT.<suffix>/ElecStaticPot.cube`、原生收敛和调度记录。

输出保留Ry的离子局域势加Hartree、Bohr网格/原子头、三完整网格步向量、z最快的原始标量和原atom_id映射；这是电子势能，不是正电荷电势。Hartree G=0为零，离子局域势零点保留，未减EF/均值/真空值。不包含XC或非局域赝势。纯cube不证明原生/GPU执行；来源绑定成功也不授予科学资格。单宿主势不产生跨任务共同能标，对齐、FNV/eFNV及带电形成能保持null。实际安装与原生验收状态以workspace发布记录为准。

0.17新增分支审阅、完整Born列汇总、P7→Γ Hessian和固定胞介电贡献消费。现有原生Berry输出可以传递未定分支/缺列状态；完整输入的矩阵计算与材料科学资格分开。Γ当前验收范围为software_math_only；原生P7接入仍缺与Berry一致的方法来源字段，未开放材料结果。全部后处理仍在计算站点Slurm内执行；没有自动选择分支、补零、声学和修正或追加DFT。

```text
mlcc berry-branch-review --response RESPONSE.json --policy POLICY.json --out SUGGESTIONS.json
mlcc berry-branch-consume --response RESPONSE.json --review REVIEW.json --out CONSUMPTION.json
mlcc born-charges --model MODEL_DIRECTORY --responses RESPONSE.json [RESPONSE2.json ...] --output BORN.json
mlcc phonon-gamma --request GAMMA_REQUEST.json --output GAMMA.json
mlcc ionic-dielectric --born BORN.json [--gamma GAMMA.json] --thresholds THRESHOLDS.json --output IONIC.json
mlcc dielectric --born BORN.json [--electronic ELECTRONIC.json] [--ionic IONIC.json] --output DIELECTRIC.json
```

`berry-branch-review`只给相对整数建议；`berry-branch-consume`消费显式外部审阅并输出新请求可用的gdirs，不改原始数据/request。deferred/rejected保留null，approved需逐方向基准和绝缘路径证据引用，仍不自动授予科学资格。Born按明确Model的稳定atom_id与x/y/z位移列汇总，任何缺列使完整张量null。

`GAMMA_REQUEST.json`明确含`harmonic_result_path`、`plan_path`、`parent`、`method_identity`、`source_binding`、`geometry_tolerance_angstrom`、`mass_tolerance_amu`、`volume_tolerance_A3`和`dynamical_imag_tolerance`；消费已存在的P7完整力常数与同胞原子映射，不能把超胞数组直接改名成Γ Hessian。`THRESHOLDS.json`含`symmetry_eV_per_A2`、`translation_eV_per_A2`、`born_sum_e`、`minimum_optical_eigenvalue_eV_per_A2`。固定胞离子增量只需要完整同方法Born和固定E=0、无NAC的Γ Hessian；只投影三个平移方向，负/近零光学模使响应未定，不裁剪。电子张量必须是同胞同方法的相对epsilon_infinity（已包含真空I）；总静态值只将电子项与离子增量相加。缺电子时可保留离子项、总量null；当前ABACUS3.10.1没有经本站证据确认的电子介电producer，不能用slab场或隐式溶剂代替。

0.13新增缺化学势的中性原始能量交付，以及MD请求中的可选`rdf={species_pair, r_edges_angstrom}`。RDF沿用显式观测窗口，输出`md-rdf.json`；缺窗口不计算，合法截断以内的计数不代表完整近邻配位数。

0.12 新增单Study MD工程结果交付：`python -m mlcc deliver-md --study study.json --task TASK_DIRECTORY --request delivery-request.json --window-request windows.json --output-directory NEW_DIRECTORY`。后处理在计算站点Slurm内执行，原生计算可复用已完成任务；不会重提MD。`--window-request`可省略，缺窗口会输出unresolved而非自动选全记录；`--targets`用于有明确Study设计要求时的独立比较。

`delivery-request.json`含`source={model_id, model_version, potential_id, potential_version, elements}`以及`window="production_window"`、`"equilibration_window"`或显式`"whole_record"`。thermo必须选择全体系元素。输出目录必须为新目录，包含collection、conditions、source-selection、thermo（范围明确时）、delivery JSON和report.md。现有workflow核对原生完成态与显式依赖，property_delivery消费全体系温度样本均值、总能首末差，并保存原始数据和单位。缺replica/统计证据不阻塞工程交付，不授予材料、平衡或生产资格；模型DFT来源不等于势由本项目DFT训练。

这是按本地 MatterAI 跨仓库契约创建的独立 matterai.bundle.v2 源码目录。0.9.0 提供晶体导入、精确扩胞/显式缺陷与原子谱系、ABACUS PW 方法资格、电子/DOS、张量弹性标定和拟合门、缺陷热力学、性质交付/设计适配、Phonopy 位移/任务/原生力入口、LAMMPS 输入/原生解析、Slurm runner 与 MCP。Ni DFT 工程链、CaZrO₃ 单次 SCF 和 Ni LAMMPS run 0 已有真实数值证据；完整弹性/缺陷/声子原生数据集、生产精度和 MD 实际采样仍待分别验收。真实状态以 workspace 的 task/result 和阶段证据为准。

## 内容与接入

- agents/mlcc/AGENT.md：领域角色、四项 Skill 和科学边界。
- skills/：建模、VASP→ABACUS、四性质、LAMMPS 四个职责单元。
- harness/cases/：行为/真实集成案例定义。schemaVersion 使用平台声明的 matterai.case.v2；其余字段是本项目约定，当前未实现案例执行器。
- bundle.json：精确版本、权威 skills 列表与 MLCC MCP 声明，risk=networked。
- src/mlcc/：当前领域函数与薄调度适配器；tools/mlcc_mcp.py 为便携启动器。
- pyproject.toml：已测试 Python 科学库/MCP 版本；站点环境在用户 workspace。

用 MatterAI 的 bundle:install 安装到独立用户 workspace，再通过平台选择 mlcc Agent。平台安装成功不意味着任何计算工具已启动；新增可执行工具后需显式接入和发布新版本，不能只补 manifest 名称。

## 计算顺序

0.4.1 增加 Study 条件读取、只读续接判断、显式结果依赖门、ABACUS 结果交付和同几何截断对照。它们是实际 Python/CLI 函数，七个 MCP 工具仍负责执行生命周期；`mlcc_list_tasks` 另外返回 `next_action`。续接建议不自动提交，未知提交须核对原始作业。

```text
mlcc study-plan --study <明确的study.json>
mlcc resume-plan --task <task.json> --site <site.json>
mlcc deliver-result --task <task.json> --study <study.json> --conditions <conditions.json>
```

三条命令只读并向标准输出返回 JSON。新任务可以声明 `required_results`，每项包含父 `task_id`、相对父任务目录的 `result_file` 和要求的 `scientific_status`。统一 runner 在提交前读取父作业终态、结果归属、科学状态与原产物；CLI 与 MCP 使用同一个依赖门。Study 指定的温度是工况，不是电子展宽，静态参考也不代表该温度平衡态。`deliver-result` 当前支持 ABACUS 解析格式，保留工程/未获资格范围，不生成产品达标结论。

工程接线先 VASP；迁移任务使用同几何 ABACUS 单点/独立弛豫，验证相关物理量后固定 ABACUS 为生产 DFT。四性质与 MD 所需后续标注均使用 ABACUS，不自动回退 VASP，不混用两引擎原始标签。

pymatgen＋ASE 是微观建模内核。LAMMPS 从明确的 ABACUS 弛豫父模型扩胞，先取得合格势，再做体相/纳米局部微结构/界面，不承担通用有限元、铁电/断裂相场或真实器件电磁。

## 工程约束

禁止防御性编程、哈希校验、自动重试、自动换引擎、假数据/补零与内容缓存；直接领域函数和当前格式适配器。模型/任务使用可读 ID、普通版本与路径。单位、物理收敛、计量和科学基准对照仍然必要。

可移植能力包不包含 IP、SSH 密钥、站点可执行路径、VASP/POTCAR 或用户结果。站点由用户 workspace 配置，使用已有 LAN SSH 别名，不默默切换网络/队列。当前未复制上游实现代码，也未声明其再分发许可。

数值计算、科学后处理与数值验收在配置指定的计算服务器通过 Slurm 执行。客户端负责编辑、传输/任务控制和查看产物；能力包安装与 MCP 握手不等于在客户端执行科学计算。

harness 验收分为方法行为、确定性数值测试和真实计算集成。案例的 execution_status 只在对应事实通过时更新；当前不具备统一 MatterAI 案例执行器。

## 0.5.0 显式 ABACUS 任务入口

```text
mlcc create-abacus --study <study.json> --model <model目录> --method <method.json> --site <site.json> --request <request.json>
mlcc parse-abacus --task <task.json> --site <site.json>
```

创建只写输入，随后通过已有七个 MCP/CLI 生命周期动作执行 Slurm 任务。解析要求已保存原生 COMPLETED/0:0，另行判断电子与离子收敛。方法显式指定泛函、自旋、逐元素初始磁矩、占据、展宽、截断、电子阈值、三方向 kpoints、设备/求解器与赝势标识；站点提供程序/MPI/赝势路径。没有 Ni 科学默认值。固定占据及多元素输入经单测，尚无本批真实数值资格。

结果交付核对 task_id、Study、原生科学日志及计算条件；不能把静态参考重标为有限温度 MD 或已施加目标外压。应变生成/比较是直接领域函数；只有同方法的真实完整三点证据才能验收，函数单测不代替应力标定或 Cij。

## 0.6.1 本地模型导入

```text
mlcc import-model --request <import-request.json> --output <新模型目录>
```

请求显式指定 `source_path`、`source_format`（cif/poscar/extxyz）、`source_reference`、`material`、`phase_requested`、`model_id` 和 `version`。相对源路径按请求文件目录解析；多结构文件必须指定从零计数的 `source_index`。只接受三维周期、满占位的显式晶体，已有整数原子 ID 保留，缺少 ID 时按展开源结构顺序分配。新目录保留原始输入、源与工作结构、模型合同和逐原子来源映射；不会覆盖已有模型版本。

不自动选择晶相或标准化重排。显式 `basis_transform` 要给出整数 unimodular 分数坐标矩阵、平移、目标晶胞和来源说明；实现检查周期晶格等价及右手笛卡尔旋转。含三维磁矩或动量矢量的非恒等旋转当前明确拒绝。身份导入保留其原方向数据。导入只建立未弛豫结构，不代表目标温度平衡态、掺杂生成能力或生产资格。

科学任务创建时，Study 的材料、晶相和模型 ID/版本须匹配所选模型；解析使用任务中保存的模型路径。七个 MCP 生命周期工具保持不变，模型导入使用 Python/CLI 入口。

## 0.7.0 方法输入与公共电子/弹性切片

```text
mlcc inspect-upf --method <method.json> --site <site.json> --output <新header-snapshot.json>
mlcc qualify-method --model <模型目录> --method <method.json> --site <site.json> --output <新qualification.json>
mlcc electronic --task <已完成SCF任务目录> --output <新electronic.json>
mlcc electronic-dos --task <已完成SCF任务目录> --emin <eV> --emax <eV> --points <网格数> --sigma <eV> --output <新dos.json>
mlcc elastic-plan --model <模型目录> --amplitudes 0.005 --output <新plan.json>
mlcc elastic-analyze --reference-task <任务目录> --strained-tasks <任务目录...> --calibration <标定.json> --thresholds <阈值.json> --output <新analysis.json>
```

`inspect-upf`通过显式站点读取已选择UPF原生头；建模、资格计算、科学后处理与数值验收均在v100经Slurm执行，本地只编辑、传输控制和查看证据。资格检查重读原生头快照，检查元素、PBE/NC、价电子、相对论处理、自旋/非SOC、占据/能带容量、网格和执行方法。科学案例的任务创建必须通过此门。0.9.0冻结启用版本只支持中性、共线非SOC的PW/PBE/NC方法。0.10.0候选增加受限带电SCF输入合同：仅固定胞、PW、非SOC、`nspin=1`、fixed occupation、正偶数目标电子数；job71的输入检查通过，电子模块修正后由job72通过20项检查，另有7项中性消费者和1项工作流检查，不等于带电科学或生产资格。`nspin=2`固定占据、SOC/非共线仍未实现，真实带电SCF电子数已有原生验证，目标量加密资格独立记录。完全相对论UPF必须显式声明ABACUS 3.10.1的j通道平均，不能把原文件改标为scalar。输入通过不等于赝势或生产精度通过。

电子入口保留 k 权重、原生/归一化占据、能级、费米能级及来源，并核对原生日志的总电子数。固定整数占据只输出当前均匀网格的 KS gap，有限展宽不输出带隙。Gaussian DOS 使用调用者给定的 eV 网格与标准差，含所有已解析能级，报告 states/eV/cell 和有限窗口积分误差；不是 PDOS、路径能带、实际温度谱或精度合格结论。当前支持原生完整 Gamma 零偏移网格，不支持不可约网格。

弹性规划采用工程 Voigt 顺序 xx/yy/zz/yz/xz/xy，剪切张量分量为 gamma/2，保持分数坐标与 atom_id。每个幅值产生六方向正负扰动，另有参考态；规划不提交任务。请求可通过 `create-abacus` 的 `input_transformation.kind=voigt_strain` 生成固定胞 SCF 原生输入。0.7.0 仅有分析门；0.8.0 增加以下张量标定协议，旧三点数据的 Cij 仍为 null。

所有新报告拒绝覆盖已有路径，历史任务/result 保持不变。七个 MCP 继续负责调度生命周期，新增领域功能通过上述 Python/CLI 调用，不另建调度服务。

## 0.8.0 模型派生、张量标定和交付

```text
mlcc derive-supercell --parent <目录> --request <JSON> --output <新目录>
mlcc derive-defect --parent <目录> --request <JSON> --output <新目录>
mlcc elastic-calibrate --reference-task <目录> --strained-tasks <24目录> --thresholds <JSON> --output <新JSON>
mlcc chemical-potential-region --request <JSON> --output <新JSON>
mlcc formation-energy --request <JSON> --output <新JSON>
mlcc binding-energy --request <JSON> --output <新JSON>
mlcc neutral-formation --host-task <目录> --defect-task <目录> [--chemical-point <JSON>] --descriptor <派生model.json> --output <新JSON>
mlcc deliver-properties --study <JSON> --tasks <目录...> [--targets <JSON>] --output <新JSON>
mlcc assess-design --request <JSON> --output <新JSON>
```

扩胞提供正行列式整数 `repeat_matrix`；缺陷提供显式 `charge_state` 和有序 vacancy/substitution/interstitial 操作。保存 parent atom ID/image、计量和电荷请求，拒绝隐式随机/补偿；新模型仍未弛豫。0.9.0 的中性 ABACUS 执行器仍拒绝带电模型；0.10.0 候选只允许上述受限固定胞 SCF 输入。真实带电 SCF 已有固定几何原生证据；缺陷形成能、VBM/费米参考、势对齐、介电屏蔽和 FNV/eFNV 修正仍待实现与科学验收。

张量标定取六方向 ±h/±2h 和共享参考态，比较能量差分与 `P=det(F)σF⁻ᵀ` 的功共轭分量。`elastic-analyze` 重新读取源任务并重算 v002 标定；需要两幅值成对斜率、秩、残余应力、线性与非对称性全部通过，才输出 clamped-ion Cij。阈值包括原六项以及 `calibration_abs_error_GPa`、`calibration_relative_error`、`calibration_signal_min_GPa`、`calibration_fd_consistency_GPa`、`amplitude_slope_difference_GPa`、`native_stress_asymmetry_GPa`。软件数学测试不能代替真实完整张量数据验收。

形成能按 `Edef-Ehost-ΣΔNiμi+q(EVBM+EF)+Ecorr` 分项。化学势区域、形成/结合能函数只做明确输入的数学后处理；不生成带电校正，不把原生 EF 当作缺陷 VBM 参考。原生中性适配器绑定真实同方法、同元素/赝势集合的固定胞 SCF 与派生模型。0.13可省略chemical point：只返回Ehost/Edefect、原始能量差、组成差和原生job来源，形成能与修正形成能均为null；空对象仍报缺μ。host50/defect121及后处理123已验证这条真实工程路径，材料、尺寸和化学势资格仍未完成。

设计比较仅匹配显式定义、单位、对象和条件，支持标称值/整误差区间、上下限/区间/目标容差。缺资格是 insufficient_evidence，没有产品规格是 not_assessed。`assess-design` 消费上游资格声明，本身不授予科学资格。当前电子交付重新读取 job40 等原生证据，精度未资格时不能给出 met。


## 0.9.0 声子软件入口

```text
mlcc phonon-plan --model <母模型目录> --request <显式位移请求.json> --output <新计划目录>
mlcc create-phonon --plan <displacement-manifest.json> --study <母study.json> --method <ABACUS方法.json> --site <site.json> --request <子模型/任务请求.json> --output <新子模型目录>
mlcc phonon-forces --plan <manifest> --tasks <全部reference及位移任务目录> --thresholds <预声明阈值.json> --output <新报告.json>
mlcc phonon-qpoints --plan <manifest> --tasks <全部任务目录> --thresholds <阈值.json> --qpoints <显式q点数组.json> --output <新报告.json>
```

`phonon-plan` 固定使用 Phonopy 4.8.3 的 Å/eV/amu Python 接口。请求必须有 `plan_id`、`version`、`phonopy_version`、整数 `repeat_matrix`、显式 `primitive_matrix`、`distance_angstrom`、`symprec`、`is_symmetry`、`hermitianize_dynamical_matrix`。MLCC 行晶胞满足 `supercell = repeat_matrix @ parent_cell`，传入 Phonopy 的 supercell matrix 为其转置；primitive matrix 按 Phonopy 列变换约定输入。总是生成明确的正负位移，保存原子谱系、质量和初始磁矩；不自动选择 primitive、相、幅度或温度。声子功能仍不支持带电/约束模型；带电 SCF 候选合同不向声子、弹性或 Berry 任务放行。

`create-phonon` 一次只创建一个指定 entry（`reference` 或 `disp-000001` 等）。请求显式包含 `displacement_id`、`child_model_id`、`child_model_version`、`child_study_id`、`task_id`、`resource_request`、`required_results`。母 study 必须选中计划的真实母模型，相/材料/掺杂/fixture 身份一致；新子 study 保留母案例工况，但实际任务是固定胞静态 SCF。调用既有 ABACUS 方法输入门，不自动调整 nbands、k 点或 SCF 精度。只写输入，提交仍经过既有 Slurm 生命周期。

力收集阈值必须声明 `force_match_tolerance_eV_per_A`、`reference_force_tolerance_eV_per_A`、`force_drift_tolerance_eV_per_A`、`geometry_tolerance_A`、`displacement_tolerance_A`。每个 entry 必须恰有一个真实完成任务，原生力、输入/输出几何、模型/Study/方法、赝势、k 点、Slurm 终态和电子收敛须一致。输出保留原始力，报告 reference 残力和总力漂移，不扣除它们；缺失或不一致返回 blocked，禁止拟合。

`phonon-qpoints` 重新读取原生任务并通过上述门后，使用 traditional finite difference 求力常数和显式 q 点频率。q 点是 primitive reciprocal fractional 坐标，结果保留 primitive 晶胞。无隐式 ASR、NAC 或虚频裁剪；是否 Hermitian 化由请求显式决定。Python 数学函数可用分析力验证算法，公共 CLI 不接受自行声称合格的力数组。软件通过不等于科学资格：当前没有真实完整位移力集/幅度和超胞收敛/NAC/高温非谐证据，不输出有资格的声子/热导或产品达标结论。

## 0.9.0 LAMMPS 工程入口

```text
mlcc create-lammps --study <study.json> --model <模型目录> --potential <势声明.json> --protocol <协议.json> --site <site.json> --request <任务请求.json>
mlcc parse-lammps --task <已完成任务的task.json>
mlcc md-collection --task <已完成MD任务目录> --output <collection.json>
mlcc md-conditions --collection <collection.json> [--window-request <md-window-request.json>] --output <conditions.json>
mlcc md-sources --request <md-source-request.json> --output <source-selection.json>
```

创建入口只写输入，随后使用同一 Slurm 生命周期传输、提交、查询与收集。当前限定显式 engineering fixture、三维周期 `units metal`/`atom_style atomic`、单 rank；势的文件、来源/许可、元素顺序、适用模型、pair style/coefficient 均由请求声明。导出保留原子 ID、类型/质量与三斜晶胞坐标映射。普通原子势不赋予铁电极化、陶瓷/金属交叉势或高分子拓扑能力。

`run0` 是静态势能/力评估，不进行弛豫或 MD。MD 输入仅提供显式 NVE/NVT 协议，调用者给出步数、时间步、温度、种子、输出频率和 NVT 阻尼；`dump_every` 必须整除 `steps`，保证轨迹记录末帧。Ni NVE 100 步已有真实原生工程链路，但采样资格仍为 false；短轨迹不能证明采样收敛、势适用域或热物性。解析读取实际 log/dump，压力 bar 转 GPa，保留势和输入来源。调度完成且工程解析通过时 workflow 可返回 completed，但工程结果不满足科学收敛依赖门，也不获得生产资格。Ni 的 EAM 能量不能与 ABACUS 裸总能混算。

`md-collection` 只读取已完成的固定格式 `metal`/`atomic` MD 任务，调用 `read_md_collection` 保留完整 native thermo/trajectory 序列、单位、时间、原子映射、模型/势和 Slurm job 身份，并将 `image_flags`、速度、unwrap、采样窗口等缺失项写入 `missing_evidence`/`unresolved`。它不修改原任务、不提交作业、不计算 MSD/扩散或平衡资格；输出文件必须是新路径。

`md-conditions` 读取已接受的 `mlcc.md-collection.v1`，调用 `read_md_conditions` 生成新的 `mlcc.md-conditions.v1`。`--window-request` 可选，用于显式声明 `mlcc.md-window-request.v1` 的工程后处理窗口；省略时保留 collection 中的窗口状态，缺失窗口继续标记为 `unresolved_missing`。窗口选择不建立平衡或生产资格，输出中的 `production_qualification` 和 `sampling_equilibrium_qualified` 仍为 `false`；该入口不提交 MD、不计算统计量，也不改写 collection。

`md-sources` 读取 request 中的一个或多个已接受 collection，调用 `select_md_sources` 按明确的 model、potential 和元素身份绑定来源，生成新的 `mlcc.md-source-selection.v1`。来源映射保留 `sources[].mapping` 中的元素和原生原子索引，并独立呈现 `source_selection` 与 `replica_aggregation`；缺少 `replica_id` 时后者保持 `unresolved`，选择成功不代表 replica 聚合或生产资格。该入口不创建快照、不提交 MD、不计算统计量，也不混用 Prism 与 source Cartesian 坐标。

## 0.10.0 候选：Berry 电荷参考到 NSCF 极化

候选接口使用以下三个显式 CLI；命令只创建或解析任务，不替代 Slurm 生命周期：

```text
mlcc create-berry-reference --study <study.json> --model <模型目录> --method <method.json> --site <site.json> --request <SCF request.json>
mlcc create-berry-nscf --reference-task <已完成的SCF任务目录> --method <method.json> --site <site.json> --request <NSCF request.json>
mlcc parse-berry --task <已完成的NSCF task.json>
```

`create-berry-reference` 写入 P5 SCF 输入并显式启用 `out_chg=1`，原生电荷文件约定为 `OUT.<suffix>/SPIN1_CHG.cube`。`create-berry-nscf` 只接受真实完成且通过原生电子/绝缘性检查的 SCF 参考，绑定同一模型几何、原子顺序、赝势、方法和 k 网格；它把参考电荷独立复制到 NSCF 任务根目录，写入 `init_chg=file`、`read_file_dir=./`、`berry_phase=1`、显式 `gdir` 和 `pw_diag_thr`。两条创建命令都不会提交作业。

候选 Berry 路线严格限定为 ABACUS 3.10.1 PW、`nspin=1`、fixed occupations、非 SOC、共线和 `symmetry=-1`；Berry 路径的 `nspin=2` 明确拒绝，普通 SCF/relax 的自旋能力不因此改变。`parse-berry` 重新核对 NSCF 与 SCF 的原生 Slurm 状态、方法/模型谱系、电荷来源和 `POLARIZATION CALCULATION` 输出。当前只接一个方向；结果保持 `branch_status=not_unwrapped`、`branch_unwrapped=false`、科学/数值/生产资格均为 false，不能声明连续分支、自发极化或介电性质。

0.10.0 的安装、启用及分项验收状态以项目 workspace 中的发布记录为准。CPU小规模兼容任务job58的真实输出经job65完成解析/入口验收，修复了周期坐标等价性与不同单位打印舍入问题；不再重算CPU Berry。GPU job53失败，job61取得FFT访问边界的真实SIGSEGV栈但未修复；GPU Berry入口保持拒绝，普通支持GPU的计算继续优先GPU。Born、DFPT、体相有限场、电子/离子/静态介电和分支解缠尚未实现。所有站点路径、赝势路径、材料、晶相和请求参数必须由调用方配置。

## 缺陷电子参考交付（0.19）

```text
mlcc deliver-properties --study <缺陷Study.json> --defect-references <参考请求.json> [--targets <目标.json>] --output <新JSON>
```

与 `--tasks`、`--p5` 互斥。请求schema为 `mlcc.defect-reference-delivery-request.v1`，显式提供 `host_electronic_path`、`defect_electronic_path` 和 `descriptor_path`（缺陷模型的model.json）；相对路径以请求文件目录为基准。消费既有 `mlcc.abacus-electronic.v001`，不重新运行能级解析器。Study绑定缺陷任务，宿主绑定缺陷描述符的父模型；保留双方的原生job、方法、数值协议、能级单位、模型和原子谱系。

采样网格VBM/CBM和SCF费米能保留各自原生能标，不据此对齐两个任务；带电缺陷最高占据级不是对齐后的宿主VBM。当前没有势源与修正，aligned VBM、势对齐、FNV/eFNV和带电形成能为null，材料资格false。总能量及电荷密度不能当静电势。该公共入口只做站点Slurm内的保存结果消费，缺失科学参考不阻塞正确的软件传递；启用版本由workspace发布记录决定。

## P5 Study结果交付（0.18已验收）

```text
mlcc deliver-properties --study <Study.json> --p5 <P5产物请求.json> [--targets <目标.json>] --output <新JSON>
```

`--p5`与原`--tasks`互斥，沿用已有结果交付入口。请求schema为`mlcc.p5-property-delivery-request.v1`，显式`source_mode`为`native_source_bound`或`software_math_only`，必填`born`产物路径，可选`gamma`、`electronic`、`ionic`、`dielectric`路径。消费保存的0.17产物，绑定Study/父Model/原子顺序/单位/方法与原生任务来源，逐项交付张量或缺失原因；不再生成响应、力常数或调用引擎。

P7力与Berry响应的物理方法身份必须一致，各自SCF/NSCF数值控制、截断和k采样保留为原始协议及差异，未记载字段不补默认。协议一致也不授予精度资格。真实输入缺失与独立数学张量示例分开记录，工程链通过不表示材料已满足设计要求。全部数值消费在站点Slurm中执行。

## 0.14.0 单方向 Berry 极化交付

```text
mlcc deliver-polarization --study <study.json> --task <已完成Berry NSCF任务目录> [--targets <targets.json>] --output <新JSON>
mlcc polarization-path --request <显式固定胞单方向路径JSON> --output <新JSON>
```

`read_berry_task` 复用 `parse-berry` 的 ABACUS 3.10.1 原生验证，但只读任务、方法、参考 SCF、电荷密度和 Berry 日志；`parse-berry` 仍负责保存 `result.json` 与任务事件。交付入口严格绑定 Study、case、模型、fixture、方法和参考 SCF，保留 NSCF/参考 SCF 的原生 Slurm job、来源文件、方向和极化量子。当前首切片只交付一个 `gdir` 的标量 Berry 极化代表值，保持 `branch_status=not_unwrapped` 和未资格状态；没有完整三维极化、自发极化、Born 有效电荷或介电张量。无目标为 `not_assessed`，有目标但原生科学证据未资格为 `insufficient_evidence`。电荷密度不复制到交付包。

`polarization-path` 消费保存的原生Berry结果及其任务/参考/模型/方法来源，逐点使用调用者声明的整数分支和依据，不自动选支。请求schema为`mlcc.polarization-path-request.v1`，包含path_id、study_id、gdir、path_basis及顺序points；每点包含point_id、path_coordinate、parent_point_id、task_file、result_file、branch_integer、branch_basis。路径限固定胞、同物理方法/组成/原子映射、单方向。只有一个真实点、缺显式分支或没有结构变化时，极化差保持null并输出原因；显式分支代数结果也不自动获得连续路径科学资格。历史单点58不能复制为真实两点，缺Born/介电响应不填零。

## 0.15.0 候选：陶瓷专用势与P5响应入口

陶瓷入口需显式安装本项目独立包`mlcc-deepmd-bridge==0.1.0`。下列计算、输入生成和后处理命令在v100 Slurm中执行；创建与提交分开，提交仍沿用原SiteRunner。

```text
mlcc ceramic-data --request <陶瓷来源JSON> --output <新集合目录>
mlcc ceramic-training-bind --collection <collection.json> --output <新dataset-manifest.json>
mlcc create-ceramic-training --request <工作区/任务ID/collection/input/训练配置/接口证据JSON>
mlcc finalize-ceramic-training --task <task.json> --scheduler-record <真实Slurm查询JSON>
mlcc create-ceramic-lammps --request <工作区/任务ID/collection/system_id/model_card/protocol/site/resource_request JSON>
mlcc parse-ceramic-lammps --task <task.json>
mlcc create-berry-response --study <JSON> --model <目录> --method <JSON> --site <JSON> --request <显式位移JSON> --output <新目录>
mlcc create-berry-response-nscf --manifest <response-manifest.json> --point-id <ID> --method <JSON> --site <JSON> --request <NSCF请求JSON>
mlcc berry-response --request <显式两点/方向/分支JSON> --output <新JSON>
```

陶瓷集合保留不同原子数和父子谱系，普通中性E/F/virial势不获得极化/外场/介电资格。工程MD保存真实源模型身份，不通过改fixture绕开资格。缺平衡/生产窗口保持unresolved。P5响应按manifest绑定子模型与原生SCF/NSCF，缺分支或方向时不输出完整张量；算法检查不等于真实响应验收。当前安装状态以workspace发布记录为准。

## 0.10.0 候选：中性缺陷任务对与材料势对照

```text
mlcc create-neutral-defect-pair --host-model <目录> --defect-model <目录> --host-study <JSON> --defect-study <JSON> --method <JSON> --site <JSON> --host-request <JSON> --defect-request <JSON> --chemical-reference <JSON> --output <新JSON>
mlcc compare-potential --request <显式配对请求JSON> --output <新JSON>
```

中性任务对只创建显式同胞、同方法的两个SCF输入。缺陷必须已有派生谱系，两个Study各自绑定模型；该成对创建入口的化学势文件含有限μ、来源及相同引擎/方法/占据能量定义。接口不选择位点、不提交计算、不输出形成能。job64只证明输入检查；0.13后处理入口另已绑定真实host50/defect121。未提供化学势的能量来源链不能称为完整形成能链。

势对照请求含 `pairs`（每项 `pair_id/abacus_task/lammps_task`）、`reference_pair_id`、显式 `tolerances`（`energy_eV_per_atom/force_component_eV_per_A/stress_component_GPa/geometry_A`），以及可选 `abacus_stress_mapping`。各引擎分别减去对应参考能后比较同组成相对能，力/应力只在来源和几何有效时比较。完整静态压力张量需要原生六分量；历史标量不能补零。当前应力标定与材料势适用域仍缺，结果保持未资格，命令正常写出报告不代表势合格。所有数值输入生成及后处理均在v100 Slurm执行。

真实材料的候选势静态任务沿用 `create-lammps`，protocol 显式增加 `purpose="potential_qualification"`、非空 `experiment_scope`，并固定 `kind="run0"`、`static_tensor=true`。保持真实模型/势的fixture身份及来源/版本，不放行普通MD。原生解析成功只返回 `evaluated_candidate_potential`；续接可记录执行完成，但不满足科学依赖。候选用途的软件门已检查，真实完整张量配对实验尚缺。

## 0.10.0 候选：带电固定几何 SCF

已有 `create-abacus` 接受显式整数 `net_charge=q`，模型电荷与方法必须一致。首切片限 PW、非 SOC、nspin=1、fixed 占据和正偶数目标电子数，写入 `nelec=0`、`nelec_delta=-q`；不自动增加带数、选择自旋或启用 gate。带电弛豫、Berry、弹性、声子和普通原子势参考继续拒绝。

`parse-abacus` 与 `electronic` 将 UPF 中性价电子数、请求目标、原生日志调整值和全 k 点占据积分相互核对。ABACUS 3.10.1 原生日志的额外等号、完整 Gamma 网格坐标与权重的打印舍入均按实际文件解析：只有打印区间证明完整均匀网格时才使用精确 1/N 权重，保留原始打印值，不无条件归一化。真实 CZO 氧空位 q=+2 的 GPU SCF 已提供该路径的原生证据；数值加密和材料资格分别记录。

结果为 `raw_charged_scf_unqualified`，保持材料科学/生产资格 false；仅原生电子收敛不代表目标量或形成能收敛。局域势、VBM、化学势、介电屏蔽、FNV/eFNV 与尺寸/弛豫收敛尚缺，因此不能将这些原始总能直接交付为带电缺陷形成能。实际 DFT 显式请求 Slurm time=0；有限运行时间仅用于软件检查和后处理。

## 0.11.0 候选：MACE 单 GPU 静态任务创建

MACE用作公开候选势和对照工具；专用势主线为ABACUS→DeePMD-kit→LAMMPS，后者须部署匹配的DeePMD C++ runtime及LAMMPS内置或插件接口，并验收同模型E/F/virial一致性。

`create-lammps`接受显式`pair_style="mace no_domain_decomposition"`的静态资格任务，沿用`purpose="potential_qualification"`、`kind="run0"`、`static_tensor=true`及未资格状态。输入包含Kokkos half邻居、atom map、关闭原子排序和newton on；`pair_coeff`必须绑定已声明势文件及LAMMPS原子类型顺序。此入口不开放MACE生产MD。

站点配置显式给出选定二进制、环境脚本及`lammps.launch_arguments=["-k","on","g","1","-sf","kk"]`。资源为1节点、1 rank、1 GPU，用`gres`、`gpus`或`gpus_per_task`其中一个字段声明；不隐式选择引擎或退回CPU。旧站点省略`launch_arguments`时仍为空列表。创建及`prepare`均不提交任务，所有建模和数值检查在计算服务器Slurm内执行。

现有独立引擎已有同模型接口证据；创建器软件检查与原生执行、材料势资格分别记录。未执行任务保持`not_calculated`，不得复制旧输出或伪造成功调度状态。本站当前发布状态及证据由workspace发布记录决定，源码版本不等于已启用版本。
# 0.30 原生响应消费补充

`mlcc electronic-dielectric --request <request.json> --output <electronic.json>` 读取来源绑定的ABACUS LCAO/PYATB direct-static电子介电结果。请求schema为`mlcc.pyatb-static-electronic-request.v1`，字段包含`scf_task_path`、`postprocess_task_path`、HR/SR/rR各自绝对`path`及单位Ry/dimensionless/Bohr、明确`minimum_gap_eV`。SCF和后处理需保存真实Slurm终态、已收敛原生证据及实际PYATB版本；不启动DFT或PYATB。

`mlcc deliver-properties --study <study.json> --p5 <request.json> --output <delivery.json>` 沿用`mlcc.p5-property-delivery-request.v1`。`source_mode=native_source_bound`，`born`、`gamma`、`electronic`为保存产品路径。新增接受`mlcc.native-born-branch-family.v1`与`mlcc.czo-native-raw-gamma-force.v001`的来源合同；电子可用已保存`mlcc.pyatb-static-electronic.v1`。请求仍使用现有字段，不引入另一执行器。

Born保存完整整数分支族，独立位点列表和全模型原子顺序分别绑定；原始极化沿晶格方向、展开系数沿Cartesian。系数不等于已选物理Born。Γ保存原始力常数/Hessian和未对称化诊断。缺物理分支或Γ响应条件未满足时，同Study结果仍保存真实来源及原因，物理Born、离子介电或完整静态介电保持null。工程交付不授予材料/生产资格。实际CZO来源与验收留在项目workspace，不打入Bundle；通用LCAO输入创建与其他材料科学资格按各自任务另行验收。

