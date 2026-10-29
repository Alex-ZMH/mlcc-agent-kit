# fea 专业接口草案

历史草案：electrostatics_2d已按正式schemas实施并注册。当前机器契约在schemas/electrostatics.*.schema.json，执行状态见ACCEPTANCE；本文件及schemas/draft保留设计依据。

状态：设计草案，未实现、未注册。公共接口保持1.0；本目录现有module.json仍not_integrated/operations={}。本文件及 `schemas/draft/` 供下一轮冻结接口，不构成可调用能力。

## 1. 操作与职责

建议首个操作名 `electrostatics_2d`，建议 `execution: queued`，证据主类型为 `real_computation`；具体超时及资源限制在确认部署与小例耗时后写manifest。成功返回实际数值，不能用demo或解析式替代真实求解。平行板解析比较是独立的数值检查证据，不要把解析值当FEM结果；是否另设benchmark操作由后续决定，当前不注册。

公共层维护task/输入快照、运行状态、worker/锁、协议/产物检查和查询；科学Adapter只处理科学输入、几何/网格/求解、后处理、检查与模块产物。WSL发行版、Conda解释器、path mapping、进程超时策略属于宿主绑定，详见INTERFACE_PROPOSAL。科学输入不含命令、脚本、sys.path、provider、审批令牌或任意文件输出路径。

未来可选导电→传热是另一项待确认操作，需独立输入/输出和方法验证；当前schema不接收coupled_analysis，不把静电扩成热力声平台。

## 2. 公共请求映射

```json
{
  "schema_version": "mlcc.adapter-request.v1",
  "interface_version": "1.0",
  "action": "preflight",
  "module_id": "fea",
  "operation": "electrostatics_2d",
  "input": {},
  "task_id": null,
  "artifact_dir": null
}
```

上例input={}仅显示外壳位置，**不是有效科学请求**。execute由公共层填真实task_id及其绝对artifact_dir，Adapter不得接受科学payload覆写它们。正式入口拟为adapter.py：从stdin读一个UTF-8 JSON，诊断stderr，stdout一个完整响应；不得把Gmsh打印、Conda banner或PETSc日志混入stdout。

preflight总预算≤10秒（公共上限）：纯结构/有限数/几何关系/资源估计/版本探测，不生成Gmsh几何、不JIT、不求解、不出预览。依赖版本可用元数据轻量读取；执行阶段再导入专业库并核对真实可用性。若预检无法在该预算内完成，向main报告实测瓶颈，不能自行把重型求解隐藏为预检。

## 3. 专业输入

机器草案：`schemas/draft/electrostatics.input.schema.json`。使用公共支持的schema子集，根和各对象拒绝未知字段；不依赖$ref/oneOf/default/条件schema。

| 字段 | 含义/单位 | 确定性额外检查 |
| --- | --- | --- |
| schema_version | fea.electrostatics-input.v1（拟定专业版本） | 与正式schema/操作版本绑定 |
| model / units | linear_isotropic_lossless_2d / SI | 只允许当前明确模型；不是自动选后端 |
| geometry | body_length_m、active_gap_count、dielectric_gap_m、electrode_thickness_m、electrode_overlap_m、left_margin_m、right_margin_m、top_cover_m、bottom_cover_m | 长度正有限；count非bool整数。保留来源1–79工程上限作为草案，不声称整个范围已验证；L=left+overlap+right；总高按完整堆叠构造 |
| out_of_plane_thickness_m | 明确挤出深度t [m] | 正有限，不设隐含1m/1mm；不计三维边缘 |
| material.relative_permittivity | 单个均匀介质εr，无量纲 | 正有限；拒绝其他材料模型、损耗/电导率参数 |
| material.source_reference | 用户提供的材料/参数来源说明 | 字符串存在不代表来源已审核；真实来源/工况还需scientific检查 |
| potentials.terminal_a_V / terminal_b_V | 端子电势[V]，有符号 | 两者有限且不同；0V是有效B端值，不能因真假值判断误报缺失 |
| mesh.target_size_m | 全局请求网格尺度[m] | 正有限；记录实际单元尺度/数量；资源预算属于可信部署策略，未批准的大请求结构化拒绝，不自动粗化 |
| outputs.field_data | 草案固定true | 原始场数据是成功必要证据 |
| outputs.field_images | 显式是否要求场图 | 不隐式开启重型viewer；图片不能替代VTU或数值验收 |

不把material名称“陶瓷”自动转换成εr，不因给了“MLCC”补几何；不以通用科学输入支持任意CAD。首版固定P1/串行及已确认数值方法，真实配置在provenance/方法记录中说明；暂不暴露未生效的求解器选项。

**可用于确认的原来源示例（仍是候选验证输入，无实际材料授权含义）**：

```json
{
  "schema_version": "fea.electrostatics-input.v1",
  "model": "linear_isotropic_lossless_2d",
  "units": "SI",
  "geometry": {
    "body_length_m": 0.0012,
    "active_gap_count": 6,
    "dielectric_gap_m": 0.000005,
    "electrode_thickness_m": 0.000002,
    "electrode_overlap_m": 0.0008,
    "left_margin_m": 0.0002,
    "right_margin_m": 0.0002,
    "top_cover_m": 0.00001,
    "bottom_cover_m": 0.00001
  },
  "out_of_plane_thickness_m": 0.001,
  "material": {
    "relative_permittivity": 1500,
    "source_reference": "Source example mlcc_2d.yaml; synthetic qualification input, material applicability not_checked"
  },
  "potentials": {"terminal_a_V": 10, "terminal_b_V": 0},
  "mesh": {"target_size_m": 0.000005},
  "outputs": {"field_data": true, "field_images": false}
}
```

## 4. 专业成功结果

机器草案：`schemas/draft/electrostatics.output.schema.json`，只约束公共响应中的results对象，公共provenance/quality/artifacts沿现有schema。未来应核对文件实际存在/数组与摘要一致，不只验证JSON类型。

| results字段 | 含义 |
| --- | --- |
| schema_version/model | fea.electrostatics-output.v1 / linear_isotropic_lossless_2d |
| out_of_plane_thickness_m、body_height_m | 实际采用深度与派生总高 |
| mesh_cells / dof_count | 真实求解的单元/自由度整数 |
| potential_min_V / potential_max_V | 节点场最小/最大，独立检查有限性/边界一致性 |
| electric_field_max_V_per_m | 单元场诊断极值；附尖角网格敏感限制 |
| charge_total_C | A/B有符号总电荷，`-t∫D·n ds` |
| charge_per_unit_depth_C_per_m | 上式除t，独立字段名 |
| energy_total_J / energy_per_unit_depth_J_per_m | `t/2∫E·D dA`及每米量 |
| capacitance_energy_total_F / capacitance_energy_per_unit_depth_F_per_m | 主输出 `2U/ΔV²`及每米量 |
| capacitance_raw_flux_total_F | `abs(QA)/abs(ΔV)`，仅诊断；不作为默认主电容 |
| charge_balance_relative / capacitance_methods_relative | 明确无量纲公式，不自动附带合格阈值 |
| outer_displacement_flux_total_C | 建议补保存`t∫outer D·n ds`，方向为陶瓷向外；目前生产Skill未输出，下一轮需实现再要求成功返回 |
| field_artifact / mesh_artifact / diagnostics_artifact | 仅artifacts/...登记相对引用，公共artifacts同时有descriptor |
| assumptions | 理想电极、均匀线性无损ε、无外空气、二维挤出、尖角Emax限制等实际假设 |

`capacitance_methods_relative=abs(C_Q-C_U)/max(abs(C_U),small_denominator)` 的small_denominator仅防数值除零，必须记录实现常数/依据，不能充当科学阈值。电荷不平衡公式同REVIEW，法向与电荷符号固定。材料/电压/深度变化不得重复乘层数；几何已表示全部有效间隙。

字段artifact中的潜在z=0只是展示坐标；真实E为x/y。若保留VTU三分量需在field manifest声明z为padding。所有总量显式填单位到公共provenance.units，不靠文件名推量纲。

## 5. 公共响应与证据

preflight响应严格使用 `mlcc.adapter-preflight.v1` 的ready/errors/warnings/checks。拟定领域错误码：INVALID_GEOMETRY、INVALID_MATERIAL、INVALID_POTENTIALS、INVALID_UNITS、UNSUPPORTED_MODEL、RESOURCE_LIMIT、BACKEND_UNAVAILABLE、BACKEND_VERSION_UNSUPPORTED。不要把缺后端当真实求解失败，更不能静默更换后端。

execute响应严格使用 `mlcc.adapter-result.v1`：

- execution_status=succeeded：科学过程/必要导出实际完成、results通过专业schema；QC仍可warning/failed/not_checked。
- blocked：输入/环境/资源/明确不支持机制阻止执行。failed：网格、标签、求解、必要导出等过程失败，给具体stage及原生错误；failed/blocked可results={}、evidence_kind=none，不补虚假C/Q/U。
- numerical/scientific各检查 `{id,status,message}`，status沿公共五值。未实施或没有判定依据写not_checked；不适用需要说明依据，不能用not_applicable掩盖未做。
- provenance.method：模块科学方法版本；backend：真实DOLFINx版本；conditions：全部实际几何/材料/电势/深度/边界约定、串行P1和真实求解器设置；sources：本次输入材料来源、抽取代码归属、必要参考/基准；applicability：有界模型而非商业器件资格。
- stderr保留原生日志；大数组只放文件。可选图片失败可在已保存必要科学结果的前提下作为明确warning，不能伪造图片descriptor；如果未来产品把某图规定为必要产物，则按该契约失败。
- 旧SOLVED_UNVERIFIED只说明来源状态；新公共status不要自造这个枚举，应以执行succeeded+对应not_checked表达。

## 6. 候选检查ID与科学负责人批准项

| 组 | ID | 内容/何时可passed |
| --- | --- | --- |
| numerical | mesh_semantics | CERAMIC及A/B/outer标签、实际facet/DOF非空、外界精确覆盖、互斥无内部错标 |
| numerical | mesh_geometry | 维数、有限坐标、非退化单元和实际几何；shape质量指标/阈值未确认则相应项not_checked，不能从旧mesh_report.valid推导 |
| numerical | linear_solver | 真实选项、reason、必要残差/有限性；缺残差不冒充残差检查通过 |
| numerical | field_finiteness | φ/E/积分量有限、数组shape/关联与网格匹配 |
| numerical | depth_units | 总量与每米量、t换算及signed Q约定；非1m厚度不变量需真实检查 |
| numerical | charge_balance | 报QA/QB/外通量及残差，容差与归一化须科学负责人批准 |
| numerical | capacitance_consistency | 主能量法与raw flux差，独立记录网格依赖；容差待定 |
| numerical | mesh_convergence | 针对此输入或明确认可的适用验证范围做有依据网格比较；单次run不能passed |
| numerical | analytic_reference | 目标后端的小型解析基准实测通过；解析公式自己返回数值不算真实求解验证 |
| scientific | model_applicability | 科学负责人确认二维/理想电极/外绝缘/线性均匀介质适用于请求 |
| scientific | material_provenance | ε来源、温度/偏压等适用工况清楚；字符串非空不自动passed |
| scientific | independent_device_reference | 若声称实物器件精度则需要独立对照；无数据明确not_checked，不扩大claim |

以上为候选检查，不写入本轮manifest。下一轮按已确认首版声明required_checks；不能为了全passed删去应有但未实施的检查。周期性解析环境资格与单任务网格验证应记录不同证据来源，禁止从“参数落在旧范围”直接判本次通过。

## 7. 建议产物与依赖

执行只在公共给定artifact_dir内创建文件，示意引用（不是当前已实现产物）：

```text
artifacts/input.normalized.json
artifacts/method_environment.json
artifacts/mesh/mesh.msh
artifacts/mesh/mesh_report.json
artifacts/fields/fields.vtu
artifacts/fields/manifest.json
artifacts/metrics.json
artifacts/quality.json
artifacts/solver.log
artifacts/artifact_hashes.json
artifacts/images/semantic_regions.png        可选
artifacts/images/potential.png              可选
artifacts/images/electric_field.png         可选
```

scratch/cache由运行层约定的当前任务工作位置容纳；当前请求只有artifact_dir，模块可在其内部scratch子目录工作、只登记公开产物；禁止写来源库、固定workspace或自行改公共record。未来需独立scratch/执行上下文字段时向main提案，不滥用科学输入。失败保留已生成的诊断文件且明确其诊断性质。

模块独立环境拟依赖DOLFINx/UFL/PETSc/MPI/Gmsh/NumPy及VTU工具；现有环境实际版本见REVIEW与environment.json。Pydantic/PyYAML仅在继续使用时列入模块依赖，Matplotlib/PyVista图片工具按实际实现说明。公共模块顶层不可导入这些库。来源版本范围不是跨机器环境锁；真实版本支持应由preflight报告与环境文档管理。

未来COMSOL适配只消费同一科学概念并返回同一量纲结果；网格/求解和原生文件都在各自后端实现。实现前必须重新验证方程/电极/深度/材料/法向/参考值，不注册虚拟COMSOL能力。
