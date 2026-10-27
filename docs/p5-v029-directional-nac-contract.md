# 0.29：Γ 点指定方向 NAC

2026-10-23 用户授权的最小切片，对应 P5.06 / P7.07。

输入复用 job197 的明确 NaCl-math-fixture：保存的二阶力常数、位移计划、母模型/Study、Born ±I、电子 ε∞=2I。保留原数学方法、质量、原子编号及来源；不冒充 Ni 或 CaZrO3 原生结果。采用已安装 Phonopy 4.8.3 的显式 Wang NAC，方向为 primitive reciprocal fractional 非零三向量。固定胞，仅计算一个 Γ 极限方向的基线和修正动力学矩阵及频率；不重新拟合力常数、不做 ASR、不改变旧 Γ Hessian 或离子介电求解器。

公共入口：`phonon-nac --request <JSON> --born <JSON> --electronic <JSON> --output <新JSON>`。请求沿用 phonon-gamma 的保存源、父模型、方法与容差字段，增加 `nac_method: wang`、`direction_basis: primitive_reciprocal_fractional`、`nac_q_direction: [1,0,0]`。Born 与 ε∞ 必须完整且同模型/方法/原子顺序，实际输入路径保留。Wang 长程项使用 Phonopy 的 eV/Å、电子电荷单位转换，并核对质量归一化。

安装源码审查更正：4.8.3 的 `run_qpoints` 未转发 hermitianize，默认会做 Hermitian 化。因此本实现使用其 `get_dynamical_matrices_at_qpoints` 底层 Rust 接口，显式 `hermitianize=False`，限定计划 `is_symmetry=False` 避免隐式改写 Born/ε∞。新增请求 `dynamical_hermitian_tolerance: 1e-12`（eV/Å²/amu），记录原矩阵 Hermitian 残差，超过时原样报错；不修正矩阵。通过残差检查才求带符号频率。方向归一化后传引擎并保留请求原值。此处不修改旧 Γ 实现。

`deliver-properties --study <同一Study> --p5 <请求JSON> --output <新JSON>` 增加可选 `nac` 文件引用，独立保存 NAC 产品、方向、单位、来源、未资格状态。它不能替换 `gamma`，不会进入离子介电 Hessian。交付消费保存结果，不重算 NAC。

验收顺序：审查新增精确测试节点 → v100 Slurm 新模块检查 → 新交付检查（复用模块结果）→ 发布副本的两个公共命令端到端验收。旧测试、完整 MCP 宿主验收不重复；MCP 服务入口未变，复用已有连接证据并核对发布绑定。所有数值/测试都在 Slurm，采用单 CPU、2 GiB、10 分钟、no-requeue；本机 Phonopy 此接口为 CPU C/Rust 小矩阵实现，没有已接通的 CUDA 路径，故不申请闲置 GPU。

数学校验：与解析 rank-one 长程项比较、方向缩放不变性、横向模式不变；检查单位/质量/原子映射及拒绝缺失或矛盾输入。保存原始错误与 job 终态。生产和科学资格始终 false，不开展材料精度研究，不增加 MD/DFT/训练。

所有权：Luna nac_core 负责新 phonon_nac.py 与新模块测试；Luna nac_delivery 负责 property_delivery.py 与新消费测试；主代理负责合同、CLI、审查、Slurm、安装发布及证据。不改独立 DeePMD 和其他任务。
