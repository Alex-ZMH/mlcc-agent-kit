# 0.33 原生 affine Born 分支审定转换

用户授权范围：实现保存的 LCAO affine 分支族到经外部审定的 Born 张量的领域转换，并接入已有消费路径。当前启用 0.32、回退 0.31、源码 0.33。无新增 DFT/PYATB/MD，无自动选支、ASR、Gamma 投影或 Hessian 修改。

## 数学与输入

直接计算 `Z[n] = base_tensor_e + sum(n[k] * coefficient_tensors_e[k])`，输出保持原子、极化 Cartesian xyz、位移 Cartesian xyz 的 N×3×3 顺序，单位 e。输入必须显式给出与 integer_labels 一一对应的全部整数（不接受布尔、浮点、缺项或猜测）。不优化分支整数，不将最近量子或声学和规则当成分支证据。

新模块 `born_affine.py`：

- `evaluate_born_affine(affine, integer_shifts)`：纯领域运算。
- `resolve_born_affine_family(born, review, *, review_path)`：消费现有读取器输出及外部审定，保持现有 `mlcc.born-charge-columns.v1`。
- `consume_native_born_review(family_path, review_path=None)`：调用原 `read_native_born_family`，再作上述转换；不修改保存族。

外部审定 schema 为 `mlcc.native-born-affine-review.v1`，包含 `family_path`（精确绝对路径）、`context`（现有产品的完整 parent/method/cell/atom context）、`integer_labels`（完整原始有序标签）、`decision`（accepted/deferred/rejected）、`reviewer`、`reviewed_at`、`rationale`、`integer_shifts`（accepted 才要求完整整数列表）、`continuous_branch_evidence`。

每条连续分支证据包含 `atom_id`、`direction_index`、`kind: continuous_polarization_path`、`source_refs`（非空、存在且有内容的外部审阅依据文件列表）、`rationale`。必须覆盖 integer_labels 的每个独立(atom_id,direction_index)组且不重复；独立端点 P/Q 或最近量子不是该证据类型。此项是外部审定的显式证据合同，不是软件自动证明物理连续性。真实 CZO 当前没有这样的审定，禁止编造。

本入口只接受当前原生 producer 的字典标签记录：label_index/atom_id/atom_index/direction/direction_index/polarization_lattice_axis/index，按原始顺序核对、每组覆盖a/b/c。旧软件夹具的列表式标签不在审定转换范围，不做兼容回退；未审定族的既有读取接口保持不变。

无 review、deferred/rejected、缺连续分支证据时，输出 unresolved、full_born_tensors_e=null，列明原因。输入身份冲突、非整数或引用文件不存在保留原始异常。accepted 且证据完整后计算张量，status=reviewed_branch_tensor；科学/数值/生产资格仍 false，外部选支审定不授整体资格。原始 affine/来源、审定原文和证据引用均随产品保留；不覆盖原族 unresolved 原文。

## 公共消费与所有权

新增公共 `born-affine --family FAMILY [--review REVIEW] --output NEW`。原 born-charges/PW Berry 路径不改。结果可直接进入现有 deliver-properties/ionic-dielectric/NAC 的 Born 合同。统一交付 native source 绑定时从 family 和 review 重新推导并比较产品，防止编辑已保存张量冒充源结果；仍沿用既有 native_jobs，不制造新物理 job。

Luna 独占 born_affine.py 和新增 tests/test_born_affine_review.py；主代理负责 CLI、property_delivery、集成验收、审查和发布。现有 dielectric_response.py/Hessian/raw Gamma 不改。各方保留他人编辑。

## 最小验收

预定一个 v100 Slurm 非 DFT 作业：1 CPU、0 GPU、2 GiB、10 分钟、no-requeue；当前直接 NumPy 小矩阵路径不使用 CUDA。只跑新增领域检查，再对真实保存的 Born 族执行新公共命令（无审定，必须 unresolved），把该新产品接入既有同 Study 交付。复用旧 Gamma/电子贡献和 job355请求，不运行旧测试、旧解析或引擎。

完整正例是明确标记的数学/软件合同，不能作为真实材料 Born 资格。真实路径验收只证明未决状态正确传递。失败保留原 job/输出；若需定向修复，只补受影响节点，不自动重试。
