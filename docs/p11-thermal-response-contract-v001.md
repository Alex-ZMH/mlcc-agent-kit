# P11 界面热响应最小切片合同

2026-10-25，原实施窗口负责输入/热模块/公共入口，主线负责版本与集成。本切片不新跑材料MD、DFT或训练，不重复439/442/443。生成显式热数据生产输入，完成必要领域消费函数；真实实例缺数据保留unresolved。

## 可复用来源和必要新增

- MLCC `md_thermo._observation_rows`：显式whole_record/step_range、原生端点和行选择；直接复用，不重新选择稳态窗口。
- MLCC `lammps_tasks.read_lammps_task`、`interface_sources.read_interface_task_sources`：真实Slurm终态、势/单位/映射及双父源绑定；MLCC `md_conditions`/`md_sources`的时间与来源合同继续保留，不重造collection框架。
- Photoresist `arf_md_conditions.normalize_settings/compile_settings`及`arf_backends_v2.validate_diffusion_protocol_evidence`提供显式条件/原生阶段/缺项报告的既有移植依据；其默认值不引入。ACS `VASP_MDAnalyzer._analyze_stability/_fit_linear_tail`没有界面热算法，扩散尾段和自动平衡选择不复用。
- 新增热量/空间温度表的薄读取器、输入命令和直接功率/温差函数。既有job45/105只有整体Temp/TotEng及坐标/力，没有热浴累计能量、速度或空间温度；不从它们推算热流。

## 原生生产输入

沿用create-lammps，kind=md、ensemble=nve、purpose=interface_thermal_response；新增显式thermal段。完整MD步长/步数/初始温度/seed/输出间隔仍由请求提供。热源/热汇分别列出源原子ID、目标温度K、阻尼ps及独立随机seed，不从材料/Study/温区推断。两组非空且不交叠，不要求覆盖整胞。

使用固定晶胞、all组NVE积分、两组langevin tally及原始累计能量采样，空间温度使用沿已保存+z法向的chunk/atom和ave/chunk。每次空间输出只取一个原生样本，不隐藏时间平均；保存step、bin ID、中心Å、Ncount和温度K。温度为每原子3个平动自由度的分箱动能温度，不自动移除流动速度或猜约束修正。能量输出保存原始f_hot/f_cold eV；符号按实际对应LAMMPS实现核对，原始值保留。单位限metal，位置Å、时间ps、面积Å²。既有GPU MACE输入配置复用，创建不提交。

符号先查官方[stable_22Jul2025_update4 fix_langevin.cpp](https://github.com/lammps/lammps/blob/stable_22Jul2025_update4/src/fix_langevin.cpp)，再读本站已部署10 Sep 2025源码的`src/KOKKOS/fix_langevin_kokkos.cpp`：两者end_of_step累加热浴力做功，compute_scalar返回负值。因此保存字段命名hot_reservoir_eV/cold_reservoir_eV，源输入=-Δf_hot，汇抽取=+Δf_cold。本站源码也确认空间表的帧首行含Timestep、Number-of-chunks、Total-count三个字段，原文见`workspace/reports/interface-thermal-v001/native-source-observation.txt`。命令格式参见[fix langevin](https://docs.lammps.org/fix_langevin.html)、[fix ave/chunk](https://docs.lammps.org/fix_ave_chunk.html)；源码核对不写成本站热任务执行验收。

现有data导出使用`force_skew=True`，原生箱为triclinic；按[compute chunk/atom](https://docs.lammps.org/compute_chunk_atom.html)的限定，空间分箱采用`units reduced`。显式Å箱宽除以atom-map所存固定胞z长度生成reduced箱宽；读取Coord1时保留原始coordinate_reduced，并乘同一z长度得到coordinate_angstrom。模型限a/b位于xy平面、c沿+z且无xz/yz倾斜，原点为既有导出的0，不新增通用旋转或坐标推断。

## 消费与双周期界面

显式analysis request：observation_window，area_angstrom2，normal_cartesian，interface_count=2，以及AB/BA各自的upstream_bin_ids/downstream_bin_ids和direction_sign（相对+z为±1）。面积/法向与原模型核对。

能量在明确窗口首末样本之间计算ΔQ/Δt，报告源输入功率、汇抽取功率和两者不平衡，单位eV/ps及W；1eV/ps=1.602176634e-7W。源功率/面积另标为total_source_power_per_area，不叫某一界面热流。窗口内逐bin按相同输出时点算术均值，再对请求的各侧bin等权平均，给出声明空间片区的温差K；不假称外推到几何面上的Kapitza温跃。

两界面形成并行传热路径，不能仅因interface_count=2就除2。可选heat_allocation必须显式给出source说明、power_reference=hot_input及AB/BA分流比例（非负、和为1）；没有该声明时，保留总源/汇功率和空间温差，逐界面J/G/R为null并指出缺分流。若有声明，按J_i=f_i*P_hot/A、方向sign*n，G_i=J_i/ΔT_i、R_i=ΔT_i/J_i计算声明片区响应，并携带原分流假设，不标为从热浴能量独立测出的分流。不选比例或默认为1/2。ΔT或J为零时相应商为null，保留原值和原因。

缺窗口、热量序列、空间温度、有效bin或分流声明时只将依赖它们的量标unresolved，仍交付已有原始样本和已算量。空bin的原生零温度不作为温度样本。没有自动稳态判定、外推拟合、块统计、热导率或电子热通道推断。

公共interface-thermal读取任务和analysis request；deliver-properties --interface-thermal接同Study。对尚未运行的已有Ni/BTO任务输出真实缺项，对明确标注数学夹具验收单位、符号、窗口、分流和温差公式。真实原生热输出兼容性待数据，本轮不把数学检查写成已完成材料热响应。
