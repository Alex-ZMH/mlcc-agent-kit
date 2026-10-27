# 0.28：显式外部电子介电输入与 Study 交付

2026-10-23冻结。0.27启用冻结、0.26回退、0.28源码候选。本合同只补现有输入/来源/消费路径，不建立ABACUS原生电子介电producer，不开展DFT、MD、训练或材料参数研究。

## 所有权

主线独占property_delivery.py、test_p5_property_delivery.py、必要cli.py接线、合同、计划、安装集成与发布判断，可委托Luna完成限定文件。既有实施聊天01a15851-eb0c-7832-ba67-4833802afd0f独占dielectric_response.py、test_dielectric_response.py与workspace/reports/external-electronic-source-v001/。不得改动对方文件、冻结副本或现有Born/Gamma/离子张量代数。

## 输入字段与接口

电子记录新增显式 `provenance_kind: "external_supplied"`，与 `method_identity.engine` 分离。既有parent/atom_ids/cell/volume/method/kind/unit/tensor/electrical_boundary/mechanical_boundary/ions/source_refs必须原样保留并通过原校验。保留输入原资格字段，任何派生结果仍不自动获科学/生产资格。未知provenance_kind拒绝；没有该字段的旧math-fixture记录维持旧软件路径。非数学电子输入没有明确external_supplied时，不允许经组合/交付冒充已存在的原生producer。

实施端提供小函数 `bind_external_electronic_input(electronic, input_path=None) -> dict`：要求external_supplied并返回副本；实际输入路径由调用者提供，规范化为绝对存在文件，保存为 `source_path`。若记录已有source_path则必须与调用者提供的路径一致；没有input_path时必须已有绝对source_path。source_refs为非空字符串列表。该函数不读回、改写源文件，不计算哈希，不认定外部数值有效。拒绝external记录携带 `source_mode=native_source_bound` 或非空native_tasks/native_jobs；可保留与math-fixture相符的software_math_only标记，其他source_mode拒绝。非空native字段不得通过外部标记洗成原生作业。

`combine_dielectric_contributions(born, electronic=None, ionic=None, *, electronic_path=None)`复用上述绑定；显式外部输入可由electronic_path或已保存source_path定位。主线在现有 `analyze dielectric --electronic` 调用传入真实electronic文件路径；在Study交付读取products后调用同一绑定函数，再执行模式/context/方法检查。无外部字段的旧math输入无需新增路径。

组合结果新增 `contribution_provenance`：electronic为空时null，否则为 `{provenance_kind, source_path, source_refs}`，外部用external_supplied，旧数学输入用software_math_only；ionic为空时null，否则为 `{provenance_kind:"derived_from_born_gamma", born_source, gamma_source}`，原样复制已有来源。该字段描述来源，不新增资格或虚构native_jobs。电子、离子原记录仍完整保存在原字段。ε∞和离子增量只按既有代数组合；缺任一贡献时epsilon_static继续null。

## Study交付规则

全局请求source_mode仍只有native_source_bound/software_math_only，表示Born/Gamma主链，不能把external_supplied加入全局模式集合。Born、Gamma、ionic保留现有原生校验；只有electronic可返回external_supplied的贡献分类。只允许这一个例外与匹配的主链共同交付，不开放任意混合模式。复合dielectric的主链模式由其非外部子贡献或既有context方法确定，仍须与已验证Born/请求匹配；external子贡献必须通过同样的外部检查。

没有external标记的native electronic依然被拒绝为未有producer合同，不能删除这个拒绝分支。父Study、模型、原子顺序、胞/体积、物理方法、单位和边界仍必须匹配。外部文件来源不豁免跨方法差异。保存dielectric与显式电子/离子产品一致性检查继续保留，包含新增来源，不允许保存结果覆盖请求来源。

交付的每项product_status/source_paths应反映实际贡献类别：electronic为external_supplied且包含source_path/source_refs；Born/Gamma/ionic仍保留各自原模式；组合结果保留逐贡献provenance，不能仅靠顶层native_source_bound把电子贡献表述为原生。顶层native_jobs只收集通过既有验证的Born/Gamma任务，外部输入不增加任何native_job。原始method和输入资格完整保留，交付资格仍false。

## 验收

所有数值/软件验收经v100 Slurm：每项1CPU、0GPU、2GiB、最多10分钟、no-requeue。只选新增精确pytest node IDs，先collect-only保存并核对，然后执行一次；失败定位后只验证受影响项。不得重跑197数学、247/249/250、旧测试或完整宿主。

复用197保存的math electronic/Born/Gamma/ionic，在新报告副本给电子输入明确外部标签；保留原2I、math-fixture方法、模型和math://引用，不冒充CZO/ABACUS，不重算Hessian或离子张量。公共集成只运行改变后的组合CLI及一次Study交付，验证路径/分类/参数值/未资格状态。原生主链+外部电子的路由单测若stub原生reader，必须明确software_contract_only，不生成虚假生产证据。

覆盖正确接入、显式来源与路径冲突/缺失、伪native字段、未声明外部的非数学输入、上下文/方法/单位/边界冲突、保存子记录冲突、缺离子时null以及native_jobs不被外部增加。既有原生Born缺项证据只读复用，不补数学ε∞。完整真实材料电子/总介电、原生ABACUS producer、完整Born/Γ及物理分支继续未完成。
