---
name: run-mlcc-dft
description: 以 ABACUS 为 MLCC 默认生产 DFT 引擎，保留用户明确要求的 VASP 对照与执行链；定义任务、MPI 环境、物理对照与一致的生产标注，不自动回退或混用引擎。
---

# ABACUS 生产 DFT 与 VASP 显式对照

公网调用先走[统一操作入口](../references/public-operations.md)；统一入口支持宿主绑定任务的完整生命周期，DFT 方法、引擎和科学资格仍按本 Skill 的显式配置与边界处理。生产默认 `engine=abacus`；只有用户明确指定 VASP 时才使用 `engine=vasp`，不自动 fallback、不跨方法混用原始标签。

创建任务前，先调用 `mlcc_describe_dft_resources(elements?)`：省略 `elements` 时查看运行时周期表摘要，
再传入模型所需元素读取详情；摘要若显示 118 项，只表示目录检查范围，不表示 118 项均可用。
任务只引用详情返回的已注册 `selected[].pseudopotentials[].id` 与
`selected[].orbitals[].id`，不猜路径或文件名。
LCAO 方法可用 `numerical_orbital_library_id` 绑定轨道详情的 `library_id`，由站点提供配套说明和映射路径。
Og 来源缺失、f-core/f-valence
限制和其他资源状态以目录实际返回为准。随后核对模型、晶相、组成整数计数、占位、电子补偿/电荷、
自旋和目标性质。缺少必要项时一次列出并停在创建前，不编造占位输入或宣称 ready；已记录执行授权
的同一任务不重复索要提交许可。安装资源可用、输入兼容、数值收敛和材料科学资格分别记录，工程开发
不因材料尚未具备生产资格而阻断，也不自动追加收敛矩阵。P4mm 与浓度整数约束必须保留；报告中的
Na/Tm 与对话中的 Ca/Tm 冲突时先澄清，不能擅自替换组成；若 Ca/Na 选择或浓度具体数值缺失，
只追问这些必要输入，不重新申请已有的执行授权。Na/Tm 电子补偿不预判必然金属或 `gap=0`，
也不把 Tm 在计算前固定为“只能 3+”；保留实际 f-core/价电子资源限制，并以原生结果为准。

`create-neutral-defect-pair`以`--method`指定宿主方法，可用`--defect-method`显式指定包含新增元素资源的变体方法。共同元素的PP/NAO与共同物理设置经共享领域函数比较，新增元素资源单列；不再要求两侧元素集合完全相同。`--chemical-reference`可省略，省略时只生成未提交的两侧输入，形成能的化学参考保持缺项。创建阶段不提交数值任务，TaskRecord的`scheduler_job_id`仍为null；完成授权后真实执行继续走既有Slurm生命周期。

0.32在计算站点经Slurm用`inspect-nao --method ... --site ... --output NEW.json`生成既有NAO快照。方法显式选择numerical_orbital_library的name/version/functional/pairing_source/pseudopotential_map；读取选择的轨道头、库说明和元素UPF映射，输出供既有qualify-method/create-abacus消费。不扫描、不换资源、不把库声明当NAO原生XC或材料生产资格；保存的原生结果仍绑定原TaskRecord/job，不借用给未执行的新任务。

0.31公共`create-abacus`也接入显式LCAO中性、非SOC、nspin=1/fixed、GPU/cusolver固定胞SCF；方法用basis_type/numerical_orbital_ids/lcao_output和UPF+NAO原生头/库配套快照，站点解析数值轨道路径。保留NUMERICAL_ORBITAL、原子映射、输出请求和复制清单；创建后仍单独prepare/transfer/submit，不隐式运行。NAO头不含XC，PBE依据须记录为库配套声明；不得从gga文件名推断。Gamma/Born/分支不是SCF创建前置，材料资格仍另判。其余LCAO阶段/带电/自旋/solver不在首切片。

固定晶胞离子弛豫通过既有`create-abacus`提交显式`ionic_constraints`，按原子ID列出每个Cartesian自由分量。ABACUS3.10.1新CG的部分坐标冻结仅限正对角轴对齐正交胞，整原子自由/冻结可用于一般固定胞；不自动切换优化器。按原生电子/离子标志、自由分量最大力、固定胞与冻结坐标核对结果；迭代耗尽的最终STRU可能尚未评估，不能晋升。使用`derive-relaxed-structure`把已保存且`geometry_promotable=true`的结果派生为新Model/Study，再以`create-relaxed-scf`接现有SCF/Berry参考创建器。两者只生成产物与输入，保持原子谱系、相/掺杂和原生job来源；不复用relax电荷，不自动提交或建立铁电资格。字段见README，数值操作仍经Slurm。

当前P5公共后处理有`berry-branch-review`、`berry-branch-consume`、`born-charges`、`phonon-gamma`、`ionic-dielectric`及`dielectric`，具体显式参数见Bundle README。所有数值后处理经站点Slurm；复用既有结果，禁止为填写缺项自动追加计算。分支整数建议不是物理授权；外部审阅记录必须绑定原生来源，缺跨位移分支依据则Born缺列。Γ适配仅消费已有P7力常数、同父胞映射和显式来源；完整Born与固定胞E=0无NAC的Γ Hessian可求离子介电增量，电子项缺失只使总量null。科学资格与软件输入完整性分别记录。

本版有 Slurm CLI 与 stdio MCP：`mlcc_list_tasks` 和 `mlcc_{prepare,transfer,submit,query,cancel,collect}_calculation`。先读取项目站点配置和平台实际工具清单/权限，不把 manifest 声明当作平台已授权。建模、VASP 与 ABACUS 输入/解析使用同一 Python 包。ABACUS 当前直接适配 3.10.1 的显式 PW/PBE/NC、共线非 SOC、固定胞 SCF/离子弛豫；原始应力保留 kBar 与 GPa，不冒称已经完成符号/截断标定或生产方法资格。

通过 `mlcc inspect-upf --method <方法> --site <站点> --output <新快照>` 读取选定资源头，方法配置中的 input_qualification.header_snapshot 引用该原生快照。`mlcc qualify-method --model <模型目录> --method <方法> --site <站点> --output <新报告>` 检查元素/元数据、价电子、PBE/NC、自旋、相对论策略、占据/能带和显式数值输入；科学案例创建任务时重算此门。冻结0.9.0支持中性、nspin=1 fixed/smearing与nspin=2 smearing；0.10.0候选新增下述限定带电SCF。SOC/非共线/nspin=2 fixed仍拒绝。完全相对论NC的非SOC使用需显式声明版本化j通道平均及依据，保留原头的full/has_so；不能自动换赝势或引擎。资格失败返回原始问题，不自动修复或重跑。

0.10.0候选带电SCF使用顶层`net_charge=q`，正q移走电子，写入`nelec=0`、`nelec_delta=-q`。必须绑定模型电荷及原生UPF输入资格，限PW、非SOC、nspin=1、fixed、固定胞SCF，目标电子数为正偶数且带数足够；不自动改带数、自旋或开启gate。解析分别核对原生AUTOSET中性数、nelec_delta、nelec now与加权占据。候选软件检查通过，真实带电原生正例仍缺；结果仅为`raw_charged_scf_unqualified`，数值/科学/生产资格均false。带电relax、Berry、弹性、声子、形成能和修正生产链未开放。

所有数值工作在项目配置的远端站点经Slurm执行，本地只编辑、传输控制和查看证据。所有实际DFT（含兼容/诊断）显式请求`time=0`，分区须允许无限时；以声明的原生电子/离子及目标量收敛验收，耗尽迭代不等于收敛。CPU/GPU、内存、体系规模保持显式，不以开发进度取消正常DFT。

执行分 prepare、transfer、submit、query、cancel、collect；数值任务使用项目配置的 Slurm，记录真实 job ID、模型版本、engine/method_set、资源、原生状态、退出码和日志。SSH 仅做控制/传输，连接结束不是作业结束。Slurm 不可用时报告故障，不回退直接进程；COMPLETED/退出 0 不等于电子/离子收敛。基础 Slurm 安装也不等于 MPI、sacct 或 VASP 链已经通过。

当前入口为 `mlcc <动作> --site <私有站点JSON> --task <任务JSON>`。先完成输入传输再提交；已有提交记录的任务不重提。查询保留 scontrol 原始终态，收集仅包含任务列明的产物。Windows 生成的 VASP 输入和 batch script 明确使用 LF。修正失败后使用新任务号并关联原始错误。

先用一个标明用途的小模型按当前选择的引擎执行弛豫/SCF，默认使用 ABACUS；只有用户明确要求 VASP 时才执行 VASP。回读结构、E/F/应力和收敛证据。VASP 的 POTCAR 在授权计算站组装，不写入能力包或公开产物。工程 fixture 不代表用户选相确认。

只有用户明确要求 VASP 对照时，才用完全相同几何分别执行 VASP 与 ABACUS，并核对泛函、自旋、价电子范围、色散、k 密度、基组和约束。比较相对能、位移力、应变应力、结构等任务相关量，不跨赝势比较裸总能。统一单位、应力符号/张量顺序和原子排序。

VASP 与 ABACUS 可用不同 MPI 实现，分别显式设置环境。不能把另一程序环境的 mpirun 或交互 .bashrc 当成可移植启动方法。

0.10.0 的 Berry 候选 CLI 为 `create-berry-reference --study --model --method --site --request`、`create-berry-nscf --reference-task --method --site --request` 和 `parse-berry --task`；创建只写输入，仍须经过同一 Slurm prepare/transfer/submit/query/collect 生命周期。参考 SCF 显式输出 `out_chg=1`，NSCF 从真实参考电荷读取 `init_chg=file`，并保留 `berry_phase=1`、显式方向和对角化阈值。该候选严格限定 ABACUS 3.10.1 PW、nspin=1、fixed、非 SOC、共线和 `symmetry=-1`，Berry nspin=2 不放行；普通 SCF/relax 的自旋能力不受影响。单方向解析只返回未解缠分支，科学/数值/生产资格均为 false，不声称 Born、DFPT、有限场或介电结果。

CPU小规模Berry原生证据可复用；独立GPU修复构建已完成原生执行和解析链，但GPU/CPU数值比较失败仍未归因，不授予科学资格。支持GPU时继续优先GPU，不自动切CPU、不重复既有CPU兼容任务。输入生成、SCF电荷或Slurm COMPLETED本身不构成Berry科学资格。基于实际安装版本逐项验证有限场、Born/介电、SOC/U与力/应力；缺功能明确报告，不假设最新文档适用于本站。生产 DFT 固定以 ABACUS 为默认；用户明确要求的 VASP 结果只作为独立 method/provenance 记录，不自动替代 ABACUS 或互相混用。训练标签按engine/method_set分开。所有站点路径、赝势和材料选择必须由显式配置提供。

中性缺陷任务对使用 `create-neutral-defect-pair`，完整参数见README。只连接显式宿主/缺陷模型、各自Study、两个SCF请求及同方法化学势来源，不选位点/相/掺杂，不自动提交。带电模型仍不能进入该中性入口。真实计算完成后使用 `neutral-formation` 读取原生任务；输入生成检查不代表形成能已验收。

用当前格式的直接适配器与原始错误；禁止防御性编程、哈希校验、自动重试、自动切引擎、数据补零与内容缓存。物理收敛/基准对照保留。
