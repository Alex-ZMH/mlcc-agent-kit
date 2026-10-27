# P11 首切片：双源周期层叠界面

固定实施范围：显式已定向的两侧周期模型→层叠模型→标准LAMMPS几何/参数输入与任务来源→同Study的输入交付。只生成模型和输入、检查新增数值路径；不执行新DFT、MD、训练、热流或加载矩阵，不宣称P11全部完成。主线管理版本/plans。

## 函数与复用

- `interfaces.build_layered_interface(side_a_path, side_b_path, request, output_path) -> ModelArtifacts`。复用modeling的read/write_model_artifacts与ASE原子对象；不调用或泛化旧单母晶界构造器。
- `interface_sources.bind_interface_study(model_path, request, output_path)`、`stage_interface_task_sources(study, model, task_directory, study_file=...)`、`read_interface_task_sources(...)`。只绑定显式Study、两源、原子谱系及不可变来源文件。
- 公共入口`create-interface --side-a --side-b --request --output`、`bind-interface-study --model --request --output`。既有create-lammps按layered_interface附带上述来源文件；prepare_lammps/export_lammps_data/validate_lammps_model和Slurm runner复用。
- `deliver-properties --interface <输入交付请求> --study ... --output ...`交付已有界面模型/可选已创建任务的来源与未计算状态，不计算响应。

## 显式几何请求

schema `mlcc.layered-interface-request.v1`，必须提供model_id、version、fixture、fixture_purpose、charge_state=0、boundary=["p","p","p"]，以及：

- sides.a与sides.b分别给出`repeat=[nx,ny,nz]`、`target_cell_angstrom`、`origin_shift_fractional=[x,y,z]`、`translation_inplane_angstrom=[x,y]`。
- 输入是已定向晶胞：a/b在xy平面、c沿正z，堆叠法向为+z。target_cell为调用方明确指定的形变后单胞，原子保持相对该胞的分数坐标；实际形变矩阵记录在产物。两侧repeat后的a/b必须一致，不搜索匹配胞或形变。
- origin_shift明确规定周期切口：源分数坐标减去该值后wrap到[0,1)，然后按整数repeat扩展；不自动选择晶面/终止层。
- `gap_ab_angstrom`和`gap_ba_angstrom`均显式给出，定义为相邻层最外原子平面沿z的距离。后者是周期边界处B→A间距。记录两个几何界面，不推断二者等价。
- `minimum_distance_angstrom`为显式几何重叠检查阈值；发现短于阈值的周期原子对直接报原错误，不删原子或自动扩大间距。

层的名义厚度由repeat_z×target_cell_c确定；占据厚度为该层最高与最低原子平面之差，两者分别记录。最终c长度为两层占据厚度加两个显式gap，不复制真空。首切片仅支持与现有LAMMPS导出一致的三维周期atomic/metal几何，不隐含开放面或三维NPT协议。

新原子ID全局连续且唯一；每个原子记录side、parent model/version/path、parent_atom_id/index、repeat image、周期切口映射及最终位置。parent_models恰好两项，分别保留父源相/材料/来源文件；CZO/Pnma与BTO/P4mm源身份不变。磁矩/电荷数组缺失时不补零；两侧原始值或缺失记录在来源，不能从Ni seed推断界面磁序。

## 产物和消费

标准model.extxyz/model.json/source.cif/dopants.json/atom-lineage.json，加`layered-interface.json`。spatial_mode=layered_interface，parent_models双源，source.cif明确为生成结构参考。几何构建状态与MD执行状态分开保存。

Study请求schema为`mlcc.interface-study-request.v1`，明确study_id/case_id/case_role和parent_study_refs，后者按a/b排列、每项含side/path/study_id，绑定生成模型及双源记录。条件由conditions显式提供，不继承父Study温程。task-local的interface-sources目录保存layered-interface.json、atom-lineage.json和两份父model.json并加入transfer_paths；两侧源方法分别保留，不合并为一个DFT标签。LAMMPS方法仍只代表显式选定势和协议。

输入交付请求schema为`mlcc.interface-delivery-request.v1`，提供model_path及可选task_path（指向已创建的task.json）。交付schema为`mlcc.interface-input-delivery.v1`，保留几何、两侧来源、原子谱系、已创建任务的显式method/protocol/potential/resource与真实状态，未有任务时task=null。组合胞的phase_requested为layered_interface_no_single_space_group；两侧P4mm/Pnma等原相仅在parent_models保留，不宣称组合胞具有某一母相的空间群。

无MD结果时牵引分离、界面热响应、局部热应力为null/not_calculated；不补tau、交叉势、原子电荷或响应。若已提供potential/protocol/site/request，沿用既有create-lammps生成未提交TaskRecord，保持scheduler_job_id=null；本轮不调用submit。材料缺项不阻塞几何和来源功能。

## 最小工程验收

使用已有Ni工程模型与已导入BTO/P4mm五原子源，构建明确标注engineering_fixture的输入演示。两侧target_cell的面内向量均显式为4Å×4Å，c分别保持3.52Å与4.0801979092Å，repeat=[1,1,2]、origin_shift=[0,0,0]、A平移[0,0]、B平移[0.25,0.25]Å、两个gap均2Å、minimum_distance=1Å。这仅为几何/映射接线参数，不构成用户生产界面选择；不优化Ni/BTO匹配或改变父相。

实际模型生成、几何/原子映射及native data回读检查仅在v100 CPU Slurm。首批只跑新增测试和公共入口；不重跑旧晶界测试、P8 job437、旧Ni验收或已导入BTO job361。若验收包含既有MACE候选势的静态输入生成，只读取既有模型文件并显式保留未选择生产用途状态，不执行run0或把bulk势视为界面势。

牵引分离、界面热传输、局部热应力、两高分子工艺分支及电边界响应仍为后续独立功能，本切片不覆盖。

## 参考边界

已阅读plans/stages.json的P11、PLAN.md、mechanics-workflow.md、modeling/model_derivatives/grain_boundaries/grain_task_sources及MD与聚合物逐函数迁移清单。上游通用MD/有机后处理不提供这个双源周期晶体构造器；保留既有runner，未复制其重试、资格流程或连续场方案。
