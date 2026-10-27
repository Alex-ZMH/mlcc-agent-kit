# MLCC 0.7.0：方法输入资格与公共电子/弹性入口

本轮目标是增加通用系统功能。CaZrO₃ 用于多元素、非磁、固定占据验证，Ni 用于双自旋、展宽和既有应变数据回归；没有展开 CaZrO₃ 或 BaTiO₃ 温度矩阵。最终安装与验收以 [0.7.0 验收记录](../workspace/reports/system-v070/acceptance.json) 为准。

## 1 方法输入资格

新增 `method_inputs.py`、`method_tasks.py` 及 `inspect-upf`、`qualify-method` CLI。原生 UPF 头通过配置中的 SSH 别名读取并保存在 workspace；资格判断重新解析原生片段，不接受可编辑的 passed 标签代替检查。

检查模型元素、元素顺序、资源标识/路径、UPF 版本和 NC/PBE、价电子、配置元数据、scalar/full/has_so、自旋与初始磁矩、非 SOC/共线开关、显式电荷、占据/能带容量、k 网格、数值参数和支持的执行方式。不同元素的 UPF 同名会在同一工作目录覆盖，因此禁止同 basename。科学案例创建 ABACUS 任务必须通过资格门；原工程 fixture 的历史合同保留。

当前适用范围是 ABACUS 3.10.1 PW/PBE/NC、cpu/gpu＋cg、中性、共线非 SOC。支持 nspin=1 fixed/smearing 和 nspin=2 smearing；nspin=2 fixed、SOC/非共线、带电超胞仍待实现。输入一致性检查不能证明赝势精度、截断/k 网格收敛或材料性能合格。

## 2 Ca 赝势兼容性

保留原 Ca.UPF 的 full-relativistic、has_so=true 和 10 个价电子元数据，没有换赝势。显式声明 `abacus_3.10.1_average_j`，计算设置为 `lspinorb=false`、`noncolin=false`。该版本会在非 SOC 路径平均 j 通道；依据为 [ABACUS v3.10.1 官方自旋说明](https://github.com/deepmodeling/abacus-develop/blob/v3.10.1/docs/advanced/scf/spin.md) 及 [版本化源码调查](../workspace/reports/method-qualification/ca-compatibility-investigation-v001.json)。原调查是修改站点配置前的只读快照，其中“只登记 Ni”的描述不代表本轮交付后的站点配置。

随后只执行了一个预先限定的小型兼容性 SCF：`p4-czo-compatibility-scf-v001`，Slurm **job 40**。原生记录为 COMPLETED/0:0、33 秒、10 次电子迭代，Ca/Zr/O 三种 NC 赝势读取成功、160 个价电子，达到指定电子阈值。[真实兼容性验收](../workspace/reports/method-qualification/czo-native-acceptance-v001.json) 与 [任务](../workspace/tasks/p4-czo-compatibility-scf-v001/task.json) 保留。

使用 100 Ry、2×2×2、scf_thr=1e-4、88 bands。scf_thr 是 ABACUS 原生电荷密度误差判据，不是 eV。源模型是未弛豫的 Pnma 20 原子模型；该静态 SCF 不表示烧制温区平衡态，也不完成结构、力、应力、介电或缺陷精度资格。

## 3 公共电子功能

`electronic.py` 从同一任务的 INPUT/KPT、method、result、原生运行日志、istate.info 和 kpoints 提取数据。核对模型 ID/版本、方法/任务/作业归属、COMPLETED/0:0、电子收敛、均匀 Gamma 零偏移网格的完整唯一坐标、能级数、占据及电子总数。

- NSPIN=1 的原生占据包含 k 权重和双自旋容量；NSPIN=2 有两个显式通道。返回原生加权占据与归一化占据，电子数同时与日志 AUTOSET、赝势元数据相符。
- fixed 整数满/空占据只给 sampled-mesh KS gap、VBM/CBM 及位置；有限展宽返回 gap=null。未实现路径能带、不可约网格、PDOS、基本带隙校正或精度资格。
- Gaussian DOS 的网格和 sigma 都由调用者显式给出，输出 states/eV/cell、窗口积分和态数误差，并携带父任务、方法、模型和能量参考。sigma 是后处理标准差，不是晶格温度。
- job40 检查得到 160 个电子、88 bands、8 k 点，DOS 总态数 176；job37 得到 72.0000012 个电子、双自旋 56 bands、8 k 点，DOS 总态数 112。这些数值用于验证解析/归一化，不作为材料设计结论。

输出写入新报告，不修改历史 task/result。原生 EFERMI 仍是所用方法的内部能量参考，尚未建立带电缺陷形成能所需的 VBM、势对齐、化学势和修正合同。

## 4 公共弹性功能的当前范围

`elastic.py` 提供六分量应变模型、请求规划和已回传任务分析门。采用工程 Voigt 顺序 xx/yy/zz/yz/xz/xy，非对角小应变为 gamma/2，F=I+epsilon，行向量晶格为 cell′=cell·Fᵀ；保留分数坐标和 atom_id。每个幅值是六方向正负扰动加一个参考态；当前只支持静态 clamped-ion 固定分数坐标 SCF。

安装版验收生成 CaZrO₃ 的 **13 份本地原生输入**，检查剪切约定、晶格、分数坐标和原子身份；没有传输或提交这些任务。分析入口检查模型/方法/原生来源、应变及完整 F、原生 STRU/最终静态结构、应力单位与日志一致性、正负配对、矩阵秩和方向覆盖。

现有 Ni jobs38/37/39 只有各向同性体积应变，秩为 1；原预设应力标定误差最小约 6.3555 GPa，超过 1 GPa，继续判失败。六方向覆盖本身也不能代替剪切/完整张量的物理标定。**本版完整张量应力标定证据生产者尚未实现，合格 Cij 保持 null。** 分析会写出阻断原因并返回非零退出码，而不是输出零矩阵或借用文献数值。

因此，本轮完成的是弹性输入/分析门切片，不是完整弹性科学执行器。下一切片应实现一般应变能量导数与应力分量的标定证据合同，再接通经过资格约束的 Cij 拟合、残余应力/线性范围与精度检查；是否运行新的数值验证任务须按当时明确范围决定，不能自动升精度重算。

## 5 安装、验收与后续

Bundle 保持 `matterai.bundle.v2`、四项 Skill 和七个 MCP 生命周期工具。新增领域功能通过 Python/CLI 调用，科学数据、原生文件和报告仍在 workspace。使用原版 MatterAI 安装器安装新版本，旧 0.6.1 与历史数值任务保留；通过已安装源码、原版非桌面宿主和真实 stdio MCP 验证。

验收包含全套测试、安装版方法/Ca 原生证据、电子/DOS/13 份弹性输入与真实失败标定阻断、历史 Study/Result 合同回归，以及原版宿主到 MCP 的实际调用。详细计数和命令见 [最终记录](../workspace/reports/system-v070/acceptance.json)、[公共功能验收](../workspace/reports/system-v070/public/acceptance.json)。

H1 与生产引擎切换保持未完成。缺陷形成/结合能、化学势、费米能级与带电修正继续保留在原计划；四性质、铁电第二部分、势资格与 LAMMPS 仍逐项推进。BaTiO₃ 保留用户温区及未决相/组成边界，没有自行选相。无产品规格时 design_assessment=not_assessed。
