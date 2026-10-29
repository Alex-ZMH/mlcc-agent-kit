# 器件扩展多单位入口交接（可用，fem 0.4.0，2026-10-22）

当前阶段：三个入口已在module.json注册，通过Windows公共入口真实调用既有WSL科学环境。保持原SI入口、schema和科学模型兼容；不改公共核心，不做LLM调用或参数扫描。

| 新入口 | 新输入schema | 多单位等价示例 | 保持兼容的SI入口 |
| --- | --- | --- | --- |
| electrothermal_2d_quantities | schemas/electrothermal.quantities.input.schema.json | examples/electrothermal-quantities.json | electrothermal_2d |
| ac_eqs_2d_quantities | schemas/ac_eqs.quantities.input.schema.json | examples/ac_eqs-quantities.json | ac_eqs_2d |
| electromagnetic_2d_quantities | schemas/electromagnetic.quantities.input.schema.json | examples/electromagnetic-quantities.json | electromagnetic_2d |

每个维度字段为严格`{value,unit,source:{kind,reference}}`，units=`explicit_quantities`。完整结构以schema/示例为准：

- geometry移除_m后缀；out_of_plane_thickness、mesh.target_size为长度量值；active_gap_count仍为整数。
- frequency为频率量值；potentials的terminal_a_real/terminal_a_imag/terminal_b_real/terminal_b_imag均为电势量值。
- materials中eps_r/tan_delta/source_reference保留，sigma为电导率量值。
- thermal中enabled/boundary_kind/source_reference保留；ceramic_k、Ni_k、ambient、convection_h分别为热导率、绝对温度与对流系数量值。
- EM的port中bus_width/feed_air/bottom_air为长度量值，model/source_reference保留；current包含real/imag电流量值及convention=`rms`。mu_r仍为固定1的无量纲参数。
- voltage_convention仍是物理幅值约定，单位换算不替代peak→RMS；温升输出保持K，输入ambient允许公共核心明确定义的°C→K。

由Windows调用唯一normalize_fields，生成原有SI schema，然后使用原验证器/WSL内核；公共任务仍保存用户原始typed input。每任务保存input.original.json、input.canonical-si.json、unit_normalization.json，规范化器不覆盖原输入。WSL只接SI与原base operation，无二次缩放。

公共core_version仍为1.0.0，本次实际catalog_version为1.1.0。FEM不精确锁词表版本：核对所需kind的语义、维度、canonical单位及实际输入单位的核心登记；以后追加无关kind/单位保持兼容，缺必要能力或改既有语义则拒绝。审计记录实际catalog_version。拼写/别名、倍率和温度偏移均由公共核心解释，无模块fallback。

实际等价任务（results和quality逐项与保存的SI基线完全一致，未重跑基线）：

| 新入口 | 真实task_id | SI基线 |
| --- | --- | --- |
| electrothermal_2d_quantities | task-344eedd76013465d8bb88a402927306c | task-2bd9b855fa29416dbedafc7b60900200 |
| ac_eqs_2d_quantities | task-27b2b2392ee74043a0782042d33f043a | task-557af8194a224f25a15fcac71ef00d72 |
| electromagnetic_2d_quantities | task-dedb1b61ad724deab2a9ce3dac19b960 | task-ead43fba81944f888e2b3eb366d8ac24 |

部署仍使用deployment/extended.example.json（原v2预算/环境不变），旧静电两项仍用v1。完整调用见EXTENDED_GUIDE.md；验收及未检查项见EXTENDED_UNITS_ACCEPTANCE.md。main可用这些稳定命名开展独立多参数矩阵和AC Agent验收；本模块未运行这些额外验证，不将公共链路成功冒充新LLM对话通过。
