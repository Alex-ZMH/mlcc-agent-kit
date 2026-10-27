# P5 原生响应能力审查（ABACUS 3.10.1）

日期：2026-10-22。范围限定为 MLCC 当前 P5/P7 路线的能力核对；本次未提交 DFT、未构建 ABACUS、未修改上游源码。

## 结论

审查锁定的官方源码副本为：

```text
workspace/reports/berry-gpu-build-v001/source-audit/source-tree/abacus-develop-3.10.1
```

该副本对应 ABACUS v3.10.1 官方 tag 基线（审查记录中的 tag commit 为
`f71921fe848659deac8db319cd4311b55b5ad480`）。v100 conda 包另报告
`4d3cbab83d661a25770eee61ce9275be0bfebe08`；两者不能直接视为同一源码，recipe patch
也没有在本审查中做逐文件映射。因此下述“未发现”结论只针对锁定的 tag 源码、其文档和示例，
不能升级为“实际安装包及所有 recipe patch 均不存在该能力”的结论。

| 能力 | 3.10.1 当前证据 | P5/P7 可交付边界 |
|---|---|---|
| PW、非 SOC、`nspin=1` Berry 极化 | 有输入和原生输出 | 可交付各 `gdir` 的电子/离子/总极化、模量和分支；不是介电常数或 Born 电荷 |
| GPU Berry | job53/61 是历史故障；修复候选 160 后，原生 job167、177/178、180–185 的执行/解析链已完成，但 job168 数值比较未通过，原因未确定 | 保留历史故障、当前数值比较失败和工程资格边界；尚未取得科学生产资格，不能作为 CPU 隐式回退 |
| 体材料均匀有限场 | 无 | `efield_*` 不能用于当前周期体介电响应 |
| `epsilon0_pw`、`epsilon0_choice` 等独立粒子光学输入 | 在该源码、文档和示例中未找到 | 不能声称存在电子介电张量 producer |
| PW DFPT、Born 有效电荷、`epsilon_infinity` | 无对应原生路径/输出证据 | P5 仍未实现 |
| P7 Gamma 力常数 | 有传统位移有限差分软件路径（前提是完整原生力集合） | 可给有限差分力常数和频率；固定胞E=0下其Γ非NAC部分可用于离子增量，方法并非DFPT |
| P7 Gamma 本征矢 | 当前调用明确 `with_eigenvectors=False` | 当前不输出本征矢 |
| Born+固定胞 Gamma 离子介电增量 | 缺可用 Born 与合格的 Gamma 力常数链；`epsilon_infinity`、NAC 不是该增量的数学前置 | 当前不能计算；补齐 `Z` 和 `K` 后可单独给出离子增量 |
| Born+模式分解/总静态介电 | 当前不输出本征矢，且缺 Born；总静态介电还缺 `epsilon_infinity` | 不能计算或宣称完整静态介电 |

## P5：PW/GPU/non-SOC `nspin=1`

当前保守输入契约是 PW、`nspin=1`、固定占据、非 SOC/非共线，关闭对称性（`symmetry=-1`）。典型工程链是：

1. 普通 PW SCF 产生电荷密度；
2. NSCF 从文件读入电荷，设置 `berry_phase=1`，选择 `gdir=1/2/3`；
3. `OUT.<suffix>/running_nscf.log` 输出 Berry phase、模量/分支信息以及总极化，极化单位包含 `C/m^2`。

源码证据：

- `source/module_esolver/esolver_ks_pw.cpp:619-622,694-700`：仅在 NSCF 且 Berry 开启时调用 `Macroscopic_polarization`；
- `source/module_io/berryphase.cpp:402-466,472-562,597-713`：电子 Berry phase、离子相位、模量处理和各 `gdir` 的 `C/m^2` 极化输出；
- `source/module_io/unk_overlap_pw.cpp:16,69,95-104`：Berry overlap 的 `unkdotp_G/unkdotp_G0` 及 reciprocal/real-space 转换路径；这也是现有 GPU 故障单定位的相关路径。

普通 PW SCF/力/应力本身可以运行，但不产生介电张量。GPU Berry 的证据需要分层解释：
job53/61 的 `SIGSEGV` 是历史故障，已由修复候选 160 隔离；其后原生 job167、177/178、180–185
完成了当前执行/解析链，job168 的数值比较仍未通过，原因尚未确定。故当前链路可作为工程集成证据，
但不能据此宣称 Berry 的科学生产资格；也不能把 CPU Berry 当作隐式生产回退。详情见
`docs/berry-gpu-issue-53.md` 及对应 job 报告。

现有 Berry 输出可被 MLCC 的极化/有限位移响应代码消费，但其物理量仍是
`P`（绝对极化、分支和极化量子），不能把 `P` 直接命名为自发极化、介电常数或 Born 电荷。

## 体有限场、独立粒子光学和 DFPT

ABACUS 3.10.1 的电场实现是 slab/surface 的 saw-like 外场：

- `source/module_elecstate/potentials/efield.cpp:31-40,58-111,234-282`：构造偶极势、能量和力项；
- 同一源码副本的 `docs/advanced/input_files/input-main.md:2236-2288`：`efield_flag`、`efield_dir`、`efield_pos_max`、`efield_pos_dec`、`efield_amp` 的输入说明，并明确要求 slab 几何且势的不连续处位于真空区域。

因此它不能作为周期体材料的均匀有限场，当前也没有由 `dP/dE` 形成电子介电张量的原生输出。

在锁定的源码、文档和示例中未发现 `epsilon0_pw`、`epsilon0_choice` 或等价的 PW 独立粒子电子介电 producer。现有
`source/module_hamilt_general/module_surchem/cal_epsilon.cpp:4,9-18` 计算的是隐式溶剂空间介电函数，不是晶体的
`epsilon_infinity`。`source/module_lr/esolver_lrtd_lcao.cpp` 和
`source/module_lr/hamilt_casida.cpp` 属于 LCAO LR-TDDFT/Casida 响应，不能混称为 PW DFPT、Born 或完整静态介电路径。

同一 3.10.1 tag 源码审查中没有 `born`、`dfpt`、晶体 `epsilon_infinity` 或 analytic lattice-response 的原生输入/输出证据。因此当前 P5 应将体有限场、Born、`epsilon_infinity` 和 DFPT 标记为
`unsupported_route`/`evidence_missing`，不能用最新版本文档或其他引擎补写能力。

## P7/Phonopy 对 Gamma 和模式介电的边界

`mlcc-agent/src/mlcc/phonons.py:666-715` 的 `compute_harmonic_qpoints` 调用：

```python
phonon.produce_force_constants(
    calculate_full_force_constants=True,
    fc_calculator="traditional",
    show_drift=False,
)
result = phonon.run_qpoints(q_array.tolist(), with_eigenvectors=False)
```

它可以在请求 `q=[0,0,0]` 时给出 Gamma 的**传统位移有限差分**力常数和频率；这不是DFPT方法。晶格动力学中的analytic部分指非NAC部分，不能据其有限差分来源排除它。当前输出还明确保留 `nac: "not_requested"`、`asr: "not_applied"` 和未裁剪的虚频状态，并没有本征矢。

`mlcc-agent/src/mlcc/phonon_forces.py` 的力集合收集器要求完整的原生 ABACUS 位移力集合；即使软件门通过，当前报告仍将其标为 `assembled_unqualified`、`scientific_qualification=false`、`production_qualification=false`。当前没有 Born 有效电荷或合格的完整力常数链，故 P7 不能提供 Born+模式有效电荷或离子介电贡献。

需要区分两个物理问题。对固定胞、零外场的离子介电增量，完整 Born 张量 `Z` 和 Gamma
力常数矩阵的平移子空间伪逆 `K_SI^+` 足够；在 SI 约定下可写为

```text
Delta_epsilon_ion = e^2 / (epsilon_0 * Omega) * Z * K_SI^+ * Z^T
```

这里的 `K` 是 Gamma 的解析（非长程非解析）部分；“解析”描述长程非解析项的分离，
不等同于 DFPT，有限位移也可以得到这部分力常数。平移零模必须投影/使用伪逆，不能直接
求普通逆。该关系及平移子空间伪逆处理见
[Wu、Vanderbilt 和 Hamann (2005), Eq. (14)](https://arxiv.org/pdf/cond-mat/0501548)，
以及该式后对 acoustic subspace 的说明。

`epsilon_infinity` 只在把离子增量与电子部分合成为总静态介电时需要：
`epsilon_static = epsilon_infinity + Delta_epsilon_ion`（按统一的张量单位约定）。
NAC 也不是上述固定胞离子增量的数学前置；它用于长程非解析修正、LO/TO 分裂和有方向的
`q -> 0` 模式分析。当前缺失 Born 或合格 `K`，所以仍不能交付离子增量；但不能再把
缺失 `epsilon_infinity` 或 NAC 写成该增量本身的阻塞条件。

## 最小可实现后续路径

这不是本次实现范围。若后续要扩展 P5/P7，应保持现有 runner、Study、方法签名和来源链：

1. 在 P7 增加显式的 `with_eigenvectors` 选项，仅在完整真实位移力集合存在时输出 Gamma 本征矢；保留力常数、单位、原子顺序、模型和 Study 来源，不自动施加 ASR/NAC。
2. 继续使用 P5 的显式 Berry 位移 producer/parser，逐点保存 `atom_id`、Cartesian 方向、位移、胞体积、Berry 分支/极化量子和原生任务路径；把 `Delta P/Delta u` 先作为响应导数，不能未经单位换算称为 Born 电荷。
3. 通过 P7 完整的 Gamma 力常数集合得到 `K`，显式保留平移零模投影/伪逆和单位；如需模式分解，再增加本征矢输出。这里不要求把有限位移路径误称为 DFPT analytic producer。
4. 单独增加有明确 ABACUS 版本/原生输出证据的 `epsilon_infinity` producer/parser；不要把 slab `efield_*`、隐式溶剂 `cal_epsilon` 或 LCAO LR-TDDFT 伪装成 PW DFPT。补齐 `Z` 与 `K` 后，可先交付固定胞 `Delta_epsilon_ion`；补齐 `epsilon_infinity` 后才合成总静态介电。若做 LO/TO 或 `q -> 0` 方向分析，再单独记录 NAC、ASR、分支和科学资格。

本报告仅确认软件能力和缺口，不把任何候选材料的数值结果升级为生产材料资格，也不新增 DFT 任务。
