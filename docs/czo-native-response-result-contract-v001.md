# CZO 原生响应结果合同

本切片验证通用系统的真实数据流，父对象为已选 CaZrO3 Pnma-20、Study cazro3_firing_validation_v003。几何是未弛豫实验参考，不代表烧制温度平衡态。

实际源链：参考 SCF269、位移 SCF284–307 → 原生收集312；参考 H/S/r → PYATB311 → 已验收电子产品344；位移各自 H/S/r → 极化316–339 → 有序聚合347 → 完整仿射系数348 → 显式坐标合同349。原力经345装配原始 Γ。全部复用原计算，347–349之间只补保存结果的领域系数/坐标。

Born 产品 `mlcc.native-born-branch-family.v1` 保留12个中心位移对、原始晶格方向P/Q、每点SCF/PYATB原生日志与作业。原生产文件顶层atom_ids是4个独立位移位点；完整20原子顺序在affine_family.atom_ids_in_tensor_order，消费信封必须以完整顺序绑定父Model，并保留原始4位点列表。先把极化方向转换为Cartesian，再应用Pnma八操作：`Z_cart=U.T Z_lattice`，`R Z_cart R.T`。完整仿射关系为 `Z(n)=Z_base+Σ n_k C_k`，基准20×3×3、36项整数系数各20×3×3；n仍未选择。基准不等于已选择物理Born。site-group averaging明确记录，与ASR/电荷中性投影不同。

Γ 产品 `mlcc.czo-native-raw-gamma-force.v001` 保存20×20×3×3力常数与60×60 Hessian，单位eV/Å²；行位移/列受力。参考力扣除策略及测量原值均保留。未进行ASR、互易、Hermitian或NAC投影。345的原始互易偏差0.00474148 eV/Å²，状态unresolved_raw_nonsymmetric；不将原始Hessian特征诊断冒充已资格的声子频率。

电子产品保留269→311→344原生派生来源，ε∞为固定离子、固定胞、独立粒子direct-static相对介电张量，包含单位阵。与Born/Γ使用同一新LCAO方法，不混PW/197/文献常数。

公共同Study结果必须保存三类真实来源及条件：物理Born未选时有效Born张量为null；Γ保持原始诊断；离子/总介电未满足条件时为null，并列出具体原因。工程交付可以验证来源、单位、原子映射、参数传递及失败/未定状态传播；不据此授予数值精度、材料或生产资格。

实际控制层TaskRecord绑定：Γ provenance.postprocess_task_file指345 task.json；Born source.collection_file指有序集合，source.postprocess_task_files覆盖347/348/349三项原生终态。349保留348数据副本及坐标转换公式。附加控制层来源记录不重新计算任何数值。

0.29保持启用冻结。0.30的接线、真实公共交付与最终集成仍以实施窗口的实际验收及主线复核为准；本合同本身不宣布验收或发布完成。
