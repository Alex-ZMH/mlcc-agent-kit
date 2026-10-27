# ABACUS 3.10.1 P5 能力审查

**2026-10-22 21:35后续修订**：以下早期GPU故障/CPU限制为历史状态；私有独立GPU修复构建160及原生167、177/178、180–185已经完成，168数值比较失败仍保留、原因未定。当前固定tag能力审查见[p5-native-response-capability-20261022.md](p5-native-response-capability-20261022.md)，不能把tag结论直接当成recipe补丁逐文件核对。物理依赖勘误：完整Born与Γ非NAC固定胞E=0力常数足以计算离子介电增量；epsilon_infinity仅用于合成总静态介电，NAC不是该离子增量的必需输入。“解析部分”意为非长程非解析项，不等于DFPT。旧文若将epsilon_infinity/NAC列为离子项先决条件，以本修订及[P5合同](p5-v017-integration-contract.md)为准。

版本溯源勘误：公开 `v3.10.1` tag 指向 `f71921fe848659deac8db319cd4311b55b5ad480`；实际 v100 二进制日志报告 `Commit: 4d3cbab`，既有包记录给出完整 revision `4d3cbab83d661a25770eee61ce9275be0bfebe08`。两者不能等同。以下“精确版本/源码”均指固定 v3.10.1 tag 的公开源码基线，不表示已证明该 tag 与当前二进制逐文件一致。conda 构建还包含 recipe patches；安装二进制的精确源码映射尚未证实。所有已开放功能必须另有该安装二进制的原生运行证据；科学/生产资格继续为 false。[官方 tag/release](https://github.com/abacusmodeling/abacus-develop/releases/tag/v3.10.1)

2026-10-22 实测修订：后续代码和原生证据已将当前 MLCC Berry 入口收紧为 **PW、nspin=1、fixed、non-SOC、CPU NSCF**。本文初版下述 nspin=1/2 候选范围由此修订取代；普通 SCF/relax GPU 与 nspin=2 能力不受影响。

v100 GPU NSCF job53 在成功读取 job50 电荷、完成对角化后，进入 `POLARIZATION CALCULATION` 并以 `FAILED/139:0` 退出。精确源码中 `after_scf()` 把 GPU 波函数复制到 CPU 后调用 Berry；`unkdotp_G0()` 使用非 device-aware 的 `recip2real()`，而 GPU FFT 对象未实现这一主机侧接口。这强烈支持 CPU 波函数与 GPU FFT 路径混用为根因，但未取得调试器回溯，不声称定位到确切崩溃指令。

正式 CPU device 分派位于相同 ABACUS 二进制内。已决定创建独立 CPU 工程任务，保留失败任务，复用原 SCF 电荷，仅改变执行设备与 Slurm 资源；不替换引擎、二进制或物理方法。CPU 原生正例通过前仍不得认定 Berry 可用，GPU 路径不得随 CPU 成功升级资格。

精确源码依据：[KS PW 调用处](https://github.com/deepmodeling/abacus-develop/blob/v3.10.1/source/module_esolver/esolver_ks_pw.cpp)、[Berry overlap](https://github.com/deepmodeling/abacus-develop/blob/v3.10.1/source/module_io/unk_overlap_pw.cpp)、[PW transform](https://github.com/deepmodeling/abacus-develop/blob/v3.10.1/source/module_basis/module_pw/pw_transform_k.cpp)、[CUDA FFT](https://github.com/deepmodeling/abacus-develop/blob/v3.10.1/source/module_basis/module_pw/module_fft/fft_cuda.h)、[设备分派](https://github.com/deepmodeling/abacus-develop/blob/v3.10.1/source/module_esolver/esolver.cpp)。nspin=2 使用单一占据带数的限制见本版 [开发合同](system-contracts-v0100.md)。

**审查版本：** v0.1（2026-10-22）  
**范围：** P5 极化、有限电场、Born 电荷、介电张量和 DFPT 的能力边界  
**执行约束：** 只读检查；没有修改现有源代码、配置或任务，也没有启动 ABACUS/Slurm 数值作业。

## 1. 结论先行

v100 上安装的二进制确实是 ABACUS `v3.10.1`，构建记录为
`cuda_mpi_mpich_hb252b04_303`，运行日志中的源码提交为 `4d3cbab`。在该精确版本的
官方源码和文档中，可以确认以下三层事实：

| P5 能力 | 3.10.1 的版本级证据 | 原生输入/输出是否已确认 | MLCC 当前资格 |
|---|---|---|---|
| PW Berry-phase 极化 | 有 `Berry_phase.md`、PW 示例和 `berryphase.cpp` | 输入流程和 `running_nscf.log` 输出格式已确认 | 未做本机数值资格，不能用于生产结果 |
| saw-like 有限电场 | 有 `electric_field` 示例、`efield.cpp` 和输入文档 | PW 输入字段、`E_efield` 输出和 slab 边界限制已确认 | 只可作为 slab/表面专用候选；不等于体相有限场能力 |
| Born 电荷 | 精确 v3.10.1 源码树没有专用 Born/DFPT 路径、文档或示例 | 没有可消费的原生结果格式 | 未实现/未资格，禁止伪造输入或补零 |
| `epsilon`/介电张量 | 精确源码树没有晶体介电响应路径；唯一命中是隐式溶剂 `cal_epsilon` | 没有晶体介电输出契约 | 未实现/未资格 |
| DFPT | 精确源码树和文档树未找到 DFPT 实现、输入或示例 | 没有原生输出格式 | 未实现/未资格 |

因此，现有计划中“先核实本机支持方案，缺失时不伪造 DFPT 输入”的原则是正确的，
但 P5.05 需要落成一个更严格的路由结论：当前 ABACUS 3.10.1 可先开发
**Berry 极化输入/解析链**；`efield_flag` 只能进入有真空区和明确势跃迁位置的 slab
分支；Born、`epsilon_infinity`、离子介电和完整静态介电不能因为有 `berry_phase`
或普通力/应力输出就标记为可用。

“源码支持”不代表“数值资格”，也不代表 CaZrO3 或 BaTiO3 已经符合任何器件设计指标。
本审查只冻结版本和接口边界，不能替代后续的同方法、同结构、同赝势的数值验收。

## 2. 证据和版本锁定

### 2.1 v100 安装证据

只读检查得到：

```text
/home/v100/miniforge3/envs/abacus_env/bin/abacus --version
ABACUS version v3.10.1

conda package:
abacus 3.10.1 cuda_mpi_mpich_hb252b04_303

source URL in the package recipe:
https://github.com/deepmodeling/abacus-develop/archive/refs/tags/v3.10.1.tar.gz

source archive SHA256:
06873eba8a4e0bc085177a6580455b28e4b62ea8a18f8afe71a02105756d91a0

package source revision:
4d3cbab83d661a25770eee61ce9275be0bfebe08
```

本地对应记录为：

- `workspace/reports/h1/abacus-version.txt`：v100 二进制版本检查；
- `workspace/reports/h1/abacus-package-metadata.txt`：conda 构建、tag 和源码摘要；
- `workspace/reports/h1/abacus-environment.txt`：ABACUS、MPI 和赝势路径；
- `workspace/reports/h1/capability-matrix-v004.json`：当前项目能力矩阵，Berry、有限场、Born/介电均保持 `not_tested`；
- `workspace/configs/site.v100.json`：站点和调度配置。

`/home/v100/abacus-work/official` 保存了与 3.10.1 二进制一起使用的官方示例和实际
运行输出。其 `005_3BaTiO3/OUT.ABACUS/running_scf.log` 标识为 ABACUS v3.10.1，
证明 PW、Ba/Ti/O 多元素、SCF、力和应力的原生输出格式可以被观察到；该例的
`INPUT` 默认 `berry_phase=0`、`efield_flag=0`，没有产生 P5 极化或有限场结果。

### 2.2 精确 tag 的官方来源

以下链接都固定到 `v3.10.1`，没有使用 `develop` 或 latest 文档：

- [Berry phase 文档](https://github.com/deepmodeling/abacus-develop/blob/v3.10.1/docs/advanced/elec_properties/Berry_phase.md)
- [Berry phase 示例说明](https://github.com/deepmodeling/abacus-develop/blob/v3.10.1/examples/berryphase/README)
- [PW Berry SCF 输入](https://github.com/deepmodeling/abacus-develop/blob/v3.10.1/examples/berryphase/pw_PbTiO3/INPUT-scf)
- [PW Berry NSCF 输入](https://github.com/deepmodeling/abacus-develop/blob/v3.10.1/examples/berryphase/pw_PbTiO3/INPUT-nscf-a)
- [有限电场示例说明](https://github.com/deepmodeling/abacus-develop/blob/v3.10.1/examples/electric_field/README)
- [有限电场 PW 输入](https://github.com/deepmodeling/abacus-develop/blob/v3.10.1/examples/electric_field/Pt-slab/INPUT)
- [3.10.1 输入关键词文档](https://github.com/deepmodeling/abacus-develop/blob/v3.10.1/docs/advanced/input_files/input-main.md)
- [Berry phase 源码](https://github.com/deepmodeling/abacus-develop/blob/v3.10.1/source/module_io/berryphase.cpp)
- [有限电场源码](https://github.com/deepmodeling/abacus-develop/blob/v3.10.1/source/module_elecstate/potentials/efield.cpp)

对 v3.10.1 的递归源码树做了只读路径检索，返回 `truncated=false`、6710 个路径。
与 `born`、`dfpt`、`dielec`、`phonon`、`polar`、`response`、`epsilon` 匹配的路径只有
spin 示例和隐式溶剂 `source/module_hamilt_general/module_surchem/cal_epsilon.cpp` 等
非晶体介电内容，没有晶体 Born/DFPT/介电响应模块、示例或结果格式。这一结论是
“没有找到可直接接入的 3.10.1 原生晶体路线”，不是把其它版本的实现移植到当前版本。

## 3. Berry-phase 极化：可实现，但尚未资格化

### 3.1 3.10.1 的实际输入流程

官方 v3.10.1 Berry 文档和示例给出的流程是两步：

1. **SCF 参考任务**
   - `basis_type pw`；
   - `calculation scf`；
   - `out_chg 1`，保留电荷密度文件。
2. **Berry NSCF 任务**
   - `calculation nscf`；
   - `init_chg file`，读取 SCF 电荷；
   - `berry_phase 1`；
   - `gdir 1`、`2` 或 `3`，分别沿 STRU 的晶格向量 `a1`、`a2`、`a3`；
   - `symmetry -1`，关闭对称性；
   - PW NSCF 的 `pw_diag_thr <= 1e-3`，之后应使用实际收敛检查而不是只信输入值。

`KPT` 网格是任务输入的一部分。官方示例以 `4 4 8 0 0 0` 计算 `gdir=3`，并明确
要求沿极化方向增加 k 点、进行 k 点收敛测试。要得到完整笛卡尔极化向量，必须分别
计算三个晶格方向，再按官方输出中的 re-projection 组合，不能从单个 `gdir` 结果
猜另外两个分量。

官方文档明确说 Berry phase 用于晶体绝缘体的宏观极化，并在 v3.10.1 文档中声明
支持 `nspin=1` 和 `nspin=2`、PW 和 LCAO 两种基组。源码中还存在 `nspin=4` 分支，
但当前 MLCC 适配器明确拒绝 `lspinorb`/`noncolin`，且项目没有对非共线/SOC Berry
结果做资格，所以 P5 planner 当前只能生成 `nspin=1/2, lspinorb=false,
noncolin=false` 的任务。

占据方面，ABACUS 输入文档把 `smearing_method=fixed` 定义为“只适用于非导体”。
因此 P5 Berry 任务必须先由电子结构资格确认绝缘性，再使用固定占据；不能把
Ni、金属化缺陷态或金属/陶瓷界面超胞直接送入体相 Berry 公式。

### 3.2 原生输出格式和科学语义

Berry 结果写入 `OUT.<suffix>/running_nscf.log`，日志包含：

```text
POLARIZATION CALCULATION
VALUES OF POLARIZATION
The Ionic Phase: ...
Electronic Phase: ...
P = ... (mod ...) (...) (e/Omega).bohr
P = ... (mod ...) (...) e/bohr^2
P = ... (mod ...) (...) C/m^2
```

极化是多值量，官方文档明确给出 modulo quantum `e R / V_cell`。结果卡必须保留
原始 ionic/electronic phase、总值、modulo 值、方向、晶格和单位；P5 后处理要在
连续参考路径上做 branch unwrapping，输出极化差 `ΔP`，不能把两次主值直接相减。
单次 Berry 输出的 `P` 不能自动称为自发极化，也不能自动得到 `epsilon`、Born 或
小信号 `dD/dE`。

### 3.3 当前 MLCC 状态

现有 `mlcc-agent/src/mlcc/abacus.py`：

- `_input_text()` 只生成 SCF/relax 的 PW 输入、力/应力开关和占据设置，不生成
  `out_chg`、`init_chg`、`berry_phase`、`gdir`、`symmetry=-1` 或 `pw_diag_thr`；
- `parse_abacus_outputs()` 只解析能量、力、应力、电子/离子收敛、磁矩和结构，
  没有 `POLARIZATION CALCULATION` 解析器；
- `AbacusResult` 没有极化、phase branch、极化量子或响应方向字段；
- 当前 `AbacusMethod.validate()` 仍要求显式 `lspinorb=false`、`noncolin=false`。

所以当前状态应写成：**版本级 Berry 输入/输出契约已确认，MLCC P5 生产适配器未实现，
真实 Berry 数值资格未通过。**

## 4. 有限电场：输入存在，但只适用于明确的 slab 边界

### 4.1 3.10.1 的能力是什么

v3.10.1 官方 `electric_field` 示例和 `efield.cpp` 实现的是一个加入裸离子势的
**saw-like potential**。基本字段为：

```text
efield_flag    1
efield_dir     0|1|2
efield_pos_max  0 <= value < 1
efield_pos_dec  0 < value < 1
efield_amp      value in a.u.
```

`efield_dir` 表示与倒格矢 `b1/b2/b3` 平行的方向，不是简单的笛卡尔 x/y/z 标签。
`efield_amp` 的单位为原子单位，v3.10.1 文档给出
`1 a.u. = 51.4220632 * 10^10 V/m`。原生代码和示例输出可见：

- 日志 marker：`Adding external electric field`；
- 幅值 marker：`Amplitute of Efield (Hartree)`；
- 能量项：`E_efield`，同时保留 Rydberg/eV 能量表；
- 电场势和其斜率变化位置由 `efield_pos_max`、`efield_pos_dec` 决定。

该功能在官方示例中同时宣称 PW/LCAO 可用，但输入文档明确要求仅用于 slab geometry，
并且势的 discontinuity 必须落在 empty space；斜率改变位置不在真空会产生非物理力。
这不是对三维周期体相施加均匀宏观电场的通用 DFPT/有限场接口。

### 4.2 对 MLCC P5 的限制

CaZrO3 和 BaTiO3 的体相介电任务不能仅设置 `efield_flag=1` 就称为有限电场介电
计算。若未来确实要建 slab/电极/真空任务，planner 必须同时记录：

- slab 的法向、真空厚度和势跃迁所在 fractional 区间；
- `efield_dir` 与 reciprocal-vector 的关系；
- 原子力是否受场势影响，是否有 dipole correction；
- 场幅的原子单位和换算后的 V/m；
- `E_efield`、总能量、力、应力和场开关的同一方法来源。

对当前 P5 体相路线，`finite_electric_field_bulk` 应保持 `not_implemented`，直到
找到并资格化适用于三维周期体相的明确方法；不能把 slab example 的输出转移到
体相 CZO/BTO。

## 5. Born、epsilon 和 DFPT：当前禁止伪造路线

### 5.1 审查结果

在精确 `v3.10.1` 的 GitHub 树中，没有名为 Born、DFPT、晶体 dielectric、phonon
response 或 polarization response 的模块、输入示例或结果文档。树中命中的
`cal_epsilon.cpp` 位于 `module_hamilt_general/module_surchem`，属于隐式溶剂
介电计算，不能当成固体 `epsilon_infinity` 或 DFPT 介电张量。

因此当前不能合法生成以下假输入或假结果：

- `born_charge`、`epsilon_infinity` 或 `dfpt` 等未被 3.10.1 证实的关键词；
- 从普通 `TOTAL-STRESS`、力或 Berry `P` 反推完整 Born/介电而不记录有限差分路径；
- 以 P7 力常数缺失时的零矩阵补出离子介电；
- 以 VASP 或其它版本输出混入 ABACUS 3.10.1 的方法集。

本审查的状态是 **native crystalline Born/epsilon/DFPT route = unavailable for the
current qualified interface**。如果后续从 ABACUS 上游补充了同版本的隐藏模块或
明确 patch，必须新增版本、源码 commit、输入、输出和数值资格证据，不能仅凭文档
名称或其它版本的 latest 页面放行。

### 5.2 仍可开发的后续响应路线

在没有 DFPT 的前提下，可以设计两条显式、可审计的后续路线，但都不应在本阶段标记
生产资格：

1. **Berry 有限差分路线**：沿同一晶胞、同一赝势、同一 k/basis 方法，生成连续的
   原子位移或应变路径，逐点做 Berry P；对 P 做 branch tracking 后，用 `ΔP/Δu`
   得到候选响应。若命名为 Born 有效电荷，必须显式按
   `Z*_{αβ}=Ω/e · ∂P_α/∂u_{κβ}` 转换，保存体积、位移单位、原子索引和张量方向；
   不能把 `ΔP/Δu` 这个带单位的斜率直接写成无量纲 Born 电荷。用 `ΔP/Δη` 得到
   候选极化-应变响应时也要记录工程应变/张量约定。每个差分必须绑定参考结构、
   位移/应变定义、步长收敛、SCF/NSCF 收敛和 phase branch。
   这不是 DFPT，且未弛豫与弛豫几何分别对应 clamped-ion 和 relaxed response，
   不能混称。
2. **P7 力常数交接路线**：在已有可资格化 Born 和电子介电数据后，用同一模型、
   atom order、单位和方法集，将力常数与非解析修正交给 P7，得到离子响应。没有
   Born 或 `epsilon_infinity` 时只能输出未修正声子/力常数诊断，不能输出完整离子
   介电张量。

若以后通过适用的周期有限场路线得到电子介电，结果应显式使用
`ε_{αβ}=δ_{αβ}+(1/ε0)·∂P_α/∂E_β`，并保存场方向、场单位、边界和拟合区间；
不能用 `P` 的绝对值或单次 Berry 主值代替这个导数。

对于体相电子介电，不能把当前 slab `efield_flag` 作为自动替代；必须先有适用的
周期有限场实现，或把 Berry/其它有限差分路线通过独立数值资格。

## 6. PW、占据、自旋和 k 点的 P5 输入资格

### 6.1 版本级约束

精确 v3.10.1 输入文档给出：

- `basis_type=pw` 是平面波路线；
- `calculation=nscf` 需要已有 charge density；
- `symmetry=-1` 表示不使用对称性，Berry 文档推荐该设置；
- `nspin=1` 为自旋简并，`nspin=2` 为共线自旋，`nspin=4` 为非共线；
- `lspinorb=true` 或 `noncolin=true` 会把 `nspin` 自动设为 4；
- `smearing_method=fixed` 只用于非导体；
- `pw_diag_thr` 对 PW NSCF 应不大于 `1e-3`，但它只是输入候选，仍需实际电子收敛。

### 6.2 项目接口的保守资格

P5 planner 的最小固定字段建议为：

```json
{
  "engine": "abacus",
  "engine_version": "3.10.1",
  "basis_type": "pw",
  "calculation": "nscf",
  "init_chg": "file",
  "berry_phase": true,
  "gdir": 1,
  "symmetry": -1,
  "nspin": 1,
  "lspinorb": false,
  "noncolin": false,
  "occupations": "fixed",
  "kpoints": [4, 4, 8],
  "kpoint_shift": [0, 0, 0],
  "pw_diag_thr": 1.0e-10
}
```

这里的 `kpoints` 和 `pw_diag_thr` 只是规划例子，不是普适精度值。实际值必须来自
方法集和收敛研究；对 `gdir=1/2/3` 应有方向对应的网格和独立收敛证据。显式 Gamma
中心 KPT、方法集、赝势、结构和 charge 文件必须通过同一 task lineage 绑定。

当前方法输入检查已经要求显式 `lspinorb=false`、`noncolin=false`，这与当前 PW
适配器一致。若将来开放 SOC/非共线 Berry，必须单独增加 nspin=4 的输入、输出和
科学验证，不可通过删除检查或把 `has_so` 当成数值资格。

## 7. 最小系统接口建议

下面是可以直接纳入系统设计的最小接口层；本审查不实现这些函数。

### 7.1 版本能力门

```text
inspect_abacus_p5_capability(
    *,
    engine_version,
    source_revision,
    requested_route,
) -> CapabilityReport
```

`CapabilityReport` 至少区分：

```text
version_match
source_evidence
input_keywords
native_output_contract
physics_boundary
input_qualification
scientific_qualification
production_qualification
issues[]
```

对当前版本，`berry_phase_pw` 的 `input_keywords` 和 `native_output_contract` 可为
`true`，`scientific_qualification` 保持 `false`；`bulk_finite_field`、`born`、
`epsilon_infinity` 和 `dfpt` 进入 `not_implemented` 或 `evidence_missing`，不能
由版本号自动通过。

### 7.2 Berry 任务规划

```text
plan_berry_polarization(
    model,
    method,
    *,
    reference_task,
    gdir,
    kpoints,
    pw_diag_thr,
    occupation="fixed",
) -> TaskPlan
```

此函数只在以下条件成立时生成任务请求：model 与 reference 的结构/方法/赝势一致、
体系已通过绝缘性和中性检查、`nspin` 属于 1/2、SOC/noncollinear 明确为 false、
SCF charge 文件真实存在、`symmetry=-1` 和方向 KPT 已显式给出。函数应生成 SCF
前置引用和 NSCF Berry 请求，不直接生成极化数值。

### 7.3 Berry 原生解析

```text
parse_berry_phase(task_path, *, source_model, expected) -> PolarizationRecord
```

解析器必须直接读取 `OUT.<suffix>/running_nscf.log`，要求唯一的 native `INPUT`、
`KPT`、`STRU`、method/task identity 和参考 charge 来源。结果至少保存：

```text
schema: mlcc.abacus-polarization.v1
engine/version/method_set/model_id/model_version
gdir / lattice_vector / kpoints / kpoint_shift
ionic_phase / electronic_phase
total_P_e_per_bohr2 / total_P_C_per_m2
modulo_quantum
cartesian_reprojection
source_native_log / source_input / source_kpt / source_stru
electronic_converged / branch_status / numerical_qualification
```

缺少 phase、modulo、方向、单位或 native 日志时阻断；不能从 `result.json` 的任意
`passed=true` 字段恢复 P5 结果。

### 7.4 响应规划

```text
plan_polarization_response(
    reference_model,
    perturbations,
    *,
    route="berry_finite_difference",
    boundary,
    thresholds,
) -> ResponsePlan
```

`route` 必须是显式枚举。当前允许规划 `berry_finite_difference`，但结果资格默认
`awaiting_native_and_numerical_qualification`；`native_dfpt`、`native_born`、
`native_epsilon` 在没有新版本证据前应直接报告 `unsupported_route`，不能生成虚假
ABACUS INPUT。`boundary` 必须区分 bulk periodic、slab/vacuum、electrode/interface，
不能把 slab `efield_*` 字段带入 bulk。

## 8. 对 CZO 和 BTO 验证案例的落地建议

### 8.1 CaZrO3

CaZrO3 仍应作为体系输入、非铁电正常响应和跨模块谱系的验证案例，使用已确认的
相/模型选择。P5 的顺序建议为：

1. 先由 P4 电子任务确认选定 CaZrO3 结构是否为绝缘体、占据是否可用 fixed、
   赝势/方法是否同一版本；不能因材料名称假定带隙。
2. 若满足绝缘条件，走三方向 Berry reference/polarization 输入和 branch 测试。
   非极性态的零自发极化或零极性差可以是有效正常结果，不是设计失败。
3. Born、`epsilon_infinity`、离子和静态介电在当前 3.10.1 路线中保持缺证据；
   后续只能通过 Berry 有限差分或新增已验证的原生路线交付。
4. 400–580 °C 的烧制温区属于后续有限温度/工艺历史输入，不能把一个 0 K Berry
   NSCF 结果命名为该温区的介电响应。高温任务还要保存温度、结构采样和适用范围。

### 8.2 BaTiO3

BaTiO3 用于铁电能力分支和极性参考路径验证：

1. 先固定高温参考相、低温极性相、晶胞基、极化方向和连续路径；不能把官方
   `005_3BaTiO3` 普通 SCF 示例直接当成 Berry 或铁电资格。
2. 每个路径点都要以同一 PBE/赝势/PW 方法生成 SCF charge 和 NSCF Berry 任务，
   进行 branch unwrapping、k 点、PW 对角化阈值和路径步长收敛。
3. 自发极化是参考态与极性态的连续极化差；单点主值、总能量双阱或普通力/应力
   不能独立证明完整铁电介电能力。
4. 800–1350 °C 是烧制工艺条件，后续若研究该温区，需要独立的高温相/结构/统计
   方法；不能从 0 K Berry 结果直接外推 `P(T)`、`D(E)` 或器件 `C(T,V)`。

## 9. 与现有执行计划的修订关系

现有 `docs/MLCC系统详细执行计划书-CaZrO3-BaTiO3-v002.md` 和
`docs/P0-P12-execution-handoff.md` 中 P5.01–P5.13 的关键原则仍然适用：

- 先判断绝缘体/相态和 Berry 适用性；
- 先定义参考态、路径、方向和分支；
- 不把普通 E/F 势当作铁电势；
- 缺 Born/力常数时只交付得到证据支持的子项；
- 非极性 CaZrO3 的正常介电响应不能因没有双阱而被删除；
- 金属 Ni、金属化缺陷态和金属/陶瓷异质超胞不能直接套体相 Berry 公式。

需要把 P5.05 的实现状态明确写成：

```text
Berry phase:      version/source supported; MLCC adapter pending; numerical qualification pending
bulk finite field: not an approved route in ABACUS 3.10.1; slab-only candidate
Born/epsilon/DFPT: no qualified native 3.10.1 route found; do not emit fake inputs
ionic dielectric:  blocked until qualified Born + P7 force constants or an explicitly qualified finite-difference route
production label: false
```

这样既保留了规划中的铁电第二部分，也避免把“能力矩阵中列出任务”误写成当前
系统已经拥有这些科学功能。P4 的普通 SCF/relax/力/应力通过仍不能替代 P5 的
极化、场、Born 或介电资格。

## 10. 下一阶段执行门

P5 的实现顺序建议固定为：

1. **输入适配器**：新增显式 Berry SCF/NSCF 任务类型，写出 `out_chg`、`init_chg`、
   `berry_phase`、`gdir`、`symmetry`、`pw_diag_thr` 和方向 KPT；不改变现有 SCF/relax
   合同。
2. **原生解析器**：只解析 3.10.1 `POLARIZATION CALCULATION` 日志，保留 phase、
   modulo quantum、方向、单位和完整 native source evidence。
3. **输入资格**：以 CZO 绝缘参考和 BTO 参考/极性路径做输入自洽检查；先不提交大规模
   路径计算。
4. **小规模远端验证**：在 v100、ABACUS 专用环境、Slurm 生命周期下，先完成单一
   参考 SCF→NSCF Berry 原生输出，再进行方向/k/阈值收敛；job 状态、native log、
   source identity 和结果卡必须一起保存。
5. **响应路线选择**：只有 Berry 解析和分支测试通过后，才决定是否实现有限差分
   Born/极化-应变；P7 力常数和电子介电依赖必须单向绑定。
6. **介电/铁电资格**：按电子项、离子项、静态/小信号、场/温度/频率范围分别签出，
   不用单个极化值、普通 SCF 收敛或“未发生劣化”替代设计符合性。

本审查完成的是版本和接口边界确认，未完成上述数值作业；因此它不改变当前
`production_qualification=false`，也不阻塞 0.9 的安装/工程主线。

## 11. 本轮检查清单

- [x] v100 二进制只读版本：ABACUS v3.10.1。
- [x] v100 conda 包 recipe：精确 tag `v3.10.1`、源码 SHA、构建标签。
- [x] 精确 v3.10.1 Berry 文档、PW 示例、Berry 源码和输出 marker。
- [x] 精确 v3.10.1 有限场文档、PW slab 示例、`E_efield` 输出和空区限制。
- [x] 精确 v3.10.1 输入文档中的 PW、NSCF、symmetry、spin、occupation、k/对角化约束。
- [x] 精确源码树路径审查：未找到晶体 Born/DFPT/介电响应模块和示例。
- [x] 现有 MLCC 输入写入器和输出解析器审查：P5 输入/输出尚未实现。
- [x] 没有运行 ABACUS 数值计算、没有提交 Slurm 作业、没有改动现有源码/配置/任务。
