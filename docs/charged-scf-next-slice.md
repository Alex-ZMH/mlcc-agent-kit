# 带电 SCF 数据生产：下一最小切片

2026-10-22。**14:00更新：0.10.0已安装、验收并启用；真实GPU带电SCF和本实验局部E/F加密通过，材料及形成能生产资格未授予。** 实现扩展既有ABACUS方法/创建/解析路径，没有新增执行器。原始缺口表保留为实现前对照。

## 当前实现与证据

- 顶层`net_charge`为规范q输入，正q移走电子；生成`nelec=0`和`nelec_delta=-q`。模型q/方法q必须一致；带电工程fixture也必须通过所选原生UPF头的输入资格检查。
- `prepare_abacus`接受显式输入资格报告后才写带电输入，要求正偶数目标电子数和足够带数；当前仅非SOC、nspin1、fixed、固定胞SCF。拒绝带电relax/应变/Berry，不自动调参、改变自旋或开gate。
- `validate_charged_scf_electrons`在写结果前复用电子解析器检查中性AUTOSET数、nelec_delta、nelec now、原生k网格与占据积分，并绑定INPUT/方法。中性原生数据不能仅改标签成为带电正例；被修改的job40副本只用于负测试。
- 带电原始结果保留`raw_charged_scf_unqualified`，数值/科学/生产资格false。弹性/声子/中性缺陷原生输入合同继续拒绝非中性及电荷覆盖；工作流不接受带电任务作为合格科学依赖。
- v100 job71：FAILED/1:0，84项通过、5项失败，原因是重构漏接占据容量变量及单元格式电子数旧值；没有DFT。修复后job72：COMPLETED/0:0，电子解析20项、中性消费者7项、工作流1项通过。输入模块已通过的部分没有重复重跑；原失败记录保留。
- 真实GPU任务75/76/77/80均COMPLETED/0:0，time=UNLIMITED，原生154→152电子数及电子收敛通过；86使用0.10安装副本验收四项真实任务和5项受影响检查。100→120Ry/222和333→444满足1meV/atom、0.02eV/Å。原78的222→333失败保留，444为审查后的显式单点加密，无旧DFT重算。0.10已启用，0.9冻结目录保留。CPU/GPU无限时与原生收敛约束继续有效。

证据：[软件切片账本](../workspace/reports/charged-scf-v002/execution-ledger.md)、[真实实验协议](charged-scf-native-experiment-v001.md)、[安装版原生验收](../workspace/reports/system-v0100/installed-charged-86/acceptance.json)。下一步接同方法host/defect/reference及所需参考数据，保留下列科学边界。

## 实现前代码缺口（历史对照）

| 位置 | 当前行为 | 必要修改 |
| --- | --- | --- |
| `model_derivatives.derive_defect_model` | 已保存显式整数q和计量/谱系 | 保留调用方选择，不自动造缺陷或选电荷态 |
| `abacus_tasks.create_abacus_task` | 非零派生q直接拒绝 | 只为显式通过新方法合同的固定胞SCF开放；保留模型q/方法q一致性和Study绑定 |
| `method_inputs.qualify_method_inputs` / `method_tasks.check_method_configuration` | UPF原生价电子及占据/带数检查已有，但只放行net_charge=0 | 分别计算Nneutral、Ntarget=Nneutral−q；校验q与delta符号、整数性、正电子数及占据容量 |
| `abacus.AbacusMethod` / `_input_text` / `prepare_abacus` | 未写nelec/nelec_delta/nupdown | 首切片写明确nelec=0与nelec_delta=−q；保持未请求带电时的中性行为；保存方法与原生输入身份 |
| `electronic._declared_electron_count` 与原生日志/占据读取 | 当前只核对中性价电子数 | 分开报告中性、请求目标、原生日志和占据积分电子数，核对三方一致 |
| 原生方法一致性检查，包括 `elastic._native_input_compatibility` | 未绑定电子数调整参数 | 将这些参数加入方法/INPUT比较；本切片不开放带电弹性分析 |
| `defect_thermodynamics.neutral_formation_from_tasks` | 非零q拒绝 | 继续拒绝，不因SCF能量可读而放行带电形成能 |

## 原生参数与首切片边界

官方v3.10.1的 [`cal_nelec`](https://github.com/deepmodeling/abacus-develop/blob/v3.10.1/source/module_elecstate/cal_nelec_nband.cpp) 先在nelec=0时求赝势中性价电子总数，再加nelec_delta。因此MLCC的“正q移走电子”对应delta=−q，不能把q直接写成ABACUS关键词。

首切片限制为PW、非SOC、nspin=1、fixed、目标电子数为正偶整数、固定胞SCF；不自动增大nbands或改变占据/自旋。不引入nupdown约束，不开启gate_flag。当中性电子数为偶数时，q=+1会留下奇数电子，必须拒绝，不能靠增加带数修复。原生 [`Occupy::iweights`](https://github.com/deepmodeling/abacus-develop/blob/v3.10.1/source/module_elecstate/occupy.cpp) 的双重简并固定占据条件支持此限制。奇电子/自旋分配属于后续明确合同。

当前已安装二进制日志commit为4d3cbab，公开tag为f71921fe，recipe带6760/6772补丁；这些公开源码只能提供版本级依据，不能代替安装副本的原生验证。

## 结果与验收

结果只输出原生总能量及能量定义、SCF收敛、Nneutral/Ntarget/native electron count、q/delta、占据/自旋、方法/模型/Slurm来源，状态为 `raw_charged_scf_unqualified`，数值/科学/生产资格均为false。不生成FNV/eFNV数值、VBM参考或带电形成能。

实现后只检查新合同和受影响中性行为。真实GPU小任务须先声明显式结构/q、参数、允许资源和目标观测；保存安装版INPUT回显、`AUTOSET number of electrons`及调整后电子数标记、占据积分、总能量、原生job ID和终态。未定义实验前不提交计算；不为合同测试扩大材料/电荷/温度矩阵。现有兼容参数不能充当生产收敛依据。

## 保留的科学缺口

[`H_Hartree_pw`](https://github.com/deepmodeling/abacus-develop/blob/v3.10.1/source/module_elecstate/potentials/H_Hartree_pw.cpp)省略库仑G=0项；[`H_Ewald_pw`](https://github.com/deepmodeling/abacus-develop/blob/v3.10.1/source/module_hamilt_general/module_ewald/H_Ewald_pw.cpp)处理离子Ewald项。仅识别这些代码不能认证本项目带电总能量的背景/参考约定与有限尺寸修正。特定slab的 [`gatefield`](https://github.com/deepmodeling/abacus-develop/blob/v3.10.1/source/module_elecstate/potentials/gatefield.cpp)平板补偿不得自动用于三维体相缺陷。

带电形成能仍依赖同方法宿主/化学势、VBM与费米能级参考、介电屏蔽、局域/远场势、修正方法及尺寸/弛豫误差。Berry、声子及LAMMPS的带电拒绝门继续保留。本合同不将这些科学缺口标完成。
