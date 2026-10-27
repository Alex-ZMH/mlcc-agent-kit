# M4 显式随机占位与外部构型导入合同

2026-10-26。用户已在监督聊天要求继续未完成实际功能；主线已核实该原始 userMessage。基线0.50启用、0.49回退，源码0.51。复用537–539，不重复已通过路径，不新增DFT/MD/训练/SQS搜索。

## 所有权与范围

- 原实施窗口：`composition_configurations.py`、对应新测试；必要的 `dopant_composition.py` 最薄复用点；唯一共享 CLI/property_delivery/Skill 接线。
- 第三窗口：`composition_sqs_import.py`、专属新测试、外部格式示例和独立消费脚本；不编辑 M1、CLI 或交付文件。
- root：本合同、输入/资源决定、统一 Slurm 验收、集成与最终审阅。COMSOL环境仅定向只读核查，由 Luna 执行；不为缺环境重做参数出口。

两实现必须复用 M1 原有计量、形式价态/补偿账、结构读写、超胞谱系和实际组成语义，不建立新任务/来源/资格框架。若需抽出 M1 计量公共函数，由原实施唯一编辑并及时交给第三。不得为随机占位伪造一份临时显式位点来绕过计量检查。

## 共享输入语义

母体沿 M1 的 `parent_model={model_id,version,path}`、`parent_study`。超胞沿 `repeat_matrix` 和 `max_atoms`，以真实加载母体的 atom IDs、元素和 ASE 超胞映像确定容量；不假定原子ID连续，也不假定矩阵对角。

沿用 `sublattices` 的 `id/allowed_atom_ids/allowed_parent_elements`，`components` 的 `element/sublattice/count` 或精确有理数浓度，及 `compensation` 原合同。未被替换的位点保留母体元素；不把“替换数量”误作所有元素的最终分数。物理位点唯一键仍为 `(parent_atom_id,parent_image[3])`，不同子晶格标签不使同一物理位置变成两个位置。

构型入口包装现有 M1 请求，并把所选占位编译回原有 `site_assignments`，每项仍为 `sublattice,parent_atom_id,parent_image,element`。材料配方、研究参数来自请求；本轮工程样本明确 fixture，不使用待定Dy/Ho提案。

## 随机分配

建议公开函数 `build_composition_configurations(request_path, output_directory)`，公开命令 `plan-configurations`。

请求采用 `schema=mlcc.composition-configurations-request.v1`、`composition_request`（现有 M1 请求模板，位点由本入口生成）、`max_configurations`，以及有限的 `configurations` 列表。每项显式提供 `configuration_id,seed,study_id,reference_model,child_model`。不代用户生成seed序列或无限尝试；列表长度不得超过显式预算。

seed仅控制这次确定的有限分配；保存算法名、运行库版本、种子和原始/排序后的候选位点。先保留明确补偿操作的物理位置，再在允许候选中无放回选择；每个子晶格的每元素计数必须精确。重叠子晶格存在歧义时明确拒绝或要求互斥的实际候选，不用循环重试寻找成功分配。

不同seed可能产生同样构型，保留该事实，不重抽、不伪造独立样本或SQS质量。固定seed与同一输入应有相同占位；重现检查只比较新算法必要行为，不重跑旧M1测试集。

输出集合保留父Study与各构型的现有build/child Study引用、完整位点和谱系；集合不是一个新的科学计算任务，native job仍null。集合交付绑定父Study，每份子build仍绑定自己的子Study。

## 外部SQS候选导入

建议公开函数 `import_sqs_configuration(request_path, output_directory)`，公开命令 `import-sqs`。优先一个可复用现有reader的确定格式（extxyz等），或在已有reader确实支持时接ATAT；不自行实现另一套SQS生成算法。最终格式/API由第三短交接固定。

沿用同一个 `composition_request`。额外提供明确外部结构路径/格式、来源说明，以及逐原子 `source_index → parent_atom_id,parent_image,sublattice` 映射。source_index以声明的0基外部文件顺序为准；不采用元素排序或最近邻自动猜谱系。晶胞、映射坐标容差按请求的Å单位显式给出，和SCF阈值无关。

校验实际文件的晶胞、坐标和元素占位与给定母体/重复矩阵/计量一致。最终模型须保留实际外部结构的坐标及其文件来源，不能仅读取元素后丢弃或静默投影外部几何。若首版限定固定母格替位，明确记录该范围，超出范围报原始原因。可不支持间隙/非晶格构型，不得假装已支持。

可附外部工具名/版本、生成参数、原始相关函数或目标函数文件、停止状态。原始文本原样保存。缺相关输出记 `correlation_assessment=not_evaluated`，工具/job未知保持null。导入证明的是结构/来源可消费，不证明SQS优化质量；格式fixture必须显示 `engineering_fixture`，不能声称真实SQS作业。

保留M1实际组成、parent/reference/model/Study和原子谱系字段；公共交付由原实施串行接入，第三不编辑共享文件。两方先固定稳定函数签名及输出schema后再接线。

## 单次合并新路径验收

所有模型生成与新数值检查在v100 Slurm。声明预算：CPU1、GPU0、内存4GiB、10分钟、no-requeue；纯构型/输入与保存交付无需GPU，也不运行计算引擎。首批最多3个小规模随机工程构型、1份明确外部格式工程输入，单构型不超过32原子，不扩大材料范围。

上述3/1/32为本轮验收样本预算，不是通用库硬限制。通用入口按调用者明确给出的 `max_configurations` / `max_atoms` 执行。

只运行新增检查：精确计量/seed复现/子晶格与补偿位置、非对角映像/原子ID、有限数量、冲突原始错误；导入顺序/来源/缺相关信息、外部坐标与计量绑定；一次新公共生成与保存交付。可用数学/格式fixture证明接口，但不能将它标为外部真实优化产物。

通过后最多一次必要安装入口检查，只核新命令绑定/实际参数解析/保存交付，不重建模型。失败保留真实job终态；主线先审因，只补改变行为与尚未运行的路径，不自动重试或重跑通过项。

COMSOL若无可在v100 Slurm使用的运行环境，保留已交付文件及明确缺口，不阻塞M4。若环境存在，另由root声明只读入538现有材料/函数的预算，不重生成出口、不器件求解、不安装或购买许可证。
