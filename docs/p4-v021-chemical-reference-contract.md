# 0.21 化学参考原生来源合同

2026-10-23。0.20冻结、0.19回退、源码0.21。目标是整胞原生总能量/组成→明确参考角色及每式量归一化→现有chemical_potential_region/neutral_formation/Study消费。不开新求解器或任务框架，不新增DFT/MD/训练，不把缺相/μ点当系统开发暂停条件。

## 所有权与恢复点

主线独占本合同、共享defect_thermodynamics.py/property_delivery.py/cli.py及集成报告workspace/reports/chemical-reference-integration-v001。现有实施聊天独占新增chemical_references.py、test_chemical_references.py、workspace/reports/chemical-reference-native-v001；其CURRENT_TASK.md保持范围/独占文件/已完成/下一步，压缩后先读，不返回旧MD任务。saved-evidence-audit.md可用，但此前旧MD final不是本化学切片交付。

## 固定API和请求

模块提供：

- `read_chemical_reference(spec)`：绑定一项已保存电子/总能来源并归一化，不重解析原生能级。
- `assemble_chemical_reference_set(request, references)`：消费上项记录列表，核对声明角色、共同物理方法及共同元素赝势，生成已齐备的旧数学函数输入或缺项。数学测试记录必须标software_contract_only，不产生原生正例。
- `build_chemical_reference_set(request_path)`：读取请求、按请求文件目录解析相对task_path/electronic_path，调用前两项。无调度、重试或DFT。

请求schema=`mlcc.chemical-reference-request.v1`：

```json
{
  "schema": "mlcc.chemical-reference-request.v1",
  "reference_set_id": "explicit-reference-set-id",
  "elements": ["Ca", "Zr", "O"],
  "host_reference_id": "czo-pnma-host",
  "elemental_reference_ids": {"Ca": null, "Zr": null, "O": null},
  "competing_reference_ids": null,
  "selected_delta_mu": null,
  "references": [{
    "reference_id": "czo-pnma-host", "role": "host",
    "phase_id": "CaZrO3_orthorhombic_Pnma",
    "phase_selection_source": "previously selected pristine Pnma model",
    "formula_stoichiometry": {"Ca": 1, "Zr": 1, "O": 3},
    "task_path": "explicit/task/path",
    "electronic_path": "explicit/saved/electronic.json"
  }]
}
```

role只允许host/elemental/competing。elemental只能含一种元素，其formula_stoichiometry可表达明确分子式，但不自动选择任何元素相/分子。competing_reference_ids=null表示尚未选择，[]仅表示调用方明确声明本次不含竞争相，输出保留该范围，不称完整稳定域。元素映射必须覆盖elements，每项明确ID或null；host唯一且必须组成覆盖elements。所有已声明ID需角色匹配；缺实际文件直接报原错误，null选择形成可读缺项。

CZO Pnma未掺杂基线已选，旧Study.phase空不推翻模型选择。当前未选的是Ca/Zr/O元素参考相、竞争相集合及μ点。不得自动选Ca/Zr/O/O2或富氧贫氧点。103只为旧数值诊断，不纳入本原生来源集合；121是缺陷，不作元素/竞争相参考。

## 原生单源与归一化

复用`defect_references.defect_electronic_reference(task_path, saved_electronic, role="host")`的既有保存源绑定，避免复制来源框架或重读能级；其非缺陷、中性、固定胞SCF范围同样适用于本切片明确的相参考。记录本函数名称是复用实现，不把elemental角色改成物理host。保存task/result/method/model/Study/atom-map及原始source_files、job终态、电子收敛、method_set和条件。

限定ABACUS3.10.1 PW、neutral、fixed occupation、非SOC共线，结果总能定义与保存电子`parent_energy_zero_definition`一致。`parent_energy_zero_eV`在此明确命名total_energy_eV_cell，不是电势或μ。真实job50可复用200保存的host-50.json；不重跑200/电子解析/DFT。缺task.net_charge历史字段由已有binding依method和原生电子数检查，不补写旧记录。

以model.composition与result.final_atoms.symbols计数核对真实整胞组成。调用方显式给正整数formula_stoichiometry；必须存在同一个正整数N，使各元素cell_count=N*formula_count。不自动约化、猜化学式或用总原子数作每式量分母。保存N、原始整胞总能和E/N（eV/formula_unit）。elemental的μ参考为E/该元素整胞原子数（eV/atom），同时保留分子式/N，不把O2的每分子能当每原子能。

每项schema=`mlcc.chemical-reference.v1`，固定主要字段：reference_id/role/phase_id/phase_selection_source/formula_stoichiometry/cell_composition/formula_units/total_energy_eV_cell/energy_eV_per_formula_unit/elemental_mu_eV_per_atom（非elemental为null），以及`source`（上述既有binding完整返回）。科学/生产资格false；`evidence_kind`=native_saved_source或software_contract_only。

## 不同组成的共同方法

保留各自原method_set，不以相同标签证明等价，也不强行要求所有参考相具有相同k网格或磁态。对共同字段engine/version、PW、dft_functional、lspinorb/noncolin、固定占据/能量定义逐项相等；本切片不接受未知附加U/外场/不同能量定义。共同元素的pseudopotential_ids、metadata（类型/价电子/相对论属性等）和treatment逐项比较，不仅比较UPF文件名。

每相nspin、初始磁矩、结构、对称性、ks_solver/device、parameters、kpoints及原method_set完整保留为per_reference_methods，列出差异；这些差异不自动变成精度或磁态资格。任何不支持的额外物理字段明确为未评估/拒绝，不能仅共享标签即吞掉。共同字段只声明recorded_physics_and_common_element_PP_match，禁止宣称完整方法/材料科学等价。

## 组合及旧函数输入

集合schema=`mlcc.chemical-reference-set.v1`，保存reference_set_id/elements/host_reference_id/references/per_reference_methods/method_comparison/missing/region_request、selected_delta_mu、scientific_qualification=false/production_qualification=false。host来源和E/N即便缺元素/竞争相也可交付。region_request仅在host、全部元素参考和明确竞争相列表已齐时非null；缺μ点不阻止域输入构造，点维持null。missing至少区分elemental_reference:<element>、competing_phase_selection、selected_delta_mu。

完整时沿用现有输入字段elements、physics（temperature_model=0K_DFT_formation_energy，oxygen_reservoir=null）、mu_ref、host、competing_phases、selected_delta_mu。mu_ref[i].value_eV_per_atom取显式elemental来源；每相formation_energy_eV=E_per_formula-sum(formula_i*mu_ref_i)。相source_tasks保留自身及所有实际所用元素源task IDs。每条记录保留原`method_set`，另外加`reference_method_id=reference_set_id`和来源reference_id；不得覆盖原标签。

主线将对旧数学函数作最小兼容：reference_method_id存在时作为显式共同参考组键，旧输入无该字段保持原行为；输出仍保留原method_set和reference_method_id。函数本身是显式数据的数学消费，不因传入组键赋予原生资格；原生来源检查在本模块完成。主线复用现有region solver，不重写LP。point只有显式selected_delta_mu且约束可行时转成neutral_formation兼容记录；其reference.engine/version/method_set/energy_definition仍取host原身份，另保存reference_set_id和完整源，不自动选点。

公共入口由主线增加`chemical-references --request <JSON> --output <JSON>`与`deliver-properties --chemical-references <已保存集合JSON>`（与既有模式互斥）。后者调用既有域函数（若region_request齐），绑定Study host模型/实际job，返回region及compatible chemical_point，缺项保持null。neutral-formation继续消费显式chemical_point，不重写其算法；本次没有真实μ，所以真实形成能继续null。完整数学例只能证明接线/算法，不能冒充元素原生源。

主线的薄消费补充：`neutral-formation --chemical-reference-delivery <交付JSON>`与原`--chemical-point`互斥，先核对交付host任务再转发chemical_point给原函数。完整数学例得到mathematical_chemical_point，native chemical_point始终null，不能将测试μ送进真实缺陷任务。

## 验收

模块由实施聊天在v100 Slurm做一次新增定向检查并读取host50，1CPU、2GiB、2分钟、no-requeue。先保存source集合JSON，主线安装/CLI只消费保存记录，不重跑模块测试或原生能级。实际应传递Ca4Zr4O12、4个CaZrO3式量、job50来源和明确缺元素/竞争相/μ点。数学例检查完整输入、每式量/每原子分母、方法/PP冲突与保留缺项，必须明显标为软件例。所有数值归一化、域/形成能消费和数值验收只在v100 Slurm；本地编辑/传输/控制/看证据。
