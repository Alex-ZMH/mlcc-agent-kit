# 材料势路线与接口验收边界（2026-10-22）

**2026-10-23 04:52 当前状态**：0.24.0已通过应变producer213/216、响应consumer218及安装219（10项新增检查，COMPLETED/0:0，5秒），并通过原版MatterAI宿主启用冻结；0.23回退，源码0.25候选。新增显式clamped-ion±应变SCF/Berry输入、保存源proper/improper响应及父Study交付；24个响应检查有通过证据，214/217失败留档并已定向修复。只使用未提交CZO输入和明确数学正例，无新DFT/MD/训练，不重算冻结项目。原生应变/物理分支、完整Born/Γ/电子介电仍未完成，MACE精度继续后置。详见[0.24交付](system-contracts-v0240.md)。以下版本段落保留历史时间。


**2026-10-23 03:43 当前状态**：0.23已由211/212及原版MatterAI宿主验收启用；0.22回退，源码0.24候选。新增P5固定胞有序SCF能量来源、相对能量及父Study交付，复用177/178和187保存Berry，不新增DFT/MD/训练。物理分支、完整Born/Γ/电子介电及材料资格仍未完成，MACE误差后置。详见[0.23交付](system-contracts-v0230.md)。以下早期版本记录保留其原时间。

**2026-10-23 00:42 当前状态**：0.20.0已通过原生GPU job205（电子收敛，COMPLETED/0:0，33秒，UNLIMITED）、安装job206及MatterAI宿主并启用冻结；0.19回退，源码0.21候选。静电势INPUT→原生cube→单位/网格/原子映射/同task电子来源→公共CLI已接通；203/204各24/11项新检查复用。只新增这一项DFT，没有MD/训练/MACE精度研究。单宿主势不能建立对齐/FNV/带电形成能，相关字段仍null。见[0.20交付](system-contracts-v0200.md)。下一项审查化学势原生参考来源，缺选相/组成不补造、不自动追加DFT。以下旧版本段落保留历史。

**23:39状态**：0.19已启用，0.18回退；新增P4电子参考/Study消费由200/201/202及MatterAI宿主通过。MACE公开候选/对照与ABACUS→DeePMD-kit→LAMMPS专用路线不变。约2.708GPa材料应力差保留未通过状态；现有接口传递正确，继续后置归因/换势/精度研究。本次未新增DFT/MD/训练，以下版本记录为历史。

**22:42状态**：0.18已启用，0.17回退；新增P5来源/Study消费由198/199及MatterAI宿主通过。两条材料势路线、MACE应力偏差后置及未获材料资格的判断不变，未开展新选势或精度实验。以下版本状态均保留历史时间。

**21:58状态**：0.17已启用，0.16回退；本轮仅新增P5后处理/消费链并复用既有证据。MACE/CZO约2.708GPa偏差处置不变：同模型接口/参数传递已通过，材料适用性未通过并后置；未重选势或追加精度实验。ABACUS→DeePMD-kit→LAMMPS专用路线保留，公开MACE仍为候选/对照。文献候选→接口→筛查→重新选择或暂缓的人工流程见下表。

**当前正式状态（2026-10-22 20:38）**：0.16已验收启用冻结、0.15回退。ABACUS→DeePMD→LAMMPS陶瓷工程链由159/166/175纳入0.15，0.16继承；晶界来源链191及MatterAI宿主通过。MACE应力偏差仍后置，不影响已验证的同模型接口/参数传递，不开展新选势或精度调查。没有已通过的材料势生产资格。详见[0.16交付](system-contracts-v0160.md)。

以下早期版本段落保留历史记录时间，当前启用状态以上段为准。

**现行状态（0.13.0）：已验收启用冻结，0.12.0回退，源码0.14候选。** 真实中性能量链host50/defect121经123和安装127通过，缺μ形成能保持null；MD07模块119及最小交付接线127通过，复用MD45。MatterAI宿主与MCP/Python绑定通过。下一核心主线直接进入P5极化/分支/响应，暂停新增Ni MD、RDF精调、MSD/统计/聚合物扩展；独立DeePMD专项保持所有权。旧0.10删除被自动审批拒绝、0.11待退役，本轮未删除。详情见[0.13交付](system-contracts-v0130.md)与[P5下一切片](p5-polarization-delivery-next-slice.md)。

下方已有阶段表和证据保留其记录时间；当前版本与下一队列以上段和滚动JSON为准。

本文定义材料势的候选路线、职责和验收边界，并分别记录实际部署证据与科学缺口。独立MACE LAMMPS已安装并通过声明范围的同模型GPU接口验收；材料生产资格未完成。0.12.0已启用并冻结，0.11.0为回退版，0.13.0为源码候选；0.10.0旧副本清理被自动审批阻断，未执行删除。不修改冻结版本及历史验收证据。

当前采用两条职责不同的路线：

| 路线 | 定位 | 当前状态 | 不能据此宣称 |
| --- | --- | --- | --- |
| MACE公开候选势/对照工具 | 作为公开模型候选和独立对照工具，接入实际LAMMPS路径后评估其在明确材料/相/任务范围内的适用性 | job84原生ASE/CUDA通过；job87静态筛查应力超限；job97独立LAMMPS安装通过，98原生GPU/101后处理接口通过，0.11.0创建/prepare经104通过，106/107/108完成公共任务、原生GPU运行、安装解析和下游消费验收 | 不替换现有Ni LAMMPS工程fixture，不因模型转换或接口接通而获得材料势资格 |
| ABACUS→DeePMD-kit→LAMMPS专用训练势 | 从ABACUS原生标注建立专用训练集，经DeePMD-kit训练/冻结后由LAMMPS执行MD | 独立0.1.0的1/2/4GPU训练、冻结、LAMMPS接口已通过；陶瓷host/defect双system链159、公共166及安装175纳入0.15，由当前0.16继承 | 工程就绪限已测PT/plugin/单节点DDP与单GPU LAMMPS；两帧均训练，无独立验证，目标材料生产资格未完成 |

job93环境安装、job84原生ASE/CUDA、job85应变参考、job87筛查均为COMPLETED/0:0。job87科学筛查未通过：最大应力误差2.8098915674GPa超过0.5GPa；ABACUS参考精度仍未资格，不能把全部偏差直接归因于MACE。历史job81失败及88/89安装过程终态保留于候选实验账本。现有Ni LAMMPS仍是工程fixture；它的run0/NVE证据可以复用任务生命周期和原生输出边界，不能升级为MACE或DeePMD的材料资格。候选MTP/NEP专用势仍需作者提供，公开MACE当前只作为候选/对照，不宣称科学合格。

## 1. 两条路线的职责

### 最新开发决策：系统功能优先

2026-10-23针对用户再次提出的约2.708GPa偏差复核：此值是固定CZO构型的MACE—ABACUS最大应力分量差；同模型ASE—LAMMPS接口最大应力分量差为4.720810959923938e-7GPa，已通过接口门（84/98/101）。公共任务106/107/108另已证明创建、Slurm原生执行、解析及候选势下游来源绑定。两类误差不能混为参数传递故障。当前跳过材料残差归因、参数精调与重新搜势实验，保留科学筛选失败；只有发现单位、映射、来源或真实数据传递缺陷时才修复受影响路径。本次复核仅阅读已有证据，不重算、不更换模型、不新增软件发布。证据见[参考诊断](../workspace/reports/czo-neutral-reference-convergence-v001/report.md)、[同模型接口验收](../workspace/reports/lammps-mace-build-v001/acceptance.json)及[公共任务验收](../workspace/reports/mace-public-v011-v001/installed-108/acceptance.json)。

2026-10-22用户要求：以MLCC系统开发为主，参数精度后置；不影响系统参数传递的问题跳过。当前MACE/CZO约2.708GPa应力偏差记为此候选的科学适用性缺口，停止将其归因、继续加密、应变对照或重新选势实验列为当前开发前置。保留已有数据、失败门限和未资格状态，不删除或改成通过。

该偏差不改变已验证的同模型ASE↔LAMMPS E/F/globalvirial传递、单位、原子映射和来源绑定，也不阻塞任务创建、Slurm生命周期、原生解析、缺陷/铁电数据接口和通用后处理开发。若将该候选用于CZO平衡体积、应力、弹性等实际物性预测，则属于科学结果可信度问题，继续保持未资格。MACE值不得写成ABACUS训练标签；未资格结果不得充当合格科学依赖。0.11公共任务闭环已有106/107/108的独立实证，其通过不依赖该材料误差过线。

### 文献选势与失败后的重新选择

| 步骤 | 当前实现/事实 | 处置及产物 |
| --- | --- | --- |
| 定义实际任务范围 | Study/模型/实验协议已有显式输入 | 记录材料、相、计量、缺陷/界面、温压/场及所需E/F/应力/极化，不能只看元素覆盖 |
| 从文献和官方资源确定候选 | 人工文献审阅和候选登记已有记录，未实现自动文献选势器 | [既有候选检索](../workspace/reports/potential-candidates-v001/literature-review.md)列出CZO专用MTP/NEP、MACE、CHGNet和经典势来源；核对目标性质证据、真实势文件、训练数据、许可、接口，论文或元素覆盖不等于适用 |
| 接口与数据传递检查 | MACE独立97/98/101接口、创建104以及公共任务106/107/108均有证据 | 只修复文件/参数/单位/映射/来源等接线错误，不通过调整材料参数掩盖接线问题 |
| 同范围科学筛选 | 静态比较函数已实现；MACE87及100/102/103为独立实验报告，未自动注册成公共TaskRecord | 保存误差、门限、缺失资格和原生来源；程序正常退出不等于候选科学通过 |
| 科学筛选失败 | 人工决策分支，非自动搜索/换势/训练闭环 | 有实际生产任务需求时，返回文献候选审阅，或按ABACUS→DeePMD-kit→LAMMPS专用路线补标注和训练；否则暂缓材料精度研究，继续系统开发 |

当前选择MACE-MP-0b3用于公开基线/接口验证，并非已确认它是CZO专用合格势。[官方模型说明](https://github.com/ACEsuit/mace-foundations)列明MPTrj及PBE+U训练方法族，不能直接等同当前ABACUS/PBE/UPF参考，也不能仅凭方法族差异判定具体残差成因。未来需要生产CZO势时再针对文献、参考方法和目标观测量重新筛选，不在本轮展开候选搜索矩阵。已有CZO专用MTP/NEP候选尚未取得可运行的权重/参数，不能写成已可切换。

软件门的现状：`potential_qualification.py`保存逐结构相对能、力、应力误差及缺失资格，未通过时`status=not_qualified`，始终不自动授予生产资格；`workflow.py::require_result_dependencies`不把`evaluated_candidate_potential`作为收敛科学依赖；`property_delivery.py::assess_design`对未资格值返回证据不足。当前电子性质交付消费ABACUS任务，尚无通用MACE物性生产消费者；不能把代码门说成整条材料势生产链已验收。

### MACE：公开候选势与对照工具

MACE路线服务于公开候选模型的可运行性、跨实现对照和适用域筛查。候选模型须转换成LAMMPS可用模型，并由实际LAMMPS `pair_style mace`执行；模型的元素顺序、单位、胞、原子映射和设备配置必须显式记录。MACE官方文档给出将模型转换为TorchScript LAMMPS模型的 `create_lammps_model.py` 流程，并分别给出CPU与GPU/Kokkos的LAMMPS接口示例；这些是路线依据，不是本站当前二进制已经具备相应接口的证明。

主代理负责v100上的独立MACE LAMMPS构建和候选任务接线。job97完成安装，job98原生GPU计算完成，但批任务因解析器失败为FAILED/1:0；job101仅复用98输出通过接口验收；源固定为10Sep2025 commit `4d222cb3ee2a6b14083c778968497bf9e0efc4b4`，配置采用ML-MACE + KokkosVolta70 + torch2.5.1cu121 + GCC12.4单GPU；安装和同模型接口已验收，详见[独立引擎记录](lammps-mace-build-20261022.md)。构建与协议报告目录为`workspace/reports/lammps-mace-build-v001`。该工作不修改或替换已有Ni LAMMPS路径，也不把公开模型直接放行到CZO、BTO、缺陷、界面或铁电任务。MACE接口验收时，须用同一冻结MACE模型在ASE/Python参考接口与LAMMPS `pair_style mace`上对相同几何、组成、坐标、晶胞和原子顺序输出E/F/globalvirial，并保存逐项差异。ABACUS参考比较另属材料资格门，参考方法不同；它不构成MACE-LAMMPS接口成功，也不相减不同方法的裸总能。两类证据之外，再单独声明材料、相、温压、应变、缺陷和目标观测量的适用范围。

### DeePMD：专用训练势主线

DeePMD主线的边界是：

1. 用ABACUS在声明的方法、赝势、截断、k点、电子/离子收敛和目标材料范围下产生原生标注，包括能量、原子力和可用的virial/应力参考；训练集、独立验证集和目标范围必须分开记录。
2. 用DeePMD-kit完成训练、冻结和模型格式记录，保存模型backend、版本、元素映射、精度、冻结文件及训练/验证来源。
3. 为LAMMPS提供匹配的DeePMD C++ runtime和实际接口。可采用LAMMPS built-in模式，也可采用plugin模式；plugin模式必须能在目标LAMMPS会话中执行 `plugin load libdeepmd_lmp.so`（或由明确的插件路径加载），并能使用 `pair_style deepmd` 与匹配的 `pair_coeff`。
4. 证明目标模型格式与runtime/backend、LAMMPS版本、MPI布局、CUDA/Kokkos路径和站点构建一致。只安装Python训练包、只成功导出模型，或只在Python/ASE中得到能量和力，都不能证明LAMMPS可运行。
5. 在真实同几何输入上比较训练/冻结模型接口与LAMMPS接口的E/F/virial。接口一致性必须覆盖元素映射、单位、原子顺序、周期晶胞和模型版本；任何差异、缺分量、后端不匹配或并行/GPU差异都保留为失败或未验收。

2026-10-22专项完成：DeePMD3.2.0/PT/CUDA固定runtime、实际plugin加载、1/2/4GPU训练与freeze，以及公共LAMMPS同几何E/F/virial一致性均有原生证据。源码适配沿用TaskRecord/SiteRunner和既有LAMMPS创建/解析；未激活新Bundle。两帧Ni工程数据、100步训练不构成生产科学资格，详见[专项执行书](abacus-deepmd-lammps-execution-20261022.md)及[总验收](../workspace/reports/deepmd-bridge-v001/acceptance.json)。

## 2. DeePMD—LAMMPS接口最低证明

官方DeePMD-kit v2.2.4文档说明，plugin模式通过 `plugin load libdeepmd_lmp.so` 加载，built-in模式不需要该命令；同一页定义 `pair_style deepmd`、模型文件和 `pair_coeff` 的映射方式，并指出该pair style来自编译进LAMMPS的USER-DEEPMD包。官方仓库的master安装说明进一步区分built-in和plugin，要求先有DeePMD C++ interface，并说明可以构建USER-DEEPMD；它还描述了Kokkos下的`pair_style deepmd/kk`路径。

本站不把master文档中的新接口、示例版本或构建方式当作当前v100软件已经支持的证据。必须针对实际安装的DeePMD版本、实际LAMMPS版本和实际v100构建给出以下记录：

| 接口门 | 必须保存的证据 | 未通过时的状态 |
| --- | --- | --- |
| C++ runtime | DeePMD C++ runtime版本、库路径、模型backend/格式、加载日志和原生错误 | DeePMD Python训练可运行，但LAMMPS接口未证明 |
| built-in或plugin | LAMMPS构建配置或plugin加载命令、实际`plugin load libdeepmd_lmp.so`输出（plugin模式）、`pair_style deepmd`与`pair_coeff`输入 | 不能写DeePMD LAMMPS已就绪 |
| 模型/元素映射 | frozen模型、type map、LAMMPS atom type、元素顺序、单位和周期胞 | 映射不一致时拒绝比较，不自动重排或补值 |
| MPI/CUDA | 实际rank、线程、GPU/CUDA/Kokkos构建与运行配置；CPU/GPU路径分别记录 | 不能把Python或单进程CPU结果升级为生产GPU/MPI资格 |
| 跨接口数值一致性 | 同一模型、同一几何、同一组成、同一胞、同一原子顺序下的E/F/virial原生输出和误差 | 任一分量缺失、单位/符号/顺序不明或误差超协议即保持未验收 |
| Slurm原生任务 | sbatch脚本、原生job ID、`COMPLETED/0:0`、资源、数值收敛和完整原生输出 | 不用直接SSH进程、短工程fixture或自动重试替代 |

`virial`与应力的换算、符号、体积和基底必须在协议中单独登记。不能把标量压力当完整virial，也不能用不同几何或不同DFT参考的裸总能相减作为接口一致性证据。

## 3. MACE—LAMMPS接口最低证明

MACE官方LAMMPS文档给出的路线包括：用`create_lammps_model.py`准备TorchScript编译的LAMMPS模型，在输入中使用`pair_style mace`和`pair_coeff`，并按CPU或GPU/Kokkos构建选择实际执行方式。GPU示例需要`PKG_ML-MACE`和Kokkos CUDA配置，文档还提示当前建议单GPU评估。站点构建、CUDA版本、libtorch、MPI和实际LAMMPS分支必须重新核对，官方示例本身不证明v100当前环境已经就绪。

MACE候选通过最低需要：

- 实际LAMMPS二进制能加载目标MACE模型，能回显模型格式、元素顺序、设备和pair style；
- `pair_style mace`/`pair_coeff`的输入与模型转换结果一致，周期图、ghost atom和domain decomposition配置明确；
- CPU/GPU、单rank/MPI配置按实际支持情况分别验证，保存Slurm原生状态和资源；
- 用同一冻结MACE模型在ASE/Python参考接口与LAMMPS `pair_style mace`上，对相同几何、组成、晶胞、原子顺序和单位输出E/F/globalvirial，并保存逐结构及汇总误差；
- 通过后仍只得到候选势在声明范围内的证据，不自动获得全材料、缺陷、界面、极化或生产MD资格。

上述ASE/Python↔LAMMPS同一模型比较只证明MACE接口一致性。材料科学资格另行使用ABACUS原生参考，按目标方法、误差预算和适用域比较候选势；参考方法不同，裸总能不相减，也不把ABACUS比较写成MACE-LAMMPS接口成功本身。

MACE路线不替代现有Ni LAMMPS；Ni工程证据不替代MACE候选接口证据。MACE也不替代DeePMD专用训练主线，除非主代理另行提交路线决策和对应科学验收。

## 4. 两条路线共用的科学资格门

任一候选势进入指定生产实验前，至少要有：

1. 明确材料、相、组成、缺陷/界面、温压、应变、外场和目标观测量的适用范围；未覆盖范围保持未资格。
2. 材料资格门使用ABACUS原生参考与候选势的相同几何、组成、晶胞、坐标、原子顺序、单位和明确能量定义。参考方法、赝势、截断、k点、电子/离子收敛和virial/应力定义可追溯；它是科学对照，不是MACE或DeePMD的LAMMPS接口成功证明。参考方法不同，裸总能不相减。
3. 材料资格或接口门所需的真实同几何E/F/virial对照分别记录。至少记录每结构相对能或每原子能定义、逐原子力误差、最大力分量误差、virial/应力六分量及转换、映射和缺失项；MACE接口门的同一模型字段使用`globalvirial`并与ASE/Python输出对应。
4. 训练/调参数据与独立验证数据分开。不能用同一组几何拟合后再宣布独立资格，不能用Ni或随机短轨迹替代目标材料。
5. 通过目标物理量的数值收敛、Slurm原生终态和资源预算。工程输入生成、单测、短smoke或模型转换只能作软件证据。
6. 若任务要求极化、介电、外场或电致应变，候选势必须有可表达且已实际验证的相应自由度和电边界；普通机械E/F通过不自动授予铁电/介电资格。

材料势科学资格的输出是带候选版本、方法、实验范围、误差、覆盖和缺口的有限结论，不是可任意改写的全局true标志。程序失败或证据不足不判材料不合格，也不能报为生产通过。

## 5. 当前缺口与后续顺序

当前未完成的事实保持如下：

- 独立MACE LAMMPS安装及单V100接口已验收（97/98/101），0.11.0创建/prepare已补显式map、Kokkos邻居及启动参数并由104检查通过；公共任务106/107/108已完成原生GPU生命周期和安装下游消费；详见[独立引擎记录](lammps-mace-build-20261022.md)；现有Ni路径保持原位；
- job84/87已完成，原生ASE/CUDA接口通过但三构型应力筛查未通过；其科学失败及参考精度缺口见[候选实验报告](../workspace/reports/mace-czo-static-v001/report.md)；
- 独立DeePMD与源码公共接口已完成工程验收；尚未进行Bundle发布接入、生产规模性能测量和目标材料科学资格，已验收范围不扩展到多节点或多GPU LAMMPS；
- 没有已确认的陶瓷/缺陷/界面专用势科学资格，候选MTP/NEP仍需作者提供，公开MACE仍是候选/对照；
- 形成能、VBM、势对齐、介电、FNV/eFNV、超胞尺寸和Berry GPU等科学缺口不因材料势路线修订而改变。

后续复用已完成的97/98/101/104/106/107/108证据，只补实际系统路径缺口。参考调查100/102/103已结束；当前停止MACE应力归因、Ca UPF精度追查、继续加密、应变及重选势实验。0.12.0已完成MD-01/02/06与单Study结果交付的安装集成；MD07执行窗口job119已有真实工程RDF证据，公共模块/CLI接入、安装发布与验收仍待完成。主窗口继续晶体缺陷和铁电/介电系统数据链。材料筛选未通过不阻塞上述系统工作或软件发布。DeePMD保持专用势主线，独立专项的训练/冻结、匹配C++/LAMMPS接口和源码公共任务链已完成工程验收；Bundle发布和实际科学资格仍分别未完成，不用MACE替代。必要数值检查均通过v100/Slurm，保留原生job ID；不自动换势或重跑已有验证。

## 6. 官方依据与项目证据

- [DeePMD-kit v2.2.4：LAMMPS commands](https://docs.deepmodeling.com/projects/deepmd/en/v2.2.4/third-party/lammps-command.html)：plugin加载、built-in说明、`pair_style deepmd`、`pair_coeff`和USER-DEEPMD边界。
- [DeePMD-kit master：Install LAMMPS](https://github.com/deepmodeling/deepmd-kit/blob/master/doc/install/install-lammps.md)：C++ interface、built-in/plugin构建及Kokkos路径。master是上游当前文档，不能当作本站当前版本已经支持的证据。
- [MACE：MACE in LAMMPS](https://mace-docs.readthedocs.io/en/latest/guide/lammps.html)：模型转换、`pair_style mace`、CPU/GPU/Kokkos构建及执行示例。
- [材料势资格下一切片](potential-qualification-next-slice.md)：现有Ni工程证据、E/F/stress比较缺口和生产资格边界。
- [PLAN](../PLAN.md)：P9/P10路线、阶段依赖和全局科学验收。



