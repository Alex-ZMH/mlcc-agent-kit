# P5实际位移响应切片

2026-10-22。源码0.15候选，启用0.14保持冻结。本切片以可运行系统链为终点；测试构型的数值精度及材料生产资格分开记录。

## 执行路线与边界

固定胞、显式原子Cartesian位移模型 → 各点SCF及原生收敛 → 对应电荷的指定gdir Berry NSCF → 原生解析 → 显式分支极化差及中心有限差分 → 可用方向的响应交付。沿用已有ModelArtifacts、TaskRecord、SiteRunner和解析器，不增加调度框架。

SCF与NSCF分两步创建。NSCF必须绑定该点实际收敛的SCF，不得用计划状态、输入生成或其他结构的电荷冒充依赖。各点有独立child Study/model/task，公共parent Study和parent model显式保存；不伪造同一Study选择多个不同模型，也不将正负位移兄弟模型改成父子。

参数必须显式指定atom ID、位移向量/Å、模型和Study标识、gdir、电子收敛控制及资源。固定原子ID/元素/胞/总电荷和方法来源；不自动选择相、掺杂、位移幅度、Berry分支或CPU执行。GPU候选未获原生证据前只标待验收。

## 响应量合同

ABACUS固定v3.10.1文档规定：gdir对应晶格方向；每方向原生值投影到Cartesian后，三个方向贡献相加才构成完整极化。不能将gdir1/2/3直接当x/y/z，也不能用缺失方向补零。[官方版本文档](https://github.com/deepmodeling/abacus-develop/blob/v3.10.1/docs/advanced/elec_properties/Berry_phase.md)

对相同父模型中同一原子、同一Cartesian轴的显式±δ位移，使用调用方声明的整数分支P+nQ，求中心差分dP/du，单位C/m²/Å。缺分支则对应导数为null。三个gdir齐备后才能求完整Cartesian导数及Born的一列；Born定义为Z*=(Ω/e)∂P/∂u，行是极化方向、列是位移方向。[公式来源](https://www.fhi-aims.org/uploads/manual/Ch3/S42.html)

由Å单位转为无量纲电子电荷单位的因子为Ω(Å³)×10⁻²⁰/e(C)，其中e=1.602176634×10⁻¹⁹ C。只得到一原子/一位移轴时不声称完整Born张量；显式分支也不自动证明路径绝缘性、分支连续性或微分极限收敛。工程数据流通过和这些科学资格独立记录。

电子介电、离子介电和完整静态介电分别留为未完成。当前ABACUS3.10.1原生锯齿外场是slab边界功能，不产生本项目所需体相介电张量，不能用E_efield能量项代替。

## 范围与所有权

- Luna `neutral_energy_contract`：新berry_response.py、对应tests、生产者manifest/输入检查脚本。
- Luna `md00_public_entry`：新berry_response_results.py、对应tests、有限差分结果合同；与生产者同步manifest字段。
- Luna `berry_gpu_variant`：既有berry_tasks.py/berry.py的显式隔离GPU候选登记与原生device解析，及变化行为测试。
- 主代理：科学审查、CLI/property_delivery接线、Slurm提交与真实任务、集成/发布/计划。已通过0.14功能不重验。

软件检查、模型生成、科学后处理均在v100 Slurm运行。新真实DFT显式time=0，GPU优先；首次补丁原生验证仅复用host50电荷、保持原gdir1物理输入，用隔离候选运行。CPU58只读对照不重算，不追加收敛或温度矩阵。

## 后续电子介电的可复用候选

本次主源检索发现ZStar/PYATB已有ABACUS位移响应和电子介电流程。[作者论文](https://arxiv.org/abs/2609.16802v2)及[源仓库](https://github.com/xdzhu/ZStar)登记为下一独立适配审查候选。其ABACUS路线需要NAO/LCAO的H(R)、S(R)、r(R)矩阵、匹配轨道和明确方法；当前PW50/58没有这些输入。本切片不安装、不自动切换基组/引擎、不混合既有PW标签；后续优先审查可复用原函数，避免重写介电求解器。该登记不等于已实现或验收。
