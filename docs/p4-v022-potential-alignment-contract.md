# 0.22：显式选区的势差诊断与来源交付合同

2026-10-23。0.21冻结/0.20回退；0.22候选。当前目标是完整输入可直接运算的同胞、同网格电子势能差及Study消费。本轮不做DFT、MD、训练、选材料或精度优化。已审查P5：完整Born、Gamma力和电子介电源仍缺，没有已就绪而应优先恢复的新源接口；既有P5数学和缺项交付不重复。

## 所有权

既有实施聊天独占`potential_alignment.py`、`test_potential_alignment.py`和`workspace/reports/potential-alignment-v001/`。主线独占本合同、CLI、property_delivery、共享electrostatic_potential/defect_references/defect_thermodynamics以及`workspace/reports/potential-alignment-integration-v001/`。不新增框架或MCP工具。实施窗口开始后更新CURRENT_TASK，压缩后读取；0.21工作不重做。

## 物理定义与边界

ABACUS3.10.1的out_pot=2字段是电子哈密顿量中的离子局域势加Hartree，Ry；不是正试探电荷的电势。直接复用0.20的单位常数和保存网格，保留原零点。q>0表示移去q个电子。

用户显式给出同一网格上的区域R后，计算：

- `delta_v_defect_minus_host_eV = mean_R(Vdefect - Vhost)`，两场先用既有Ry→eV常数解释。
- 同时报告样本数、host/defect区域均值、差值最小/最大、population标准差(ddof=0)和峰峰差。标准差只描述区域变化，不是统计独立样本误差或收敛资格。
- 若绑定同一host任务的已保存电子VBM可用，可输出`candidate_host_vbm_on_defect_gauge_eV = host_vbm_eV + delta_v_defect_minus_host_eV`，明确为所选区域参考移位候选。相反，将defect电子能级移至host零点应减同一差值。

相同胞、网格和明示选区并不证明该区域已达到物理远场；不自动找平台、阈值、最远区域、晶核或空间平均零点。不做平移、旋转、插值、重采样或自动筛点。仅支持同一坐标框架、相同shape、origin及完整step vectors；几何比较采用原输出打印精度，不能把不同网格近似成同一网格。

`potential_alignment_eV`在既有formation correction接口中是已经换算后的能量贡献，不是本合同的原始势差。故该字段、`aligned_host_vbm_eV`、`correction_terms`、FNV/eFNV和charged formation保持null；不得自动乘q并接入形成能。未来若采用传统参考移位的qΔV项，须冻结其完整能量表达式与符号；若采用FNV/eFNV，模型长程势/介电/电荷分布/边界及alignment-like项须统一定义，不能再次叠加这里的qΔV。依据：[Kumagai–Oba 2014](https://doi.org/10.1103/PhysRevB.89.195205)。ABACUS定义依据已保存的精确3.10.1审查及205/206，不使用VASP输出假设。

## 固定API

1. `calculate_regional_potential_difference(host_potential, defect_potential, selection)`：纯领域函数；消费0.20势记录结构，完整输入执行上述运算。明确软件数学输入标`evidence_kind=software_contract_only`，不得产生native成功证据。
2. `build_potential_alignment(request_path)`：读请求、按请求目录解析路径；调用既有`build_defect_electronic_reference(host_electronic_path, defect_electronic_path, descriptor_path)`一次绑定保存电子来源，读已保存势JSON，不调用cube或电子原生解析器。验证来源后调用上项或显式返回缺项。

请求schema=`mlcc.potential-alignment-request.v1`：

```json
{
  "schema": "mlcc.potential-alignment-request.v1",
  "alignment_id": "explicit-pair-id",
  "host_electronic_path": "saved/host-electronic.json",
  "defect_electronic_path": "saved/defect-electronic.json",
  "descriptor_path": "defect-model/model.json",
  "host_potential_path": "saved/host-potential.json",
  "defect_potential_path": null,
  "selection": null
}
```

selection完整时为`{"kind":"index_boxes","boxes":[{"lower":[0,0,0],"upper":[2,3,4]}],"reason":"explicit physical selection rationale","source":"selection document/user declaration"}`。上下界均零基整数，三维半开区间[lower,upper)，在网格范围内；多个箱取并集，每个网格点权重相同，重叠不重复计数。非空区域即可，单点不构成平台证据。这里的数字仅说明格式，不是实际CZO选区。native request的selection继续null。

## 来源/方法校验

- native势必须为`mlcc.abacus-electrostatic-potential.v1`，类型local_ionic_plus_hartree、电子势能符号、Ry/Bohr和0.20的未减均值/EF/真空零点，电子收敛、native_output_observed与保存的原生Slurm完成证据成立。纯cube不能作为native输入。
- 每一势记录的task/job、Study/model/version、method_set、完整method、atom_map/source IDs、source_files内task/result/model/INPUT等绑定对应电子reference的同一任务。不能把host50电子和host205势仅凭同一模型合并。保存引用路径指向同一来源，不重读native grid或能级。
- host必须中性非缺陷；defect必须显式descriptor指向该host父模型；复用既有pair校验。实际q、charge convention和atom lineage保留，不强求host/defect原子数相同。
- 复用pair.method_comparison的记录字段，完整计算要求`same_recorded_comparison_fields=true`；q变化按显式声明允许，不把method_set标签相同当物理等价。两侧完整method随结果保留。当前严格同方法/同数值首切片不支持跨方法比较。
- 对所有已提供的输入先做来源检查；缺另一网格不能掩盖已提供源不匹配。缺网格或selection返回明确missing，不能把已存在的错误路径当missing。
- 软件数学fixture与native结果分开；来自软件电子来源/势的结果始终software_contract_only，绝不能成为native source-bound成功。测试不得制造貌似native的完整正例。

## 输出与主线集成

输出schema=`mlcc.potential-alignment.v1`，包含alignment_id、request_path、`references`（完整原pair）、`source_paths`、`potentials`（每侧紧凑来源/单位/grid/method/job摘要，保留原artifact路径，不重复复制全网格）、selection、missing、`difference`（纯函数结果或null）、`candidate_host_vbm_on_defect_gauge_eV`、`evidence_kind`。缺项状态`missing_inputs`，完整运算`computed_regional_difference_unqualified`。

顶层`potential_alignment_eV`、`aligned_host_vbm_eV`、`correction_terms`、`FNV_eFNV_correction_eV`、`charged_formation_energy_eV`均null，`native_alignment_accepted/scientific_qualification/production_qualification=false`。完整数学运算可输出非空difference/candidate VBM，但不能改资格。

主线增加`potential-alignment --request --output`公共入口；现有`deliver-properties`互斥入口增`--potential-alignment RESULT`，只消费保存结果，绑定defect Study/model并完整保留诊断及缺项，不再运行领域函数。没有新的形成能分支或校正默认值。

## 唯一新增检查预算与真实复用

实施窗口一次Slurm软件/保存源验收：cpu 1任务/1CPU、2GiB、2分钟、no-requeue，数值线程1。纯差值/统计无需GPU。本地仅编辑、传输、控制、查看证据。

真实host为job205，同task电子/势由206保存：`/home/v100/projects/mlcc/reports/electrostatic-source-integration-v001/installed-206/{electronic,potential}.json`。defect复用121及200保存电子JSON（精确文件名先读取旧证据，不猜）；descriptor使用其模型。真实缺defect势、selection，missing必须保留；不为验收生成它们。只调用新公共CLI一次，不重复205/206/207/208或旧解析。

完整数学正例覆盖差值方向、Ry→eV、恒定位移、非均匀场、重叠选区/非正交网格、错误坐标/单位/来源和软件证据边界。主线安装验收仅补新CLI/Study消费，不重跑模块或真实来源绑定。实际双native网格的完整科学验收仍未完成，不阻塞该可运行软件切片。
