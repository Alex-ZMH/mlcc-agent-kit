# Slurm 故障期间的核心开发分工

本轮最终状态（2026-10-25）：0.47已启用冻结，0.46回退，源码0.48。524/525真实保存源消费、526的49项新检查、528安装接入全部COMPLETED/0:0；新增法向夹持路径的准备527、原生529及消费530通过，三点均原生force tolerance。所有数值在v100 Slurm，Windows仅用于编辑/传输和公共runner控制。0.45已按精确路径退役。完整[发布验收](../workspace/reports/core-integration-v047-v001/release-acceptance.json)与[原生路径验收](../workspace/reports/interface-normal-relax-native-v001/acceptance-reviewed.json)。真实界面电势正例、P4物理参数和BTO离子静态项仍未决，以下实施过程不覆盖此最终状态。

2026-10-25 21:40恢复后续：Slurm已由用户认证恢复，主线读取523实际FAILED/1:0并提交一次封存剩余消费524，COMPLETED/0:0、8秒。BTO电子张量/Born及Gamma非正定造成的离子/总静态null已完整传入同Study，六项523检查未重复。Luna完成P4保存源消费525，同样COMPLETED/0:0、8秒，六入口及同方法/原生job/电荷/VBM绑定通过，科学参数缺项保留。对应验收为`workspace/reports/bto-native-response-v047-v001/acceptance-524.json`及`workspace/reports/charged-potential-native-v001/acceptance-525-reviewed.json`。新路径联合检查由原实施窗口继续，第三窗口准备安装。以下“待恢复/未运行”保留为本轮开发准备时状态，不覆盖此最新记录。

2026-10-25：主线已读取监督聊天原始用户消息（turn `01a1731e-b2ef-78d2-9629-807a2ba88190`）：先修 Slurm，恢复后只续接未完成消费/验收，三个窗口并行推进不依赖 Slurm 的核心功能。

当前启用 0.46、回退 0.45。0.47 的 `candidate-v047-followup.tar.gz` 与 `consume-followup.sbatch` 已封存；本轮新增开发不覆盖该副本，不混入其未完成消费验收，不提前升版/启用。本地只编辑、静态审阅和查看保存证据；数值运行、模型生成和测试均等待 v100 Slurm 恢复。监督独占控制器诊断/恢复协调，开发窗口不改服务、不提交作业。

## 文件所有权与实际函数

| 责任方 | 最小实际交付 | 独占文件 |
| --- | --- | --- |
| 主线 + Luna | 保存489/490/496原生电势、电子数、方法/模型/Study来源接到既有势对齐/FNV/形成能请求；复用已交付绑定与算法，不新造源bundle | `workspace/reports/charged-potential-native-v001/` 下新增请求、消费脚本和交接；原 `potential_alignment.py`/`charged_defect.py`/`defect_references.py`/`electrostatic_potential.py` 如发现实际缺陷再由主线审定修改 |
| 原实施窗口 | 现有固定胞法向响应增加显式夹持原子和可弛豫内部原子的位移控制最小化路径；输出原生停止原因、自由原子力和夹持反力，沿现有 normal response 消费 | `lammps_interface_normal.py`、`interface_normal.py`、`interface_normal_tasks.py`及对应测试；必要 `lammps.py`/`lammps_tasks.py` 接线归该窗口 |
| 第三窗口 | 已保存的界面静电势产品按明确方向和区域消费，报告区域电势差及沿法向场；可选同模型参考/受扰状态的差量，保留单位、符号、边界和来源 | 新 `interface_electrical.py`、`interface_electrical_sources.py`及对应测试；不编辑根电势reader、LAMMPS或共享CLI |

上述为本轮实施分工；两个执行窗口现均已交回源码，全部相关文件由主线持有。共享 `cli.py`、`property_delivery.py`、Skill 接线已由原实施窗口串行完成，先接法向响应，再接第三窗口已审定的电响应函数。P4 已确认既有公共入口足够，无需新增CLI。主线持有 CURRENT_TASK、PLAN、阶段JSON、版本及总验收。

## 科学与实现边界

- P4 必须核实保存电势是否已含原生逐方向数据，而不是再解析或重跑 DFT。不得猜远场窗口、介电标量/张量、VBM或化学势，也不得把 CZO LCAO 介电与PW缺陷方法自动混为同方法。缺输入只使相应计算请求待补，不阻塞源适配实现。
- 主线已核对496保存电子产品：host490为160电子、q0、VBM=8.649724753610428 eV；缺陷489为152电子、q+2，同记录method_set。VBM已有来源，不再笼统列缺。完整同方法/模型/谱系绑定由现有公共消费者执行，不以method_set字符串相同替代。保存cube已有完整values_eV，不缺网格解析器。尚缺selection、显式标量FNV参数（含有来源的ε与采样/积分参数）、同方法μ和EF网格；不会自动取LCAO介电张量平均。
- 法向弛豫路径使用显式 `min_style`、力/能量收敛阈值、迭代/评价次数和夹持/自由原子ID。只固定胞、位移控制，不暗选实际Ni/BTO载荷或追加MD。原生迭代耗尽必须保留。夹持反力必须来自未被 `fix setforce` 覆盖的原始力；实现需核对 LAMMPS 官方语义。保留双周期界面定义，不自动除2、不把返回坐标称为物理恢复。
- 电响应只实现有明确定义的静电势剖面/区域消费。势的单位、电子势能与电势的符号关系以及轴/胞映射必须显式；区域为用户给出的采样范围，不能自动找平台或平滑。普通MACE/DeePMD E/F不能生成电响应；无原生界面电势时保持缺源。不得从电势剖面编造局部极化、介电常数、电容、屏蔽长度或电场耦合MD。
- 数学检查只验证函数，真实源检查只消费新增/已保存证据。现有冻结与已通过检查不重复。所有新增功能明确标记未运行/未验收，Slurm恢复后只运行变更路径所需检查。

## 交接要求

交回真实函数名、修改文件、输入/输出合同、静态审阅结果及待Slurm执行的最小检查。禁止只交盘点或空合同。主线审查后接共享CLI和同Study；恢复后先完成523剩余消费，再安排新路径检查。

## 本轮实际实现与审阅

- P4 已准备 `native-request-489-490.json`、`consume-existing-p4-chain.py` 和同名 sbatch，直接调用已安装0.46的三条领域命令及三条同Study交付。没有新增公共源包装器或重复已有算法。完整保存源绑定、方法比较和缺参数传播待本次Slurm消费验证；未执行任何新计算。
- 法向路径已在既有 `validate_normal_protocol/model`、`normal_input_commands`、`parse_normal_outputs`、`normal_response_from_points` 与 `read_interface_normal_task` 中实现 `fixed_cell_clamped_internal_relaxation`。主线与Luna静态审阅了位移累积、三组原子、解除力覆盖后的反力和原生停止原因。数据可用与原生弛豫收敛分开，双周期胞净响应不改称单界面牵引。10项新增检查及一次真正原生最小化路径均未运行，详见 `workspace/reports/interface-normal-relax-v001/handoff.md`。
- 电势领域函数 `calculate_interface_electrical` 和保存源函数 `build_interface_electrical_product` 已实现，主线已审查公式与真实producer字段。此前错误的映射顺序假设、LAMMPS专属晶胞字段和扁平INPUT假设已修正；保留ABACUS元素分组、周期坐标等价、嵌套INPUT/OUT.INPUT及可选NAO/网格方法字段。当前无实际界面电势源，bulk CZO不能替代。交接 `workspace/reports/interface-electrical-v001/handoff.md`。
- 公共 `interface-electrical --study --request --output` 及 `deliver-properties --interface-electrical` 已实现并经主线静态审阅。相对电势路径按请求文件目录解析；原始来源、请求/Study绝对路径和后处理job ID保留，保存交付不重算响应。7项新增公共接线检查未运行。共享源码和Skills已交回主线，见 `workspace/reports/interface-electrical-v001/public-integration.md`。
- 唯一新路径联合脚本 `workspace/reports/interface-electrical-v001/verify-public-integration.sbatch` 选择六份新测试文件，并对保存job439 Ni/BTO Study执行两条公共命令检查缺源null交付；CPU1/2GiB/5分钟/no-requeue。它取代分散的法向/电响应检查脚本，不运行引擎，不建立真实界面电势或夹持最小化通过证据。P4脚本另以已安装0.46消费保存489/490/496。两者均仅准备，未传输提交；恢复后先完成523剩余消费，退出终态另查询归档。
- 本轮仅源码编辑、保存证据检查与静态审阅，运行验收仍未进行。不得用上述实现完成说明替代Slurm终态、真实界面原生源或软件启用记录；0.46仍启用，0.47封存消费候选保持独立。
