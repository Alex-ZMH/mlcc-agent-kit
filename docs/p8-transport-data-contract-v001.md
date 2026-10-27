# P8 保存能带到 BoltzTraP2：最小合同 v001

状态：固定实现合同；安装 job436 与新增路径 job437 已完成。job437 COMPLETED/0:0（6 秒），15 项新增检查和 4 条公共命令通过。安装发布与版本/计划由主线管理。本轮只消费已有 ABACUS 保存结果，不生成 DFT/MD/训练或材料精度矩阵。

## 固定函数与后端

选用官方发布 `BoltzTraP2==26.3.1`（GPL-3.0-or-later）。调用链固定为 `sphere.get_equivalences → fite.fitde3D → fite.getBTPbands(curvature=False,nworkers=1) → bandlib.BTPDOS(scattering_model="uniform_tau") → fermiintegrals → calc_Onsager_coefficients`。数据载体仅提供 kpoints、ebands、mommat=None 和 get_lattvec，不登记插件，不改后端。固定版本 API 没有 GPU 接口，使用有限 CPU Slurm。

MLCC 单模块 `transport.py` 提供 `read_transport_source(request)`、`calculate_transport(source, parameters)` 和 `build_transport(request_path)`。前者绑定保存电子产品、原 task/result/method/INPUT/STRU.atom-map.json，直接读取 result.final_atoms 的晶格与结构。后两者调用固定后端并保存结果。公共入口 `transport --request <JSON> --output <JSON>`；`deliver-properties --transport <JSON> --study <JSON> --output <JSON>` 只交付已有产品。

## 请求与输入

请求 schema 为 `mlcc.transport-request.v001`，字段：

- `electronic_path`：已保存 mlcc.abacus-electronic.v001 产品。
- `task_path`：该产品唯一原生 SCF 任务目录。
- `kpoint_weight_field`：明确指定产品中的权重字段。不得重新归一打印权重、补点或用能带路径代替完整均匀网格。
- `temperatures_K`：显式非空正温度数组。
- `chemical_potentials_eV`：显式数组；`energy_reference="native_fermi"`，定义为相对该原生 EFERMI 的偏移。
- `dos_energy_window_eV`：相同参考的积分能窗 `[low,high]`；必须包含所选化学势。
- `dos_bins`：显式积分直方图分箱数。
- `equivalence_count`：显式 Fourier 等价类目标数量，后端返回的实际数量及 FFT 尺寸单独记录。
- `magnetic_symmetry`：nspin1 为 null；nspin2 必须显式提供 `moments_muB_by_atom_id` 与 `source_refs`，作为后端的对称输入。缺少时该实例 unresolved，不从总磁矩或初始种子自动推断磁序/最终局域矩，不使用伪造磁矩打破对称。

能量读取 `band_energies_eV[spin,k,band]`；这是既有电子 schema 的 eV 字段，不采用 parent_energy_zero_eV 总能量作能带原点。k 坐标必须是 direct_reciprocal_lattice，源网格须已声明完整并核对坐标/权重。nspin1 转为 `[band,k]`、dosweight=2；nspin2 将两通道沿 band 轴拼接、dosweight=1。不再次倍增自旋简并。占据与电子数保留在引用的既有电子产品中，复用其读取核对证据，不推算或选择掺杂量。

晶格使用保存原子结构的 Å 行向量，按后端官方规则转为列向量 Bohr（乘 units.Angstrom）；能量/化学势/能窗用 units.eV 转为 Ha。单位常数直接来自安装版本。保留原子/模型/方法/源 job 和原生电子收敛/调度状态。输入缺项返回 unresolved 产品，结果张量 null，列出缺项；源身份冲突保留原始异常，不回退或补零。

## 输出

输出 `mlcc.transport.v001`，四个张量的轴均为 `[temperature,chemical_potential,cartesian_row,cartesian_column]`：

- S：V/K。
- sigma_over_tau：S/(m s)。
- kappa_e_over_tau：W/(m K s)，零电流电子热导项。
- power_factor_over_tau：W/(m K^2 s)，明确使用 `S.T @ sigma_over_tau @ S`，不把逐元素平方推广到非对角张量。

记录全部原始参数、实际积分/FFT 网格、插值回采样残差、rigid-band/constant scalar relaxation-time 形式及来源。不猜 tau；不输出实际 sigma/kappa/PF、ZT 或晶格热导，不新设材料资格层。

## 最小实际输入及验收

两个只读上游无电子 BoltzTraP2 可迁移实现。已有 MD/Fickian/离子电导函数不适用于此链；PYATB 的矩阵输运器不是本轮保存能带后端。

已有 job40 `p4-czo-compatibility-scf-v001` 与 job43 保存 `czo-electronic.json` 提供 nspin1、完整2×2×2、精确权重0.125；同任务 result.final_atoms 提供晶格。以 330 K、原生费米偏移0 eV、积分能窗[-2,2] eV、4096 bins、64等价类为一个明确工程点，不新增温度或材料矩阵。

Ni37 同样具有完整2×2×2和晶格，但没有本轮显式 magnetic_symmetry 选择，保留该实例 unresolved；不因此阻塞非磁源公共路径。两者都复用保存源，不重跑 DFT。

只验收新数据桥、能量/自旋单位映射、一次后端数学对照、真实保存源公共入口与同Study交付。安装依赖 job434 因缺少 cmake 失败，job435 因构建隔离无法导入 cmake Python 模块失败；job436 显式改用 CMake 原生二进制安装完成。原始错误保留，没有自动重试。验收和交接见 workspace/reports/transport-v001/run-437/acceptance.json 与 final-handoff.md。

## 官方来源

- [PyPI 固定发布26.3.1](https://pypi.org/project/BoltzTraP2/26.3.1/)。下载源保存在 workspace/reports/transport-v001/reference/source-url.txt。
- [官方 dft 数据合同](https://gitlab.com/sousaw/BoltzTraP2/-/blob/v26.3.1/BoltzTraP2/dft.py)、[fite API](https://gitlab.com/sousaw/BoltzTraP2/-/blob/v26.3.1/BoltzTraP2/fite.py)、[bandlib API及SI转换](https://gitlab.com/sousaw/BoltzTraP2/-/blob/v26.3.1/BoltzTraP2/bandlib.py)、[units](https://gitlab.com/sousaw/BoltzTraP2/-/blob/v26.3.1/BoltzTraP2/units.py)。
- Madsen, Carrete & Verstraete, Computer Physics Communications 231 (2018), 140–145，[DOI:10.1016/j.cpc.2018.05.010](https://doi.org/10.1016/j.cpc.2018.05.010)，[作者稿](https://arxiv.org/abs/1712.07946)。刚性能带与输运积分方法取自原论文，不将材料精度验收增加到软件开发前置。
