# CaZrO3 原生介电实测协议 v001

执行终态（2026-10-23）：参考269及24位移284–307全部COMPLETED/0:0；311电子、316–339极化、345原始Γ、347–349 Born分支族及坐标合同均已保存。355真实同Study交付与356安装副本通过，0.30已启用，0.29回退、源码0.31候选。[正式工程验收](../workspace/reports/czo-native-response-v030-install-v001/release-acceptance.json)。以下保留输入冻结/提交时记录；不是仍待提交或允许重复运行的队列。物理Born、离子贡献及完整静态介电仍为null；电子贡献及原始来源链已交付，科学生产资格未建立。

2026-10-23 用户新授权：按陶瓷原生介电链实测，采用多卡并行。此任务取代旧Gamma独立修复的下一优先级；0.29冻结不改，软件薄适配进入0.30。真实参考SCF job269已COMPLETED/0:0，69秒；原生矩阵/力/SCF收敛已产出，下一步位移与原生后处理。协议中的待核对数值必须在首次对应计算前补全，不能按占位值运行。

## 对象与完成标准

唯一父对象：workspace/models/cazro3-pnma-pristine/v001/model.json及model.extxyz，Ca4Zr4O12，已选未掺杂正交Pnma；父Study为workspace/configs/cases/cazro3-firing-v003.json（cazro3_firing_validation_v003）。这是未弛豫实验参考几何；本轮固定胞小位移响应不冒充烧制温度平衡态。BTO相未选择仅保留自身缺项，不阻塞CZO。无温度、掺杂、晶界矩阵，不重跑237。

必须把同一物理方法下的真实ABACUS数据连到Born、Gamma、电子介电贡献及Study交付。允许ABACUS矩阵的可追溯第三方后处理，准确标注它与引擎直接介电输出的区别。不能用197数学数据、文献常数、2I或未选择材料填补缺项。原生电子收敛、绝缘性、分支连续性、完整力/极化维数分别判定；单方向/单列不称完整介电。未弛豫参考的稳定性问题和生产数值资格独立保留。

## 路线选择及复用

既有PW50/177/178/180–185/187/188由实施窗口逐项清点，只在其原模型/方法/位移方向范围复用。当前PW源不含LCAO H(R)/S(R)/r(R)。现场核实已装ABACUS、abacuscopilot及Ca/Zr/O赝势和匹配NAO资源，并审查ZStar/PYATB实际函数。若采用LCAO，建立明确新方法，Born/Gamma/电子贡献均用该方法自己的SCF/矩阵/力，旧PW值不混入其差分或总介电。

第一批计算目标是新方法的一个真实父参考SCF及其电子响应。实际UPF/轨道、库cutoff基准与单位、1.2倍输入、k点、SCF阈值和solver在资源审查后冻结；scf_nmax明确1000，DFT time=0/no-requeue。参考任务本身必须保留能量/力/原生矩阵/绝缘证据，可复用到后续链，不另做benchmark。

完整Born/Gamma位移数量由实际Pnma对称性和选定原函数在v100 Slurm生成任务清单后确定；清单必须写明每个原子ID/方向/幅度/对称性映射和实际DFT总数，再提交该批。当前冻结数量：父参考1项已完成；位移24项已完成且312已收齐全部原生源；参考PYATB311已完成，24点极化后处理316–339已提交。后处理不等同新增DFT，具体网格/公式在源路线核实后冻结。不会因有4卡扩大材料范围。

## 多卡资源和依赖

冻结预算为独立任务各1V100/1MPI/2CPU/8GiB，最多3项并发，总3GPU/6CPU/24GiB。v100现场总4V100/16CPU/27800MiB，cpu/gpu共用该节点；其他安装/后处理占用同一内存账本，不重复计资源。先用实际必要的参考任务证明该LCAO solver/device支持，不盲申单点多GPU、不重算旧任务做benchmark。独立位移各有独占目录和job ID；同点若需Berry必须依赖自己的已收敛SCF，不能共用其他位移的电荷。DFT均time0/no-requeue；资源失败/原生未收敛保留，不自动重提或调参。

模型生成、科学后处理及验收也由Slurm执行。CPU后处理只有在对应第三方接口没有可用GPU实现时使用，单项声明CPU/内存/时间；本机仅编辑、传输、调度控制及查看证据。

## 独占所有权

- 主线：本协议、CURRENT_TASK/PLAN/plans三JSON、workspace/reports/czo-native-dielectric-v001、输入生产/模型与Slurm/公共集成。Luna native_dielectric_runtime独占本目录runtime-audit.md；native_zstar_route独占zstar-route-audit.md，均只读审查。
- 既有实施窗口01a15851-eb0c-7832-ba67-4833802afd0f：workspace/reports/czo-native-dielectric-consumer-v001、真实源清点、保存原生数据的消费/聚合/交付与必要薄适配。改公共模块前列文件交接；不并行提交DFT。
- 旧Gamma隐式Hermitian行为仅在这条原生链需要该入口时作最小修复，不独立扩成另一发布主线。

## 本轮核对产物与后续冻结点

runtime-audit.md：实际环境、solver/GPU、UPF/NAO/cutoff、PYATB/ZStar可用性；zstar-route-audit.md：实际原函数、所需输出、电子响应公式和自动运行行为；另一窗口清点原生源。三者交回后立即更新本协议的方法/任务清单、生成Slurm输入并按已授权范围实际提交，不再要求泛泛批准。

## 首个参考 SCF 冻结输入（2026-10-23）

method_set=czo-apns-pbe-lcao-native-dielectric-v001；任务czo-native-lcao-ref-v001，远端/home/v100/projects/mlcc/workspace/tasks/czo-native-lcao-ref-v001。ABACUS 3.10.1普通abacus_env二进制，LCAO/GPU/cusolver，1 MPI。PBE、nspin=1、非SOC、neutral、fixed occupations；Gamma-centered 4×4×4、symmetry=-1、gamma_only=0；ecutwfc=120 Ry，scf_thr=1e-8，scf_nmax=1000，nbands=100，Broyden mixing_beta=0.3。输出力、应力、电荷、能隙、H(R)/S(R)/r(R)。这些是本轮固定输入，不宣称网格/NAO/介电积分已收敛；不自动加密或重试。

逐元素配套依据为现场PPORBs中pseudopotentials/element.json、ecutwfc.json、两目录readme及实际UPF/NAO header。Ca.upf配Ca_gga_10au_100Ry_4s2p1d.orb；Zr_ONCV_PBE-1.0.upf配Zr_gga_10au_100Ry_4s2p2d1f.orb；O.upf配O_gga_6au_100Ry_2s2p1d.orb。Ca/O PseudoDojo、Zr SG15是此APNS集合的既定逐元素选择，不要求不同元素统一赝势系列。各价电子10/12/6；Ca fully-relativistic UPF按ABACUS非SOC average_j处理。PSP推荐截断70/100/90 Ry、NAO均100 Ry，输入120=1.2×max(100,100) Ry。采用现场efficiency NAO；库明确未推荐其用于高精度未占据态，记录为电子介电精度未资格，不阻塞本轮真实系统链。

参考后处理冻结为PYATB direct-static独立粒子clamped-ion电子介电；积分6×6×6、occ_band=80以原生电子数160再核对、minimum_gap_eV=0.01仅为已采样点绝缘门。运行版本由实际安装和作业内version文件记录。真实输出经native_derived/native_source_bound合同交付，不标ABACUS直接ε输出。Born/Γ位移计数仍须在Slurm生成清单后冻结，不能预设对称性结果。
## 位移批次冻结和实际提交

Slurm输入生成283完成：24个中心Cartesian位移，Ca原子ID0、Zr4、O8和12，各±x/±y/±z、0.01Å；固定胞/primitive I/supercell I，symprec1e-5Å，8个对称操作，各site位移轨道rank3。清单workspace/reports/czo-native-dielectric-v001/displacement-manifest.json。DFT合计25项=参考269+位移284–307；未重跑任何旧任务。

24个位移按3条独立调度队列提交，每条afterany仅限制同时运行数，不构成不同几何间科学依赖，也不重试失败项。每项独立原子初始电荷/目录/child Study/derived model/原生矩阵与力。请求2CPU每项，现场Slurm因物理核/线程规则实际分配4线程，三项合计12线程/24GiB/3GPU，仍在节点16线程/27800MiB/4GPU内。后处理共享这份总资源账本，必要时等待调度释放内存。
