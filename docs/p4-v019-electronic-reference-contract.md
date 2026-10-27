# P4 0.19 电子参考来源与交付合同

2026-10-22。0.18仍为启用冻结版，0.19为候选。本切片是系统数据链工程验收，不建立材料生产资格。

## 分工与范围

- 既有实施聊天独占新 `defect_references.py`、对应单测及 `workspace/reports/defect-electronic-reference-v001/`。
- 主线拥有科学合同、首次50/121电子后处理、共享CLI/Study接线、集成与发布。Luna在主线下实现 `property_delivery.py`、`cli.py`、`test_defect_reference_delivery.py`；不得修改实施聊天模块。
- 集成证据目录 `workspace/reports/defect-reference-integration-v001/`。不新增DFT、MD、训练、势扫描或材料精度研究。

## 数据路径

复用50宿主与121中性O8空位的已完成原生任务，仅在v100 Slurm调用现有 `read_abacus_electronic_task` 一次，另存 `native-electronic/host-50.json` 和 `defect-121.json`。已有75/76/77/80电子JSON直接复用，不重复读取或积分原始能级。后处理资源为1 CPU、2 GiB、2分钟、no-requeue；有限时限仅用于后处理，不用于DFT。

独立消费函数接收保存电子JSON与缺陷描述符，保留原始task/result/method/Study/model/atom lineage和job来源。宿主须q=0并绑定描述符父模型；缺陷须绑定子模型与显式电荷。物理方法与数值协议均保留，差异显式报告；不得把带电任务与任意宿主宣布为已对齐同方法参考。

通过现有 `deliver-properties --defect-references REQUEST --study STUDY --output OUTPUT` 交付。请求schema为 `mlcc.defect-reference-delivery-request.v1`，字段为 `host_electronic_path`、`defect_electronic_path`、`descriptor_path`，相对路径以请求文件目录为基准。Study绑定缺陷任务；宿主Study可以不同，但模型谱系必须吻合。

## 数值语义与缺失状态

VBM/CBM/KS gap是各任务原生均匀采样网格结果，费米能是该任务SCF电子化学势参考。不同任务的能标尚未对齐。带电缺陷最高占据级不是对齐宿主VBM，不能据此给热力学转变能级。

`parent_energy_zero_eV`在既有电子结果中实际来自总能量，只保留为总能量来源；不能用作平均势。禁止用总能差、费米差、电荷密度或UPF局域势文本代替周期静电势场。

当前没有已定义的势文件、势网格、介电修正或化学势参考。势对齐、FNV/eFNV、带电形成能保持null，逐项保留恢复条件。不调用数学形成能函数绕过原生带电gate。既有 `potential_alignment_eV`是能量贡献，未来也不能重复乘q或与含对齐的总修正重复相加。

工程验收要求真实保存源→参考模块→公共CLI→Study交付路径正确，单位/方法/谱系/job/缺失与失败状态保留。软件数学fixture只验证行为。scientific/production qualification均false；无产品目标则design_assessment=not_assessed。缺失材料数值不阻塞该软件路径验收。
