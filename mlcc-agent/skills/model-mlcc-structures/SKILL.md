---
name: model-mlcc-structures
description: 从已选择的晶相构建显式超胞、多元素占位与补偿模型，并保留后续 DFT 和 MD 的原子谱系。
---

# 显式原子建模

`plan-configurations --request <JSON> --models-output <新根目录> --output <集合JSON>`消费`mlcc.composition-configurations-request.v1`：`composition_request`沿用M1计量/子晶格/补偿，`max_configurations`是显式数量上限，每个`configurations`成员给出configuration_id、seed、新Study/reference/child身份。PCG64按稳定排序的允许位点无放回分配，固定补偿位点先保留；保存算法、库版本、seed、候选池和实际位点。不同seed可能重复构型，不重抽或冒称SQS。集合经`deliver-properties --composition`绑定父Study；各子build沿用自身Study交付。

`import-sqs --request <JSON> --models-output <新根目录> --output <build JSON>`调用外部构型导入，schema为`mlcc.sqs-import-request.v1`，也含`composition_request`。外部格式、逐source_index到父atom ID/重复像/子晶格映射和Å容差必须显式；保留实际外部晶胞、坐标与原始来源/相关函数/停止信息。缺质量证据保持not_evaluated，格式工程样本不能声明真实SQS优化。导入返回现有M1 build，直接使用同Study `deliver-properties --composition`，不运行SQS搜索器。两入口的模型生成与数值检查均经Slurm，合同见`docs/composition-configurations-m4-v001.md`。

`plan-composition --request <JSON> --models-output <新模型根目录> --output <构建产品JSON>`接收`mlcc.dopant-composition-request.v1`。请求显式给出父模型/Study、新参考与子模型身份、整数`repeat_matrix`、`max_atoms`、子晶格和允许atom ID、组分整数个数或有分母的浓度、逐点`parent_atom_id/parent_image`以及补偿账。分母可选`sublattice/all_atoms/explicit_cation_set`，个数必须精确可实现。形式价态及来源用于核对替位/空位/间隙的离子计量差，电子补偿和净电荷独立保留；缺补偿依据则保存unresolved参考与计划。已解析请求复用现有超胞/缺陷函数，产出实际组成、dopants、两级lineage和新子Study。`deliver-properties --study <构建产品中的study_path> --composition <构建产品JSON> --output <交付JSON>`接保存交付。生成与数值检查经Slurm；当前只做显式选点，不自动选位、舍入、扩胞或生成随机/SQS配方。

`create-interface --side-a <模型目录> --side-b <模型目录> --request <JSON> --output <新目录>`从两个明确的已定向周期模型构建层叠界面。显式输入每侧target_cell、整数repeat、周期切口、面内平移、两个周期间距和边界；不自动匹配、选终止面或修改母相。模型、layered-interface.json和逐原子双源谱系一起保存。`bind-interface-study --model <目录> --request <JSON> --output <新Study JSON>`绑定两个已给定父Study及新模型。几何字段与定义见`docs/p11-layered-interface-contract-v001.md`。首切片仅提供三维周期atomic/metal输入，所有几何生成及数值检查在v100 Slurm执行。

本版已实现 Python `import_model_artifacts` 与 `mlcc import-model --request <JSON> --output <新目录>`，接受明确的本地 CIF、POSCAR、extxyz 满占位周期晶体。还保留 `build_nickel_fcc_fixture`、模型回读和 VASP/ABACUS 原子排序映射。生产选相与掺杂系综仍按用户输入逐步实现，尚无建模 MCP。

0.8.0 增加 `derive-supercell --parent <目录> --request <JSON> --output <新目录>` 与 `derive-defect`。超胞要求显式正行列式整数 repeat_matrix，保存 parent_atom_id/parent_image；缺陷要求显式 vacancy/substitution/interstitial 操作和整数 charge_state，按 atom_id 选位，不推断补偿或随机构型。新模型不复用父身份，仍未弛豫/未生产资格。冻结0.9.0的ABACUS入口拒绝带电；0.10.0候选允许显式输入资格下的固定胞PW/nspin1/fixed正偶数目标电子SCF，模型q必须与方法q一致，尚无真实带电原生验收。派生 source.cif 是生成子结构参考，父源通过 parent_source_ref 保留。exact 扩胞复制原有缺陷图样，不代表重新采样。

先列化合物候选和相：顺电机制可用 CaZrO3/SrZrO3/MgTiO3，铁电基准可用 BaTiO3；BST/BZT/BCTZ 先确定组成。记录来源结构、胞设置和工况，让用户选择相，不用 C0G/X7R 代替结构。弛豫后的实际对称性与指定母相分别记录。

周期表选元素后，明确子晶格、价态、补偿、目标/实际子晶格浓度及整数个数；不从元素名推断唯一占位。A 位三价施主不能默认用正氧空位补偿；B 位受主与缺陷复合体另定义。

pymatgen 导入和占位，ASE 统一原子对象/导出/扩胞。保存 source.cif、model.extxyz、model.json、dopants.json、稳定 site/atom ID、父关系、种子和资源来源路径/版本。DFT 使用整数显式原子，不是分数占位 CIF。

分别定义最大分散、无约束随机、SQS、团簇与偏聚。最大分散不是无偏随机；SQS 不证明热力学平衡。比较周期最小像/配对统计与多个独立构型；一个掺杂原子不能证明胞内分散。暴露稀浓度/补偿所需的真实胞尺寸和成本。

父模型 exact 扩胞会复制掺杂图样；另行大胞重随机化必须新建派生模型并保留组成/补偿/种子。含真空 slab 的面内扩胞与实体增厚分开。

VESTA 仅作人工查看。错误直接说明，不替用户换材料/相，不做哈希校验或自动修复。

DFT k 网格与电子阈值由 study 所用的显式方法配置给出，不在通用建模函数里固定数值。原始输入、展开后的源结构和工作结构分别保留。多 block/frame 必须显式选择 source_index；已有 atom_id 不得重排重编号。等价晶胞变换须记录整数 unimodular 矩阵、平移、目标晶胞和审计来源，检查逐原子对应，不只修改晶相名称。
