# MLCC 0.28.0：外部电子介电输入与 Study 交付

2026-10-23：0.28.0已启用冻结，0.27.0回退，源码0.29.0候选。安装job255 COMPLETED/0:0、3秒；registry/MCP/Python均为0.28，145个发布/安装文本文件直接一致。MCP入口未变，复用已有宿主证据；改变的CLI路径由255验证。

交付范围：在既有电子介电输入、组合与Study交付路径中，支持明确声明的外部ε∞，保留逐贡献来源。最终版本状态和原生job证据以[发布验收](../workspace/reports/external-electronic-integration-v001/acceptance.json)为准。

电子输入必须声明`provenance_kind=external_supplied`，保留真实method_identity、parent/原子/晶胞、source_refs、单位、边界和原资格字段。公共入口将实际输入文件绑定为绝对source_path，拒绝与已有路径冲突、未知来源、空引用或伪native任务。未声明外部的非数学电子输入不能冒充原生producer；既有数学输入身份保持不变。

Born/Γ主链的全局source_mode仍只有native_source_bound/software_math_only。外部类别仅用于电子贡献，不能放松Born/Γ的任务/方法/单位/映射来源检查。组合结果分别记录电子与离子来源；Study交付记录外部文件和引用，native_jobs只由已验证原生任务贡献。保存组合与显式输入不一致时拒绝。缺离子贡献时总介电保持null，完整张量也不自动获得科学资格。

输入端job252和消费端job254各14个新增用例通过；前置251/253只收集精确测试清单。旧测试执行数为0。消费测试的原生主链路由使用明确software_contract_only reader stub，不是材料证据。

安装验收只复用197保存的数学电子/Born/Γ/离子张量，新增外部来源标签后运行两个公共命令：dielectric、deliver-properties。原2I、math-fixture方法、模型、math://引用和已保存张量保持；没有重算Γ/Hessian或离子响应。软件输入接口就绪不代表真实材料ε∞、完整Born/Γ或总静态介电已完成。

本轮未运行DFT、MD、训练、材料精度矩阵或完整宿主旧验收。原生ABACUS电子介电producer仍缺确切可用路线和原生输出证据，保持未完成。后续新ABACUS任务另参考[使用提示](abacus-practical-tips.md)，该提示不改变本轮范围或历史协议。
