---
name: run-mlcc-md
description: 显式选择已有势或 ABACUS→DeePMD 自训练势，复用陶瓷训练集合和模型卡创建 LAMMPS 工程任务，并保留采样与材料资格边界。
---

# 同源扩胞与局部界面 MD

公网调用先走[统一操作入口](../references/public-operations.md)；统一入口只调用已有 MD CLI/模块 ops 创建控制任务，所有势、协议、站点和科学资格继续由本 Skill 的显式请求决定。

氧空位路径沿 `create-lammps-neb --study --model --final-model --potential --protocol --site --request` 创建既有 TaskRecord，`parse-lammps-neb --task` 保存原生 NEB 图像、端点及 regular/climbing 停止记录；创建不自动提交，数值任务仍经既有 Slurm runner。`vacancy-migration --request --output` 消费显式 `mlcc.vacancy-migration-request.v1`：固定母体/空位模型、母位点与移动原子 ID、父映射、观察范围、capture radius、ambiguity gap 和连续确认帧数均来自请求。`source.kind=md_native` 读取已保存原始轨迹、Prism 映射和时间条件；`source.kind=neb_result` 读取已保存的 `mlcc.lammps-neb-result.v1`，按图像/反应坐标保留，不能作为 MD 时间轨迹。局部最近位点周期像不补 native image flags 或 unwrap；歧义、多占据和未确认换位照实记录，不拟合迁移速率或扩散系数。`deliver-properties --study --vacancy-migration --output` 将完整保存产品接回同一 Study，不重读原始帧、不重算事件。指定路径意图和最小化后的实际占据分别保留；不根据意图宣称发生跳跃。参数与本次最小实际链见 `docs/vacancy-migration-v001.md`。

固定胞切向路径使用`create-lammps`的`kind=interface_tangential`、`purpose=interface_tangential_response`和`tangential_response.schema=mlcc.interface-tangential-protocol.v1`。当前仅`fixed_cell_clamped_internal_relaxation`，显式单位法向`normal_cartesian`绑定原界面几何，显式单位切向`tangential_cartesian`须与法向正交；不自动选向或归一化。q沿切向增量移动受控夹持，fixed/moving/free分组和minimization沿已有显式合同；夹持setforce最小化后unfix，再同几何run0保存原始力。切向输出为`dump.tangential-*`，创建不提交，验收仍经v100 Slurm。`interface-tangential --task <task.json> --output <product.json>`及`deliver-properties --interface-tangential`接同Study，保留原生停止原因、实际调度状态和未决。位移方向不替代界面法向，双周期胞净反力只除一次面积；坐标返回只报告坐标闭合。本切向新路径尚未运行验收。

固定胞法向位移控制沿用`create-lammps`的`kind=interface_normal`和`purpose=interface_normal_response`。显式`normal_response.kinematics=fixed_cell_clamped_internal_relaxation`时，`fixed_atom_ids`为A侧静止夹持，`moving_atom_ids`为B侧位移夹持，`free_atom_ids`为允许内部弛豫的其余原子；三组互斥并覆盖模型。`minimization`必须声明`min_style`（当前cg/sd）、`etol`、`ftol_eV_per_A`、`maxiter`和`maxeval`。逐点只移动受控夹持，夹持最小化后解除setforce并在原几何run 0保存完整原始力；不以被清零的夹持力求反力。原生停止原因、迭代/评价次数和自由原子力随`interface-normal`及同Study交付保留；调度成功与弛豫收敛分开。参数和势由请求给出；执行结果与原生停止原因随保存产物保留。

P11显式局部virial输入沿用`create-lammps`，`kind=run0`、`purpose=interface_local_stress`、`static_tensor=true`及`local_stress={schema: mlcc.local-stress-protocol.v1, contribution: virial}`，输出原始逐原子bar Å³六分量。此切片无MD积分、动能项或局部温度；实际执行经Slurm。本站MACE/KOKKOS不支持per-atom virial，保留原生错误，不换势或分摊全胞压力。完整字段见`docs/p11-local-stress-contract-v001.md`。

已有DeePMD独立路线支持`purpose=potential_qualification`和显式`local_stress.compute_style=centroid/stress/atom`，分量顺序必须为`[xx,yy,zz,xy,xz,yz,yx,zx,zy]`。保留完整非对称张量，不压六分量。`local-stress`沿既有入口解析，`deliver-properties --local-stress`消费保存产品；bulk任务保留真实Study/model/potential/method/native job，interface来源为null，不影响界面任务的必需来源。此接线复用已保存结果，不重复原生执行。

界面热数据输入沿用 `create-lammps`，显式 `kind=md`、`ensemble=nve`、`purpose=interface_thermal_response`，由 `thermal` 声明热源/汇原子ID、温度、阻尼、seed、噪声零合力选择、采样间隔和空间分箱。生成 Langevin 累计热浴能量及单样本分箱温度输出；不代选参数、不自动提交。完整字段与符号见项目 `docs/p11-thermal-response-contract-v001.md`；已有普通NVE整体总能量不能当作热浴输入热量。

界面法向静态输入沿用 `create-lammps`，显式 `kind=interface_normal`、`purpose=interface_normal_response`，在 `normal_response` 中列出两侧完整原子ID组、单位法向、面积、两个周期界面数及逐点位移/加载分支。其中`fixed_cell_rigid_side_translation`分支固定胞、A固定、B刚性平移，无积分或最小化；写出每点原始力、能量及unwrapped坐标。创建不提交，实际执行仍沿用Slurm runner。完整协议见项目 `docs/p11-normal-response-contract-v001.md`。现成势明确传入，不改用途标签迁就验证器、不自动选势或启动加载矩阵。

`interface-normal --task <task.json> --output <product.json>` 消费完成的原生任务，导出广义法向反力/位移、区间割线刚度和规定坐标返回的闭合残差；未运行实例保留 unresolved/null。`deliver-properties --interface-normal <product.json> --study <Study.json> --output <delivery.json>` 交付保存产品。两个周期界面一开一合，反力只按面积归一化一次，不除2或标成每个界面的牵引；坐标返回不代表弛豫后的卸载恢复。

当前包已接入 LAMMPS 输入、原生解析与共用 Slurm runner；Ni NVE 100 步真实任务已完成 MD 工程链路。该任务的采样资格和势的科学适用域仍为 false，不能把工程完成当作采样或生产资格。LAMMPS 是原子/粒子模拟器，不将普通 MD 描述为 FEM、铁电相场或裂纹相场；本版不接连续求解器。

## 显式选择势路线

先沿用用户已选材料、相、掺杂/空位和势路线。已有适用势文件时走下文 `python -m mlcc create-lammps --potential ...`；用户选择 ABACUS→DeePMD 自训练势时走本节。没有可用 MACE 只表示该候选不可用，不触发自动换势、标注或训练。用户已明确选择后直接执行授权范围内的步骤，不再要求重复确认。

自训练入口为 `python -m mlcc.ceramic_potential_route --request <route-request.json>`，请求必须包含 `potential_route="abacus_deepmd"` 及以下一个 operation。其余字段与现有公共创建器保持一致，所有路径、资源、材料身份由项目配置提供。

| 情况与 operation | 必须显式提供的字段 | 实际调用与停止位置 |
| --- | --- | --- |
| 已有完成模型卡，`create_lammps` | workspace、task_id、collection、一个system_id、model_card、protocol、site、resource_request | 调用现有 `create_ceramic_lammps_task`；写原生输入和未提交TaskRecord |
| 已有ABACUS训练集合、明确要求训练，`create_training` | workspace、task_id、input_file、collection、interface_acceptance、account、training_config | 调用现有 `create_ceramic_training_task`；写训练脚本和未提交TaskRecord |

仅缺模型卡不能视为训练授权；保持输入缺口，不尝试查找任意势或自动调用另一operation。collection 必须来自显式 ABACUS 来源，已有集合直接复用。确有新增已授权标注时才使用 `python -m mlcc ceramic-data --request <JSON> --output <目录>`；必要的联合清单绑定沿用 `python -m mlcc ceramic-training-bind --collection <JSON> --output <JSON>`，创建器也会完成该绑定。不同组成保留各自system和原子ID，母体/缺陷同来源组不能伪装成独立验证集。

编制 `training_config` 时显式填写 `nproc_per_node=1/2/4`、CPU、内存、有限训练时限及固定 dp/torchrun 路径，并在创建结果中复核实际资源。底层配置类保留其已有默认值；本Skill编制请求时使用选定站点预算。训练参数从 input_file 读取，保留局部/全局batch。数据与模型规模适合时使用多GPU，已有模型不为增加卡数而重训。四卡的两帧工程吞吐证据不代表生产规模加速。

创建完成后检查 `potential_route.selection="explicit"`、真实模型/来源/元素映射、资源和 `scheduler_job_id=null`，再沿用既有 prepare/transfer/submit/query/collect 或对应七个MCP工具；创建器本身不提交。训练真正完成后读取原生scheduler记录，以 `python -m mlcc finalize-ceramic-training --task <task.json> --scheduler-record <JSON>` 登记模型卡；已完成模型卡直接进入单system的 `create_lammps` operation。LAMMPS真正完成后使用 `python -m mlcc parse-ceramic-lammps --task <task.json>` 接现有原生解析、MD collection和conditions。旧训练/MD job只作为来源，不写成新任务的scheduler_job_id。

首次使用时核对执行Python实际绑定的 mlcc 与 mlcc_deepmd 路径；源码依赖为 `mlcc-agent[ceramic]` 对应 `mlcc-deepmd-bridge==0.1.0`。候选源码测试可显式绑定两个源码根，发行版是否安装以当前环境的实际绑定证据为准；源码通过不等于发行版已安装。不得依据旧“未安装”文案自动安装或替换环境。只有训练/推理/原生LAMMPS阶段才需要匹配的DeePMD/PT/CUDA及插件运行时。输入生成与数值验收仍在选定站点Slurm中执行。

普通自训练E/F/virial势不支持极化、外场力或介电推断；已有陶瓷工程训练/短MD证据不授予目标温区、掺杂、晶界或生产科学资格。未资格势仅按现有创建器允许的显式工程run0/短NVE范围消费，不能借路线选择绕开科学使用门。

## 已有势与通用MD消费

`saved-domain-parameters --request <JSON> --output <JSON>` 将保存的 NEB 候选势垒、法向/切向曲线或区域应力直接转入领域 JSON。请求 `mlcc.saved-domain-parameters-request.v1` 明确给出 `kind`（`neb_barriers`、`interface_normal`、`interface_tangential` 或 `local_stress`）、`study_path`、`source_path`；区域应力另给 `region_id`。保存值、曲线位移与分支、单位、坐标、原子映射和原始状态照传，NEB 未收敛候选值继续保留，周期胞净响应保持原定义。该入口只读取产品 JSON，不解析原生输出或重算拟合；沿 `deliver-properties --domain-parameters` 接回对应 Study，实际消费经 Slurm。

同一入口的 `md_msd`、`md_replicas`、`vacancy_occupancy` 分别消费已保存 MSD、两 seed 摘要和迁移占据产品。MSD 曲线与滞后坐标以文件及 JSON pointer 引用，已有拟合值直接复制，D 的原 null 和原因保留；副本均值、标准差、标准误及置信区间均直接读取，未提供的 SE/CI 不补值。占据帧与几何事件引用保存记录，NEB 图像和反应坐标不作为物理时间，原 null 时间、端点未决及原生未收敛状态随条件保留，不产生跳跃速率。此出口不再调用拟合、统计或轨迹解析。

`bulk-thermal-transport --request <JSON> --output <JSON>` 消费 `mlcc.bulk-thermal-transport-request.v1` 的 `study_path`、`model_path`、`source_path`、`task_path`、`result_path`、`observation_window` 和 `transport`。从保存的 `mlcc.md-bulk-heat-source.v1` 读取热浴累计量与逐帧分箱温度，按实际时间拟合热源输入/冷端抽取功率，再按声明面积、方向和 `heat_fraction` 求热流；指定 bins 的窗口平均温度对空间坐标拟合梯度，按 `kappa=-J/gradT` 输出方向热导。`periodic_channel_count`、分流依据和排除热浴的 bin 选择须明示，不自动均分。空 bin、缺窗口和零梯度只令依赖量为 null，原负值、收支差和拟合残差照存；稳态保持 unresolved。六项领域参数通过 `deliver-properties --domain-parameters` 接回源模型对应的同一 Study，数值消费经 Slurm。

`lammps-elastic-response --request <JSON> --output <JSON>` 消费 `mlcc.lammps-elastic-response-request.v1` 中的 `study_path`、`model_path`、零应变 `reference` 和六方向正负应变 `samples`；每点明确给出 `task_path`、`result_path`、`strain_voigt`。从已保存原生应力复用现有弹性拟合，输出 GPa 单位的完整 `elastic_stiffness_tensor`（6×6）和 `reference_stress_tensor`（3×3），保留 Voigt 顺序、工程剪应变、源笛卡尔坐标、固定分数坐标条件及原始数值和调度状态。通过 `deliver-properties --domain-parameters` 接回母 Study，不重解析原生输出或追加应变扫描；数值消费经 Slurm。

`bulk-thermal-response --request <JSON> --output <JSON>` 消费 `mlcc.bulk-thermal-response-request.v1`：`study_path`、显式 `states[{state_id,source_path}]`、配对 `interval` 和闭区间 `observation_window`。读取保存的 `mlcc.md-bulk-thermal-source.v1`，输出密度、同 seed/同外压 NPT 定压比热区间，以及各向同性固定形状约束下的热应变张量和线/体热膨胀区间。焓使用平均 PE+KE 与声明外压乘平均体积，分母采用实际平均温差；瞬时压力仅作来源记录。零温差时仅温差相关量保持 null，保留其他可计算量、窗口、单位、原子映射和原始状态。领域 JSON 沿 `deliver-properties --domain-parameters` 接同一 Study；新增计算与验收经 Slurm。

`bulk-thermodynamics --request <JSON> --output <JSON>` 消费 `mlcc.bulk-thermodynamics-request.v1`：`study_path`、`states`（`state_id`、`md_delivery_path`、`volume_source_path`）以及按状态 ID 明确配对的 `cv_intervals`。现有 MD delivery 的 thermo 保存样本给出 PE、KE、实际温度均值和窗口，atom-map 的 `masses_by_type`、类型/原子映射及 `g/mol` 给出质量来源，保存的 whole_cell 体积请求给出体积。密度为质量/体积；同 seed、固定胞的比热区间为两态平均 PE+KE 之差除以实际平均温差和全胞质量。保留目标温度、实际温度、窗口和原始状态；不另推波动热容或跨 seed 统计。产物采用 `mlcc.domain-parameters.v1`，含 `mass_density` 和 `mass_specific_heat_cv_interval` 的数值、定义、单位、条件、标量坐标说明、原子映射、来源与状态。`deliver-properties --study <Study.json> --domain-parameters <product.json> --output <delivery.json>` 将保存参数原样接回同一 Study。计算和新增验收仍经所选站点 Slurm。

固定胞动态采样使用 `create-lammps` 的显式 `kind=md`、`purpose=md_native_sampling`、`ensemble=nvt` 和 `native_sampling` 协议。常规轨迹、严格五列原生展开坐标、逐原子九分量 virial 采样及含动能的总压力序列分别保存；不混用应力贡献。已有保存 collection 可由 `deliver-md --collection` 直接消费，窗口来自显式请求，MSD 与同温度独立副本沿已有入口处理。缺少 Fick 判据时保留曲线及拟合诊断，D 为 null。

`md-thermal-sources --request <JSON> --output-dir <新目录>` 消费 `mlcc.md-thermal-sources-request.v1` 中的 `task_path`、`sampling_path`、`collection_path`、`analysis` 和 `mechanical_constraint`。`sampling_path` 必须指向绑定原生任务的 `mlcc.md-native-stress-source.v1`；`analysis` 沿 `mlcc.local-stress-analysis.v1` 显式声明窗口、whole_cell 全体原子及实际固定胞体积。该入口复用现有九分量应力数学，保存局部应力产品、逐帧真实观测温度和机械约束历史；当前贡献为 `virial`、`kinetic_included=false`，动态源不标为零速度。随后通过 `thermal-stress` 及 `deliver-properties --local-stress/--thermal-stress` 接入同一 Study。温度从实际记录读取，热浴目标值、烧制范围和局部温度不能相互替代；差分保留有限采样及原始条件。

双源`spatial_mode=layered_interface`模型沿用同一个`create-lammps`入口，显式传入势、协议、站点和资源；创建器将界面几何、原子谱系和两侧原模型记录复制到task-local `interface-sources/`并加入transfer_paths，保留P11、两源相身份和独立方法来源。创建不提交；没有交叉势输入时不自动选择或拼接势。`deliver-properties --interface <mlcc.interface-delivery-request.v1 JSON> --study <JSON> --output <JSON>`交付已有模型与可选task.json的输入/参数来源，未运行的牵引、热响应和局部热应力保持null。接口详情见`docs/p11-layered-interface-contract-v001.md`。

通过 `create-lammps --study --model --potential --protocol --site --request` 显式创建工程任务，参数均指向已声明输入文件/模型目录；创建不提交。用既有生命周期工具执行 Slurm，再以 `parse-lammps --task <task.json>` 读取末帧原生输出；对已完成的固定格式 MD 任务，用 `md-collection --task <task-directory> --output <collection.json>` 读取完整 thermo/trajectory 序列；对已接受的 collection，用 `md-conditions --collection <collection.json> [--window-request <md-window-request.json>] --output <conditions.json>` 生成条件与后处理窗口选择。当前支持三维周期 metal/atomic、单 rank 工程 fixture、run0 与显式 NVE/NVT 输入；Ni NVE 100 步是已完成的真实工程桥接案例，仍不提供采样资格。势的来源、许可、文件、元素顺序及 pair 设置必须明示；run0 不运行 MD。数值计算与后处理放在配置中的计算服务器，客户端仅控制和查看。工程 completed 不能作为科学收敛依赖或势资格证据。材料、势和站点路径均由调用方显式提供，技能不内置默认值。

`md-collection` 只消费已完成的原生任务目录，不提交、不改写源文件，也不补齐缺失的 image flags、速度、unwrap 或采样窗口。输出保留 native job/model/potential 身份、单位、步数和物理时间；缺失证据通过 `missing_evidence` 与 `unresolved` 明确返回，不能据此生成 MSD、扩散、平衡或生产资格。

`md-conditions` 只消费已接受的 collection，并可消费一个显式 `mlcc.md-window-request.v1`。省略 request 时保留 `unresolved_missing`；提供 request 时只选择已有 thermo/trajectory 端点。它不提交作业、不计算统计量，也不把窗口选择升级为平衡或生产资格；`production_qualification` 与 `sampling_equilibrium_qualified` 保持为 `false`。

MD-02 来源绑定使用 `md-sources --request <md-source-request.json> --output <source-selection.json>`。request 必须显式给出 `collection_paths`、`model_id`、`model_version`、`potential_id`、`potential_version` 和 `elements`；入口调用 `select_md_sources`，只绑定已接受 collection 的原子来源与元素索引。输出分别保留 `source_selection` 和 `replica_aggregation`；缺少 `replica_id` 时 replica 状态为 `unresolved`，来源绑定不表示采样聚合或生产资格，也不创建快照、提交作业或计算统计量。

0.10候选在同一入口增加 `purpose="potential_qualification"` 的静态用途，须在protocol提供非空 `experiment_scope`、`kind="run0"` 和 `static_tensor=true`。它允许真实科学模型与未资格候选势，保留原fixture身份、材料/相/来源/谱系；不会开放真实材料普通MD。静态输出清零速度，仅取位力压力六分量，再转换到源坐标系的拉伸正应力。`compare-potential --request --output` 只对显式同几何任务比较相对能、力和应力，参数见README。完整张量原生实验、DFT参照精度/应力标定、材料适用域仍缺；`evaluated_candidate_potential`及续接completed不是科学依赖资格。

0.11候选补充MACE单GPU静态创建输入：显式`pair_style="mace no_domain_decomposition"`，保留上述run0资格用途；site的`lammps.launch_arguments`必须为`["-k","on","g","1","-sf","kk"]`，请求1节点、1 rank及明确1 GPU。创建器写入Kokkos half邻居、atom map、关闭原子排序及newton on，并核对势文件和元素映射。入口不自动选势/换引擎/退回CPU，不开放材料生产MD；创建软件验证、独立引擎原生证据和材料科学资格分别记录。MACE定位公开候选/对照，专用训练主线保持ABACUS→DeePMD-kit→LAMMPS；DeePMD路线同样必须有匹配C++ runtime与LAMMPS内置或插件接口。

`deliver-md --study --task --request --output-directory [--collection] [--window-request] [--targets]`把同一已完成MD任务接到条件、来源选择、thermo和property_delivery结果包。已有collection时显式传入`--collection`，直接消费保存序列并核对原生任务/job、模型、势和Study身份，不重解析原生日志。request明确source模型/势/全部元素及window（whole_record/equilibration_window/production_window）；窗口缺失就交付unresolved。任务原生job与本次analysis_scheduler_job_id分别保留，报告写入新workspace目录，后处理在计算站点Slurm执行。

可选`thermo_diagnostics`请求显式填写`fields`，键为所需的`temp`、`etotal`或`press`，每字段可给`max_abs_slope_per_ps`和`anomaly_z_threshold`；前者单位为该原生字段单位/ps。`blocks`可列`{block_id,start_step,end_step}`，端点来自所选窗口且区间互不重叠。输出样本方差、逐块统计、对真实时间的OLS漂移及总体标准差z-score，保留异常样本的原始索引/step/时间。没有阈值或块时保留相应未决项，不代选参数、不删样本、不自动寻找平衡窗口；块均值离散度不当独立replica或置信区间。`thermo-diagnostics.json`接入同Study交付清单；缺窗口时值为null。既有温度均值/总能首末差和来源状态保留，诊断阈值结果不阻断系统开发。字段合同见`docs/md-thermo-diagnostics-contract-v001.md`。

原子示踪MSD沿同一`deliver-md --collection`入口，请求增加`msd={source_atom_ids:[...],dimensions:3,com_policy:"none",fick_window:{start_ps:...,end_ps:...},thresholds:{minimum_r_squared:...,maximum_relative_slope_spread:...,log_msd_exponent_range:[...,...]}}`。`minimum_msd_change_A2`是可选显式阈值。只消费固定胞、实际原生展开坐标和均匀物理时间；按所选原子及所有时间原点计算三维MSD。缺展开证据时MSD/D为null，不用wrapped坐标重建。阈值缺失或失败保留诊断，D为null；通过时输出单轨迹条件性D，无replica/CI。只做MSD时可显式`thermo_summary:false`，不重算thermo或RDF。结果`md-msd.json`列入同Study清单。

新任务可在既有MD protocol显式设置`unwrapped_trajectory:true`，由创建器另外写出`trajectory.unwrapped.lammpstrj`的`id type xu yu zu`，不替换旧dump。必须由实际原生文件及其输入命令绑定展开证据；生成输入或数学格式夹具不是原生执行验收。完整范围见`docs/md-msd-contract-v001.md`。

`md-replicas --request <request.json> --output <summary.json>`只消费已保存MD交付中的一个明确标量；当前支持`MD_temperature_sample_mean`和`MD_total_energy_final_minus_initial`。请求使用`mlcc.md-replica-request.v1`，给出`source_selection`、`observable_id`、`sources:[{delivery_path,replica_id,independence}]`和显式`interval`。`descriptive`与`student_t`模式按`docs/md-replica-contract-v001.md`声明；replica ID、速度seed及独立执行依据必须来自现有源，不能把分析job或时间块当成独立轨迹。缺replica身份时保留单源描述均值，SD/SE/CI为null，不补造元数据。此后处理经Slurm，不重算thermo/MSD或解析原生轨迹。

`deliver-properties --study <study.json> --md-replicas <summary.json> --output <delivery.json>`把已保存汇总接入原Study，核对各源delivery/task/job/observable并保留原状态、缺项及artifact清单；该交付步骤不再调用统计函数。它不提交MD任务，也不自动发起replica计算。

`thermal-stress --study <study.json> --request <request.json> --output <product.json>`消费已保存局部应力，以显式同模型/势/原子组/体积参考计算完整3×3 GPa差量。请求为`mlcc.thermal-stress-request.v1`，逐状态提供保存产品、已记录区域温度及机械约束历史；缺输入显式null。载荷改变只交付普通应力变化；缺参考或历史保留未决项。相同约束下的差量表示给定热历史下的观测变化，不是平衡热应力系数或唯一温度因果归因。空间温度bin不自动映射为固定原子组，热浴设定值不替代观测。字段见`docs/thermal-stress-contract-v001.md`；后处理经Slurm，不重跑原生计算。

`deliver-properties --study <study.json> --thermal-stress <product.json> --output <delivery.json>`交付保存差量、历史、缺项及来源清单，绑定原source任务与同Study，不重新作差或解析原生表。

读 ABACUS 弛豫父模型和版本，以 ASE 整数矩阵扩胞，输出 LAMMPS data、type_map、parent_atom_id/image_index/child_atom_id。exact 会周期重复掺杂；重随机模型另存。界面有陶瓷和金属多个父模型，slab 不沿真空简单重复。

先明确势的元素、局域环境、T/加载范围、电荷/长程/分子拓扑。bulk 势不能无验证用于界面/分离；不直接拼 EAM/氧化物/聚合物或把形式氧化态当经典电荷。需要时按一致 ABACUS 方法标注，再训练/检验，覆盖应变、表面、剪切和分离；按母轨迹/加载路径隔离测试数据。

先做 E/F、时间步/NVE 漂移、NPT 参考和尺寸对照，再晶界/孔隙/粗糙与局部迁移。virial 需体积/粗粒化才能称应力；不要将纳米高应变率结果直接外推整层器件寿命。

陶瓷/Ni、高分子保留层、临时粘结剂造成的排胶后状态分别建模。保留层默认是待验证的烧结后低温装配假设；无合格反应模型不删除聚合物冒充排胶/烧结。

张开/剪切/热循环明确夹持、侧向约束、面积、温控区、速率、独立高分子构型与无应力温度。真空 slab 不整体三向 NPT。热流实现与多体/长程势匹配后再报告界面热响应；Ni 电子热导不由纯经典 MD 获得。

区分可逆 Wsep、速率相关 MD 牵引/耗散、Ni 塑性、聚合物黏弹与宏观 Gc；未来转交本构时避免双计耗散。参数包附单位、T/速率、方向、误差与来源/适用范围，不输出未算 FEM/相场图。
