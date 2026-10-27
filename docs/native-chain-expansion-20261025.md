# 2026-10-25 已授权原生链增量

授权来源：主线已读取监督聊天“叮嘱”中2026-10-25原始用户消息。用户要求继续独立实现光刻胶来源的MSD/扩散、多副本统计和局部热应力，并授权按CZO计算标准推进BTO原生电子/Born/Γ、Ni/BTO原生热响应及带电缺陷电势。授权覆盖旧“一概无新增DFT/MD”的限制；仍不展开温度/精度矩阵、不重复已有CZO结果。当前0.45已启用、0.44回退、源码0.46；MD05经455/456及安装461验收，单一真实来源的replica统计仍未决。

## 2026-10-25 11:30增量

- BTO准备460的目录冲突失败保留；463仅续接缺失的18个位移输入。唯一参考DFT464为GPU、time=0，COMPLETED/0:0，39秒；原生40电子，第23次迭代density error=1.82185661927e-12，明确电子收敛，H/S/r已写出。主线审定后批准这18个已有端点按同节点三卡资源并行，无新增相/精度矩阵。原生解析仍由`native_lcao_producer`负责；独立`postprocess-producer/`由`native_electronic_cli`最小移植既有CZO函数，先审定再提交PYATB，不与原生账本写入交叉。
- Ni/BTO457准备、458真实GPU100步、462原生消费/同Study均COMPLETED/0:0。AB空bin保留null；BA已输出温差4212.459690909091 K，且原生整体温度出现显著瞬态升高，不能称热浴目标温度下稳态。缺热流分配，单界面G/R为null；不追加MD优化。
- 带电准备459 FAILED/1:0来自host元数据与子模型经extxyz序列化后的精度表示差异。严格原子ID/顺序和实际执行extxyz一致，非原子错配。主线批准仅修配对预检为比较真实执行结构，保留parent/O8/q+2及失败证据；不改原模型、不放宽比较容差，成功后提交原定匹配host/defect两项DFT。
- 第三窗口已提交DeePMD九分量原生run0工程检查466；原实施窗口继续局部热致应力参考差分/温度与约束历史模块。两条路线独立，不重训或互证MACE。

## 任务和所有权

| 工作 | 当前输入/执行范围 | 所有权与交接 |
| --- | --- | --- |
| BTO原生介电链 | job361未掺杂中性化学计量P4mm5原子/[001]模型，保留Ti/O位移；核实自己的PP/NAO/价电子/带数/固定占据与k点后，参考CZO显式位移/原生力/H-S-r→Born/Γ/电子介电→离子/总介电同Study | root科学审定；Luna `native_lcao_producer`独占`workspace/reports/bto-native-dielectric-v001`输入准备，主线审定具体方法后提交。无新相、掺杂、弛豫或精度矩阵 |
| 带电缺陷势 | 已审定O8 vacancy/q=+2、19原子、job80输入来源；新scf1e-11/1000上限、PW120Ry/k444/88bands/nspin1 fixed/out_pot2。旧host205为100Ry/k222/scf1e-4，不可配对；只新增该缺陷的同胞pristine母模型同方法host一项，组成明确的2项最小原生势源 | root已审定并授权Luna `next_core_scope`在`workspace/reports/charged-potential-native-v001`准备/提交。新共同method_set=`cazro3-oncv-pbe-pw-e120-k444-scf11-pot-v001`，tasks=`p4-czo-vo8-q2-pot-scf11-v001`与`p4-czo-host-pot-scf11-v001`；每项1GPU/1CPU/8192MiB/time0/no-requeue。旧80/205保留，不把历史裸标签混入新结果；无显式介电/选区/μ，不跑FNV/对齐 |
| Ni/BTO原生热响应 | 复用439模型/Study/MACE势与445输入；新独立task，18原子固定胞，下面的显式工程协议 | root确定协议；Luna `native_electronic_cli`独占`workspace/reports/interface-thermal-native-v001`，授权提交并在实际终态后消费 |
| MD05 | 保存的单一observable，多replica身份/独立性与显式统计方法；不重算45/105/450 | 第三窗口领域模块；原实施窗口公共CLI/Study，交接后主线集成 |
| DeePMD逐原子virial | 现有匹配CZO冻结模型/type_map，一次新增九分量原生run0路径；不重训、不互证MACE | 第三窗口MD05交回后独占`lammps_local_stress.py`/`local_stress.py`及必要creator/tests；原实施窗口收到接口后接CLI/Study。资源及实际版本另在专项执行单明确 |
| 局部热致应力变化 | 显式同模型/势/原子映射/区域体积、参考状态、温度与机械约束历史；同约束差分才能称热致应力变化，载荷改变不得改名纯热应力 | 原实施窗口MD05交回后做独立`thermal_stress`模块；不改第三窗口独占的原生/局部应力文件 |

2026-10-25用户已明确“BTO 分别单掺，先提出文献工程方案”，主线已读取监督聊天原始userMessage核实。首批为BTO:Dy与BTO:Ho两个独立系列；Dy+Ho共掺及CZO掺杂不在本次选择内。监督负责提出有文献来源的最小工程方案，具体位点、浓度和补偿仍为proposal pending；尚未授权据建议直接生成或提交稀土计算。原投料mol R₂O₃/100mol主体不能直接作为晶格替位比例。普通E/F势不代表电场耦合模型；界面电响应和单界面牵引仍需相应明确输入和可识别的物理定义。job442双周期界面刚性位移的总力不能靠任意原子分组变成单界面牵引。

## Ni/BTO最小原生协议

新task：`p11-ni-batio3-interface-thermal-mace-native-v001`。不覆盖445的input-only任务。

- 439既有18原子固定晶胞，面积16Å²，法向+z、双周期界面，原双父源和映射保留。
- 初始300K，速度seed12345；热源Ni原子0–7为310K/seed23456；热汇BTO原子8–17为290K/seed34567；Langevin阻尼0.1ps，zero/tally均yes。
- dt=0.001ps，100步，每10步输出原热浴累计能量、空间温度与旧轨迹；bin宽1Å。数值为本次明确选定的短时工程协议，不是烧制工况或稳态采样声明。
- 原MACE/Kokkos引擎10Sep2025，GPU1、1MPI、2CPU、3072MiB、10分钟、no-requeue；不请求逐原子virial，因此不依赖MACE该输出能力。
- 消费whole_record已输出热表，AB片区bin6→8、方向+1；BA片区bin1→14、方向−1，依据439原始层位置事前声明；原生空bin保留缺项。
- `heat_allocation=null`：交付总源/汇功率与片区温差，不默认除2或伪造单界面G/R。瞬态不平衡、漂移、空bin和原始失败照实保留。
- 一次Slurm CPU输入准备（1CPU/2GiB/5分钟）→实际独立GPU job→真实终态后的单次CPU消费。复用正式0.44公共创建器/消费者，无445旧测试重跑；数值和模型生成全部v100 Slurm。

## 共享资源与DFT规则

2026-10-25本轮读取v100为单节点16CPU、调度内存27800MiB、4×V10016GiB，初读无活动job。cpu/gpu分区指向同一节点，不能分别重复计内存。BTO/带电DFT每项最多1GPU、明确CPU/内存，最多3项独立DFT并行；其他GPU任务由Slurm按同节点总资源排队，提交前再次读取状态。输入准备/后处理是有限预算的软件作业。

所有新增实际DFT使用`scf_thr=1e-11`、`time=0`、no-requeue；原生电子/离子与所声明目标量分别记录，不以迭代耗尽标收敛，不自动改参数或重试。BTO的PP/NAO/电子数/带数/k点不可机械复制CZO。Born/Γ数值处理沿`docs/born-gamma-provisional-standard-v001.md`，新材料未做的采样/步长/基组维度保留未验证，不为软件交付自动追加收敛矩阵。
