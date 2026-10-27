# P5 下一就绪系统切片只读评审

2026-10-23，Asia/Shanghai。范围：PLAN、当前源码及保存证据；没有运行测试、科学后处理、DFT/MD/训练，也没有改产品、计划或发布副本。本次只新增本文。主线通知 producer249、Gamma247、installed250 已通过，0.27收尾中；不以较早 PLAN 历史段落替代这项最新状态，也不重复上述验收。

## 建议结论

下一项可冻结为：**显式外部 ε∞ 张量的来源分类及同一 Study 交付**。它是现有电子贡献输入与公共交付之间的具体缺口，不是 ABACUS 原生电子介电 producer。当前可以做软件输入/来源/消费验收；没有已获选定的真实 CZO 外部 ε∞，因此不能宣告真实材料电子/总介电已完成。

若下一合同要求必须实现“ABACUS 原生晶体 ε∞”，则目前没有就绪实现项：缺本机确切可用的计算路由、原生输入/输出格式和示例证据。不应先创建空 writer/parser，不能借 slab 外场或隐式溶剂结果冒充体材料 ε∞。

## 具体断点与最小修改建议

1. `mlcc-agent/src/mlcc/cli.py:441-445` 的 `analyze dielectric --electronic` 已读取外部 JSON；`dielectric_response.py:_electronic_tensor`（722）检查父模型/Study、原子顺序、晶胞体积、物理方法、dimensionless、fixed_E_zero、fixed_cell、clamped 和 source_refs。`combine_dielectric_contributions`（751）复制外部电子记录，组合已有离子增量。这里没有 ABACUS 电子张量执行/解析，也没有原生作业的证明。
2. `property_delivery.py:882` 只有 `native_source_bound`、`software_math_only` 两种全局来源模式。`_p5_declared_mode`（1325）由 method.engine 推导模式，并要求子贡献模式一致；`deliver_p5_properties`（1736）再次要求每个产品与请求模式一致，1809对 native electronic 明确抛出 `NotImplementedError`。所以，一个与原生 Born/Γ 同上下文、同方法、但通过外部文件提供的 ε∞ 无法如实表达为第三种来源再进入同一 Study：不能贴 software 标签混过原生链，也不能贴 native 标签假装已有 producer。
3. 这不是“遗漏所有来源路径”：`deliver_p5_properties` 已在1755附近读取 product_paths，并在返回中保留 product_paths/request_path；`_p5_source_paths`（1391）也保存 electronic.source_refs。**不要为继续而再加一套路径包装、registry 或 CLI。** 缺的是外部输入的来源语义及组合交付规则。

建议主线冻结一个仅作用于 electronic 的显式外部输入标记（字段名由主线决定，例如 provenance_kind=external_supplied），与计算方法身份分开：谁提供张量，不等于计算使用何种 engine。保留外部文件路径、引用、原始 method_identity、上下文、单位/边界和资格；缺真实来源不得升级为 native。Born/Γ 仍用原来的 source_mode 和 native 校验；只允许已显式声明且匹配的外部 electronic 与其组合，输出逐贡献来源，保留 native_jobs 只来自真实原生任务。不要全局允许任意模式混合或删除现在的伪 native 拒绝分支。

最小产品修改位置预计是 `property_delivery.py` 的 `_p5_declared_mode` / `deliver_p5_properties` / 合成产品来源判断；`dielectric_response.py` 只在必要时透传明确来源描述，不改张量代数。现有 JSON/CLI 可承载电子记录，不需要新命令、新引擎、新任务框架。实验文献张量若不能匹配现有物理方法/模型，不自动豁免其差异；跨方法对照另立合同，本切片只处理同上下文的显式外部输入。

## 已有数据与可验收边界

| 保存来源 | 实际内容 | 可复用范围 |
|---|---|---|
| `workspace/reports/p5-v017-integration-v001/installed-197/software-math-positive/electronic.json` | two-mass-spring 数学案例的2I、`engine=math-fixture`、`source_refs=[math://p5-electronic/2I]` | 外部文件消费/来源分类的软件输入；原样保留数学身份，不能改名成CZO或ABACUS材料张量 |
| 同目录 `born.json`、`gamma.json`、`ionic.json`、`dielectric.json` | 已保存的完整数学参数链与未资格输出 | 复用数值，不重算Γ/旧矩阵；只检验改变的输入分类/交付路径与已保存值一致 |
| `workspace/reports/dielectric-response-v001/job-194/born.json`、`ionic.json`、`dielectric.json` | 原生Berry来源已读取；20原子60列Born均缺，三个介电量为null | 原生来源、不完整输入及未资格状态保留；不向该材料补数学ε∞ |
| `workspace/reports/phonon-force-source-handoff-v001/execute-249/fixtures/test_collection_native_task_re1/phonon-source-fixture/collection.json` | 实际collector产物，来源路径完整但明确software fixture且blocked | 已交回0.27的来源投影证据；本建议无需再运行collector |

验收应限定新增来源选择/拒绝规则，以及一次变化后的公共交付：外部标签/文件路径/引用保持可追踪；不产生虚假的native_jobs；缺离子增量仍null；同Study/模型/单位/边界/方法不符仍拒绝；无来源或谎称native的电子记录仍拒绝。使用精确新增node ID、先Slurm collect-only核对，再执行一次；不要重跑197数学、249或完整宿主。native Born与外部 electronic 组合的路由测试如需软件stub，必须明确标为software_contract_only，不计为真实CZO正例。

真实材料恢复条件：用户选定一个可用的外部电子张量及准确来源、模型/相/条件、物理方法、单位/边界；或者另行取得本机真实原生producer证据。未取得时，工程来源接口可独立验收，材料ε∞/总静态介电资格保持未完成。

## Born 与 Γ：没有发现需要抢先重写的消费链

- `dielectric_response.py:aggregate_born_columns`（336）已有保存响应→列→全张量路径；`_validate_native_sources`（250）检查来源，`_column_from_response`（299）只消费显式Born列，不推测分支。`berry-response-native-v001/berry-response-results.gpu-v002.json` 的六个180–185来源已有，但响应仍为unresolved_missing_branch、Born列null；194已正确交付60列缺项。恢复需要可审计物理分支/绝缘路径依据及显式整数；填满全部列还需要其余原子/方向的数据。不能自动设零分支或为了系统开发重跑材料矩阵。
- sibling child Studies不直接满足`polarization.py`顺序单Study路径，是`berry_response.py`明确声明的边界。现有`berry_response_results.py`已走独立位移响应消费者并连接Born；不应为绕过科学缺项而放松Study身份或另写并行适配层。
- `phonon_gamma.py:compute_gamma_fixed_cell_hessian`（701）及`dielectric_response.py:calculate_ionic_dielectric`（575）已有Γ Hessian→离子贡献的消费路径。0.27已补collection任务路径传递。`phonon-gamma-native-source-v001/job-198/existing-missing-forces.json`仍是实际保存的incomplete/blocked集合，缺15个期望条目；完整原生Γ缺的是力集合，不是再加一个source-list函数。
- `phonons.py:compute_harmonic_qpoints`及Γ适配当前`with_eigenvectors=False`。模式本征矢/分解是另一个可扩展功能，但不是已有固定胞Hessian伪逆离子增量的前置，也不是本轮最小输入/来源断点；暂不以它替代已有链路。

## 原生 ε∞ 能力证据的限度

`docs/p5-native-response-capability-20261022.md`明确区分锁定v3.10.1 tag源码与v100 conda构建，recipe patch尚无逐文件映射。该审查在锁定源码/文档/示例中未找到已验证的PW晶体ε∞/Born/DFPT producer；`efield_*`为slab锯齿势，`module_surchem/cal_epsilon.cpp`为隐式溶剂，不能移作周期体电子张量。该结论是“当前没有可用工程证据”，不是“所有安装补丁或版本绝不存在能力”。本次不重新运行引擎探针，也不把新网上文档当作本机能力。

因此下一原生producer合同至少还需要：实际执行文件与源码/补丁的对应关系、支持的明确输入路线、含单位/张量方向/离子边界的真实输出样本，以及同一Model/Study/方法/Slurm来源。现有普通SCF力/应力、Berry极化、完整数学ε∞都不能填补这项证据。

本报告只建议主线冻结一个有现成输入消费函数的小范围来源合同；未批准任何真实外部材料张量、DFT或新科学矩阵，未接受新版本。
