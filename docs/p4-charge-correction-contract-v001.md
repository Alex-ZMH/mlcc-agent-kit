# P4 标量 FNV 与带电形成能消费合同

本路径使用 `pymatgen-analysis-defects==2026.3.20` 的发布实现。后端来源和具体参数保存在结果中。其接口为标量 FNV；不平均介电张量，不声明为各向异性 eFNV。

## 公共入口

```text
mlcc charge-correction --request REQUEST.json --output CORRECTION.json
mlcc charged-formation --request REQUEST.json --output FORMATION.json
mlcc charge-transitions --request REQUEST.json --output TRANSITIONS.json
mlcc deliver-properties --study STUDY.json --charge-correction CORRECTION.json --output DELIVERY.json
mlcc deliver-properties --study STUDY.json --charged-formation FORMATION.json --output DELIVERY.json
mlcc deliver-properties --study HOST_STUDY.json --charge-transitions TRANSITIONS.json --output DELIVERY.json
```

所有数值处理与上述验收均在配置站点 Slurm 执行。客户端负责编辑、传输和查看结果。输出使用新文件；不存在的已指定文件保留原始错误。明确缺失的输入写 `null`，结果保留 `missing`。

## 修正输入

请求 schema 为 `mlcc.charge-correction-request.v1`，包含 `correction_id`、`host_electronic_path`、`defect_electronic_path`、`descriptor_path`、`host_potential_path`、`defect_potential_path`、`parameters`。路径相对请求文件解析；潜势或参数尚缺时对应字段为 `null`。

`parameters` 明确提供：

- `q`：整数，正值表示移除电子，必须等于缺陷来源电荷。
- `defect_frac_coords`：缺陷位置，三个分数坐标，范围 `[0,1)`，不自动找缺陷。
- `dielectric`：`value` 为正标量，`unit="dimensionless"`，`source` 为明确来源。
- `q_model`：`beta`、`gamma`（`unit="Bohr"`）和 `expnorm`，不隐式选择模型参数。
- `integration`：`energy_cutoff_eV`、`mad_tol`、`step`。后两项原样传入发布后端，保留后端的原子单位积分约定与原始收敛错误。
- `sampling`：`policy="midpoint_after_defect_shift"`、`axes=[0,1,2]`、`width_angstrom`。窗口按已声明的后端中点策略取样，结果保存实际半开索引、各轴势差与模型势。

ABACUS 入口复用已绑定的 `mlcc.abacus-electrostatic-potential.v1`。只读原生局域离子加 Hartree 的电子势能，按既有常数从 Ry/Bohr 转到 eV/Å；保持 z 最快的网格顺序。当前接收原生零起点周期网格，坐标为 `i*L/N`，不重复周期端点，不重采样。原子映射、模型、任务、Study、方法和原生 job 绑定复用既有检查。

结果 `mlcc.charge-correction.v1` 保留原始引用和输入；`calculation` 为 `mlcc.scalar-fnv.v1` 或 `null`。计算项包括图像电荷能、各轴和平均对齐位移、电荷乘数、对齐能及总能：

```text
short = Vdefect - Vhost - Vmodel
alignment_energy = q * mean_axis(mean_window(short))
correction_total = image_charge_energy + alignment_energy
```

不能把既有 `potential-alignment` 的任意区域原始势差另加到本结果。旧诊断接口保持其原有含义。

## 形成能与转变能级

`mlcc.charged-formation-request.v1` 包含 `formation_id`、`correction_path`、`chemical_delivery_path`、`ef_grid_eV`。化学势来自已保存的 `mlcc.chemical-reference-delivery.v1`，绑定同一宿主任务、方法、能量定义和原始 VBM；数学记录只与明确数学记录配对。缺少修正、化学势、VBM 或 EF 时 `formation=null`。

完整输入直接调用既有 `formation_energy_terms`。图像项与 FNV 对齐项只加入一次，VBM 使用宿主原始值，不再叠加区域诊断移位。

`mlcc.charge-transition-request.v1` 包含 `transition_id`、`formation_paths`（记录名到形成能产品路径）和显式 `ef_interval_eV=[下限,上限]`。绑定共同宿主、方法、化学势点及来源、VBM、同一缺陷操作/组分变化后，直接调用已在 job426 验收的 `charge_transition_envelope`。不拟合采样曲线，不推断带隙，不重写下包络算法；任一输入缺失即保留整个集合的 `missing`。

Study 交付保存完整产品、原始 job、路径和状态。单个修正/形成能绑定其缺陷 Study；跨电荷态集合绑定共同宿主 Study。软件验收进度和原始材料状态分开记录。

## 证据与边界

本轮复用 host205 与 job209/210 的既有来源，实际缺陷势仍缺失，不新增 DFT、MD 或训练。公开 GaN 的 VASP LOCPOT 仅为外部数值参考，不进入 ABACUS 原生标签。软件格点夹具明确标为 `software_contract_only`。执行记录位于 `workspace/reports/charge-correction-v001`；版本启用由主线发布验收决定。

发布源：[Freysoldt 实现](https://github.com/materialsproject/pymatgen-analysis-defects/blob/v2026.3.20/pymatgen/analysis/defects/corrections/freysoldt.py)、[官方对照数据说明](https://materialsproject.github.io/pymatgen-analysis-defects/content/freysoldt-correction/)、[PyPI 2026.3.20](https://pypi.org/project/pymatgen-analysis-defects/2026.3.20/)。许可证为 BSD-3-Clause-LBNL，参考文件保留其原始来源。
