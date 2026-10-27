# 0.8.0 系统功能合同与验收边界

本版对应 2026-10-22 的 24 小时开发窗口。交付对象仍是通用 MLCC 系统；CaZrO₃、BaTiO₃ 是验证案例，Ni 是工程 fixture。软件测试、原生数值证据与材料科学资格分别记录。最终安装版验收记录位于 `workspace/reports/system-v080/acceptance.json`，该文件生成并通过前不视为已发布。

## 1 精确扩胞和显式缺陷模型

```text
mlcc derive-supercell --parent <父模型目录> --request <请求.json> --output <新模型目录>
mlcc derive-defect --parent <父模型目录> --request <请求.json> --output <新模型目录>
```

两个请求都要求 `model_id`、`version`，可以提供 `study_id`。新身份不能复用父模型 ID 和版本。目标目录必须不存在；不覆盖父结构或历史模型。

超胞请求提供 `repeat_matrix`：3×3 整数矩阵、正行列式。晶胞约定为 `child_cell = repeat_matrix @ parent_cell`，每个子原子记录新的 `atom_id`、`parent_atom_id` 和整数 `parent_image`；位置满足 `(parent_fractional + parent_image) @ parent_cell`。非对角矩阵也支持。带非零电荷的父模型暂拒绝扩胞，避免隐式改变总电荷。

缺陷请求提供显式整数 `charge_state` 和有序 `operations`，每项只能是：

- `{"kind":"vacancy","atom_id":...}`
- `{"kind":"substitution","atom_id":...,"new_element":...}`
- `{"kind":"interstitial","new_atom_id":...,"element":...,"frac_coords":[...]}`

按稳定 ID 操作，不推断位点、补偿机制或随机分布。幸存原子的 ID 保留；新原子不能重用已删除 ID。记录每步计量和总 `composition_delta`，正数表示加入原子。带电模型可作为结构及电荷请求保存，但 `create-abacus` 会明确拒绝，当前中性执行器不能将其默默按中性计算。

派生后的 `source.cif` 是生成子结构的参考文件，明确标注 `source_structure_role=generated_child_reference`；父原始结构通过 `parent_model` 和 `parent_source_ref` 保留。`model.json`、`dopants.json` 和 `atom-lineage.json` 记录同一派生关系。模型保持 `relaxation_status=not_run` 和 `production_qualified=false`。这不是随机/SQS 系综、MD 势资格或高温平衡模型。

## 2 完整张量应力标定和 Cij

```text
mlcc elastic-plan --model <目录> --amplitudes <h> <2h> --output <新计划.json>
mlcc elastic-calibrate --reference-task <目录> --strained-tasks <24个目录> --thresholds <阈值.json> --output <新标定.json>
mlcc elastic-analyze --reference-task <目录> --strained-tasks <24个目录> --calibration <标定.json> --thresholds <阈值.json> --output <新分析.json>
```

六个工程 Voigt 分量依次为 xx、yy、zz、yz、xz、xy。每方向取 −2h、−h、0、h、2h，共用一个参考态，合计 25 个原生任务。保持分数坐标、原子 ID 和同一方法；规划和分析不提交任务。

应力视为当前晶胞的 Cauchy 张量，采用 `P = det(F) σ F⁻ᵀ`，比较 `(1/V0)dE/dηa` 与 `P:Ha`，工程剪切的 `Ha` 两个非对角元为 1/2。eV/Å³ 转 GPa 因子为 160.21766208。对中心及 ±h 点分别做中心差分；在中心比较 h 与 2h 两种步长导数。每方向至少有一个可辨识信号，零应力参考点允许存在；整组数据只选一个全局 ± 符号。两符号均通过、信号不足或不一致不能授予标定资格。

科学约定依据：ABACUS v3.10.1 的 [stress_pw.cpp](https://github.com/deepmodeling/abacus-develop/blob/v3.10.1/source/module_hamilt_pw/hamilt_pwdft/stress_pw.cpp) 按当前 `ucell.omega` 组织应力贡献并输出 TOTAL-STRESS；有限变形功共轭关系见 [Bower：Work and Energy](https://solidmechanics.org/Text/Chapter2_5/Chapter2_5.php)。源码与连续力学定义支持协议选择，实际符号及数值一致性仍须原生标定。

显式阈值包括：

| 字段 | 用途 |
| --- | --- |
| fractional_tolerance / strain_tolerance | 分数坐标和实际变形梯度一致性 |
| native_stress_asymmetry_GPa | 原生应力张量对称性 |
| calibration_abs_error_GPa / calibration_relative_error | 能量导数与应力做功的误差 |
| calibration_signal_min_GPa | 符号可辨识信号 |
| calibration_fd_consistency_GPa | 两步长中心导数一致性 |
| amplitude_slope_difference_GPa | h 与 2h 的成对应力斜率一致性 |
| reference_stress_GPa | 参考残余应力 |
| linearity_residual_GPa / condition_number_max / asymmetry_GPa | 拟合残差、条件数及 Cij 非对称性 |

这些是每个协议须事先声明的阈值，不是 MLCC 通用生产精度。分析重新读取并核对原生能量、应力、收敛、方法、KPT、STRU、最终结构和来源，再重算 v002 标定，不接受单独的 `passed=true`。旧各向同性标定不能资格化完整张量。Cij 是固定离子分数坐标的 Cauchy 应力增量/工程应变切线；不强制对称化，不宣称 relaxed-ion、有限温度或有限压力热力学弹性张量。当前 Ni 三点数据继续阻断，生产资格保持 false。

## 3 缺陷热力学

```text
mlcc chemical-potential-region --request <请求.json> --output <新区域.json>
mlcc formation-energy --request <请求.json> --output <新分项.json>
mlcc binding-energy --request <请求.json> --output <新结合能.json>
mlcc neutral-formation --host-task <目录> --defect-task <目录> --chemical-point <点.json> --descriptor <派生model.json> --output <新报告.json>
```

`chemical-potential-region` 要求 `elements`、逐元素 `mu_ref`、`physics`、`host`、`competing_phases`，可选 `selected_delta_mu`。每个参考包含来源、engine/version/method_set/energy_definition，元素参考以 eV/atom 给出；相的形成能按其显式化学计量式给出，不能混用每原子与每化学式能量。求解 `Δμi≤0`、宿主等式和竞争相不等式，返回可行性、逐元素坐标界及指定点残差/绝对 μ，不自动挑富氧/贫氧。算法错误保留为错误，不能解释为空稳定区。有限温度来源标签不等于本模块计算了热力学修正；机械外压不等于氧分压。

`formation-energy` JSON 字段与 Python 函数同名：`Edef`、`Ehost`、`deltaN`、`mu`、`q`、`vbm`、`ef_grid`、`correction_terms`。公式为：

`Edef − Ehost − Σ ΔNi μi + q(EVBM + EF) + Ecorr`

q>0 表示移走电子；EF 相对宿主 VBM，以 eV 给出。q=0 不要求 VBM 或 EF。q≠0 要求显式 VBM、EF 网格与修正分项/总和。`potential_alignment_eV` 是已经换算好的能量项，不是待乘 q 的电势差；`image_charge_eV`、`band_filling_eV`、`other_eV` 与它相加必须等于 `total_eV`。不能把内含 alignment 的修正总量再次加上 alignment。这里只核算调用者提供的项，不生产 FNV/eFNV 修正。

`binding-energy` 输入 `formation_records` 与 `stoichiometric_coefficients`。正系数为孤立缺陷/反应物，负系数为复合体/产物；正结合能代表该显式反应有利。检查元素增减及电荷守恒、方法、宿主、μ 与 EF 参考一致，不补入隐含库，不推导 NEB 或速率。

上述三个数值函数输出数学后处理、未科学资格状态。`neutral-formation` 另外复读真实任务，绑定派生模型/父模型和原生方法/能量/结构，只支持相同元素及赝势集合、固定胞 SCF、中性方法。输出 raw 中性形成能；弛豫、尺寸收敛、新元素取代、化学势科学资格和带电方法仍分别待验收。当前尚无真实宿主/缺陷任务对，不能把公式单测写成材料形成能验证通过。

## 4 性质交付与设计适配

```text
mlcc deliver-properties --study <study.json> --tasks <任务目录...> [--targets <指标.json>] --output <新交付.json>
mlcc assess-design --request <请求.json> --output <新评估.json>
```

交付器重新读取真实电子数据，核对 Study/模型归属，输出 `observables` 列表和每项的定义、单位、对象层级、条件、方法及原始文件引用。当前支持均匀网格 KS gap、EF、VBM、CBM 标量；保留静态 0 K 条件，不改标为烧制温度性质。CaZrO₃ job40 的精度未获资格，所以仍是 unqualified。

纯比较器输入两个列表 `requirements` 和 `observables`。需求必须显式给出 `required` 布尔值与 `uncertainty_rule`，观测量必须有数值或 null、不确定度或显式 null、科学状态及来源。仅精确匹配 `observable_id`、definition、object_level、unit、conditions；多个完全匹配项视为歧义，不悄悄择一。

比较支持上限、下限、区间、目标±容差。`nominal` 只按标称值，`whole_interval` 要求整个对称绝对误差区间满足要求。完全在内为 met、完全在外为 not_met、跨边界或缺科学证据为 insufficient_evidence。仅 required 项参与总评。函数消费上游 `qualified` 声明，不负责授予资格；原生电子交付器不会将 SCF 收敛自动升级为精度合格。

没有产品指标时为 not_assessed，不阻塞系统开发。已有设计引用却未提供显式 targets 文件时提示缺失输入。当前没有启用任何产品合格线，数学测试中的数值仅证明比较算法。

## 5 后续开发

下一切片优先接有限位移模型、ABACUS 原生力和 Phonopy 数据桥，并继续铁电分支、LAMMPS/势资格与其余专用性质。BaTiO₃ 的相、结构与其余案例边界保持待选择。H1、生产引擎资格、真实完整弹性张量和缺陷科学验证均不会因本版软件交付自动完成。
