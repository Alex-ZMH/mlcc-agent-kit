# CZO 真实 MD 源：MSD、独立副本、匹配约束热应力

2026-10-26。依据已读取的人类授权 `01a1770f-104c-7541-8cc0-246dfa2f769a`：先完成 LAMMPS 实际工程链，随后处理 ABACUS 静态未决/实例缺参数；允许自主确定工程实例参数，原生状态与适用性照实记录。

## 本批固定范围

- 不重复法向529/530、切向531–534、NEB546–551、旧155/466/458/462计算。既有势、模型和数学函数复用，不训练或搜索新势，不扩材料、温度、路径或精度矩阵。
- 原生模型：`/home/v100/projects/mlcc/development/0.10.0/project/workspace/models/cazro3-pnma-pristine/v001`，20原子、固定原胞、原stable atom IDs；无新结构生成选择。
- 势：`deepmd-czo-neutral-joint-training-v001`，版本/训练job146；`/home/v100/projects/mlcc/development/ceramic-training-v001/project/workspace/tasks/czo-neutral-joint-training-v001/frozen_model.pth`及同目录模型卡。保留短训练/未资格状态，不能据此阻断工程输入输出链。
- Study沿用466：`cazro3_firing_validation_v003`，case `cazro3_pnma_undoped`，model `cazro3-pnma-pristine/v001`；method_set `lammps-deepmd-czo-neutral-joint-training-v001-146`。本批实际目的为工程采样，历史Study角色不能授予材料资格。300/400K是本批热浴条件，与烧制温区及静态DFT明确分开。
- 引擎/插件沿真实546/466：`/home/v100/dpa4/releases/3.2.0/bin/lmp`、同prefix MPICH launcher和DeePMD插件；环境脚本为 `/home/v100/projects/mlcc/development/deepmd-bridge-v001/project/workspace/configs/deepmd-lammps-env-v001.sh`。

## 唯一协议与预算

| 项目 | 已审定值 |
| --- | --- |
| 原生任务 | 4个独立Slurm任务：300K×seed202610261/202610262；400K×相同两seed。相同温度的两任务才是副本集合；温度组不能混合。 |
| 动力学 | 固定胞NVT、全原子移动、周期p/p/p、无固定原子组、无外载/变形；速度初始化目标T、独立显式seed、去初始总动量。 |
| 时间 | metal单位；dt=0.0001ps；Tdamp=0.01ps；每任务单次run6000，不reset_timestep，不构造多run调度。 |
| 窗口 | 按现有闭区间接口明确equilibration=[0,990]、production=[1000,6000]，均为dump10实际帧，不共享step1000；连续积分仍0–6000。生产窗0.1–0.6ps，共0.5ps；预平衡段不等于已证明平衡。 |
| 输出 | thermo/dump每10步；原常规trajectory保留；另有严格五列id/type/xu/yu/zu供现有MSD；opt-in采样sidecar保留id/type/xu/yu/zu/ix/iy/iz/vx/vy/vz/centroid virial9。 |
| 资源 | 每任务1节点、1 MPI rank、2 CPU/task、1 V100、6GiB、20min、no-requeue；4任务同时最多4V100/8请求CPU/24GiB。Slurm实际CPU分配保留原值，不与请求量混淆。 |
| 共享状态 | 锁协议时节点Slurm RealMemory27800MiB、CPUAlloc0/AllocMem0；系统available29755MiB，4GPU各占5MiB且利用率0。提交前若变化，排队而不超售。 |
| 准备/新软件检查 | v100 Slurm CPU1–2、GPU0、6GiB、10min；一次生成新输入并验新增行为。不得先重跑旧smoke。 |
| 新消费 | v100 Slurm CPU2、GPU0、6GiB、10min；已有函数+新薄适配的必要检查/公共调用合并，不重跑数学旧验收。 |

所有原生失败保留，不自动重试、改参数、换引擎。资源/运行长度是本批有限MD预算；后续真实DFT仍scf_thr1e-11/time0，不套用MD时限。

## 参数和输出交接

第三窗口拥有原生writer、采样sidecar reader及 `mlcc.md-native-stress-source.v1` 保存源，向原实施交明确字段后串行接线。新增purpose=md_native_sampling，不放宽旧potential_qualification的run0边界；独立pressure-series.dat以Nrepeat=1保留T与total压力六分量，旧MD thermo/header不动。每个任务保存原job ID/终态、Study/model/method/potential、protocol、原输入/日志、atom-map/Prism、源文件与采样/统计角色；不能把报告生成job当原生MD job。

1. MSD：O原子source IDs8–19；真实五列展开坐标，固定胞，真实step/time；dimensions=3、com_policy=none。诊断拟合窗口lag0.01–0.10ps，不提供Fick数值合格阈值；保留MSD、拟合/原点数与诊断，D=null。不得追自发跳跃、延长到“漂亮D”或补造unwrap。
2. 副本：按300/400K分别消费两份真实MD交付；选择现已支持的温度均值observable、descriptive n=2均值/SD；按既有descriptive合同，SE和置信区间为null，不改为student_t，不宣称覆盖率或平衡，不把MSD曲线冒称已聚合。独立性为同父模型不同初速度seed、不同原生执行。
3. 应力：逐采样帧保留九分量原始centroid virial及分量顺序、单位、sourceCartesian/Prism约定；首批whole_cell采用virial-only、kinetic_included=false。另外保存的原生完整total压力张量含其明确kinetic语义，不能混作同一个应力源或以缺项补0。
4. 热致差分：同seed的300K参考与400K目标，whole_cell全20原子、真实固定胞体积。由新保存源薄适配形成窗口应力产品，显式均值定义、原frame_keys和样本；复用已有单位/张量/差分函数，不把动态记录强塞旧run0协议。
5. 温度/机械历史：实际T取原生观测，与应力帧逐项绑定；`mlcc.region-temperature-history.v1`和`mlcc.mechanical-history.v1`保留各自原protocol及source_files。机械样本明示cell/boundary/fixed_atom_ids=[]/loading.kind=none。相同约束下差分仍可能含瞬态/结构/初态贡献，不能叫平衡热应力系数或温度唯一因果。
6. 同Study：新MSD、温度副本、动态应力及热应力保存产品都绑定上述CZO Study；原生与分析job分开。Ni/BTO458/462仅复用保存真实热源；非等价双界面不按50/50虚构单界面G，能交付的胞级响应与未决单界面量分开。

## 独占文件与完成条件

- root：本合同、AGENTS/CURRENT_TASK/PLAN/计划JSON、资源/Slurm协调、科学审阅、集成、唯一必要安装与启用。
- 第三窗口：`lammps.py`、`lammps_tasks.py`中本批最薄hook；新`lammps_md_sampling.py`及专测；`workspace/reports/czo-md-real-sources-v001/native-producer/`。不改旧ceramic NVE限制、旧run0接口或公共CLI。
- 原实施：`md_msd.py/md_replica.py/thermal_stress_sources.py`及确需的`md_trajectory/md_sources/md_conditions`中实际必要薄适配，CLI/property_delivery/MD Skill；`workspace/reports/czo-md-real-sources-v001/consumer/`。复用`local_stress_from_frames`多帧/旋转/均值，动态产品明确virial_only，不沿用zero_velocity描述；不重写数学函数，不改writer。root独占workflow公共续接的必要接线。
- 不重造runner、来源框架、插件系统。格式/路径/来源不匹配属于需修复的软件问题；材料数值不好或短采样不充分照实交付。
- 验收：4个真实原生终态与原生数据→MSD曲线和拟合、两组真实副本统计、匹配条件应力差与历史→同Study→一次安装副本入口。工程通过后推进后续ABACUS清单，不以温度/势精调替代系统开发。

后续ABACUS工程选择已获人类授权，不再等待材料参数批准：BTO保持已选P4mm父结构，分别单掺Dy、Ho；首批拟2×2×2、Ba7Ti7R2O24、每元素一Ba位一Ti位自补偿q0、各1构型；f-core PBE scalar NC11e UPF及配套NAO、nspin1、无SOC/价层4f U。正式提交前仍须核原生资源、父ID映射与同方法host配套；LAMMPS本批完成后才开展有限host/Dy/Ho清单，不扩响应或精度矩阵，不伪造占据或收敛。
