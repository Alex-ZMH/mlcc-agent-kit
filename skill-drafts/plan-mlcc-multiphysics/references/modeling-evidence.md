# 开源建模与 MS-MCP 方法核实

核实日期：2026 年 10 月 20 日。这里只读检查了相关资料和本地脚本，没有启动 Materials Studio、调用队列或改动 FeOCl 项目。

## FeOCl 实际使用的方法

本地可检索项目为“FeOCl项目整理与拆分”，其归档合同列出原始跨尺度项目。迁移后的相关文件位于 `D:\project\跨尺度计算`。

已读的 `validate_cif_in_materials_studio.pl` 调用 `MaterialsScript`，导入 CIF、读取原子并导出 XSD。它证明本地具备 MS 原生导入/往返验证方法，不意味着存在一个已公开的 MLCC 开源 MCP。

`C:\Users\ironman\.codex\skills\build-feocl-solvation-models\SKILL.md` 和配套 `randomize_substituent_sites_xsd.py` 进一步表明：初始结构由 MS/MS-MCP 准备，之后由确定性脚本重构 XSD、选择位点、填充溶剂和导出。随机器对 FeOCl 两侧表面设置 2/3 位点分配，并以最大分散加种子打破并列；它不是无约束均匀随机选择。

适合迁移的做法是：母体来源固定、可复现种子、显式位点列表、对照用相同几何假设、导出回读检查、独立保存原生与派生文件。不迁移 FeOCl 的五位点比例、P1 盒子、价态/磁性设置或将最大分散默认视为所有掺杂的真实分布。

当前会话未暴露 Materials Studio 建模 MCP 工具，也未部署以下候选。接口调研与“现在可直接调用”是不同状态。

## VESTA

[官方介绍](https://jp-minerals.org/vesta/en/) 支持晶体、体数据、形貌显示、晶格变换和超胞等操作，适合检查结构、局部配位以及电子密度/极化相关结果。

[官方许可](https://jp-minerals.org/vesta/en/download.html) 表述为条件下免费使用，限制未经许可再分发；[官方手册](https://jp-minerals.org/vesta/archives/VESTA_Manual.pdf) 明确说明源码未公开。因此不把 VESTA 称作可自由二次开发的开源建模后端。

本次核实没有找到官方、完整的 VESTA 批量掺杂/任务编排 MCP API。VESTA 可以作为本项目的预览/人工编辑适配器；浓度整数化、价态补偿、随机/SQS 系综、来源追踪和 ABACUS/LAMMPS 输入仍由建模核心负责。统计占位 CIF 不等于已经展开为可运行的显式原子模型。

## 直接相关的开源组件

| 项目 | 已确认内容 | 本项目需要补什么 |
| --- | --- | --- |
| [pymatgen](https://github.com/materialsproject/pymatgen) | 结构、元素/价态、变换、表面/界面与分析；当前核心对象在 pymatgen-core 包 | MLCC 材料/相来源登记、指定占位/补偿和系综政策 |
| [pymatgen DopingTransformation](https://pymatgen.org/pymatgen.transformations.html) | 接受含氧化态的 dopant，并有位点/半径/枚举等参数 | 不将半径或 Ewald 排序当成占位/溶解性 DFT 证明 |
| [ASE](https://ase-lib.org/) | 结构操作、计算接口、优化/MD 等 Python 组件 | ABACUS 的实际适配版本与标签验证；不假设任意 ASE 安装有内置 ABACUS calculator |
| [icet](https://icet.materialsmodeling.org/advanced_topics/sqs_generation.html) | 依子晶格、目标相关和随机种子生成 SQS | 稀土缺陷复合体、偏聚和真实浓度条件需要另外定义 |
| [Atomsk](https://github.com/pierrehirel/atomsk) | CLI 原子模型处理；官方点缺陷教程给出随机选择后替位 | 电荷/化学、SQS 目标和全部模型谱系并非这条命令自动完成 |
| [AtomisticSkills](https://github.com/learningmatter-mit/AtomisticSkills) | MIT 许可，MCP/skills；结构查询、超胞、元素替换、MLIP/MD；README 的 DFT 路线为 VASP/ORCA 等 | ABACUS/LAMMPS 目标版本适配、位点级掺杂、补偿、系综检查、设备链参数接口 |

其中 pymatgen 是晶体数据/分析核心，ASE 是几何和计算器适配层，icet 提供相关函数/SQS 方法。不是每项都必需部署；先用最少组件完成相选择与显式掺杂导出，再按需求接入。

## AtomisticSkills 源码级判断

已经读取 [base_server.py](https://github.com/learningmatter-mit/AtomisticSkills/blob/main/src/mcp_server/base_server.py)：`supercell_expansion` 调用 pymatgen 的 make_supercell，`modify_structure` 使用 replace_species。后者示例包括整类元素替换和统计混合占位，不能由此认定已实现指定百分比、特定位点、随机/SQS 和补偿缺陷的显式超胞。

因此它是最接近用户所述“通过 MCP 操作开源原子建模”的参考项目之一，但不宜直接宣传为现成 MLCC 掺杂平台。若复用，其简单替换能力需要扩展为选定具体原子索引、补偿计数、构型系综和导出检查。README 提供的 DFT/MLIP 生态也不能替代 ABACUS 与 LAMMPS 的实际兼容验证。

本次没有审计其全部运行环境、所有工具、外部模型许可证和计算结果；采用前仍应完成一个限定范围的端到端算例。不会为了采用 MCP 而替换用户指定的 ABACUS/LAMMPS。

## 其他计算链的接口证据

- [ABACUS–Phonopy](https://phonopy.github.io/phonopy/abacus.html)：直接给出位移 STRU、ABACUS 力计算和 FORCE_SETS 路线。力常数标注不对位移结构继续弛豫。
- [ABACUS 最新关键词](https://abacus.deepmodeling.com/en/latest/advanced/input_files/input-main.html)：截至本次读取页面为 3.11.0-beta11；DFPT 的 epsilon_inf/Born/LO-TO 字段存在，同时明确 under development。列为能力探测项。
- [Phono3py](https://phonopy.github.io/phono3py/phono3py-api.html)：二/三阶力常数及晶格热导 BTE。与 ABACUS 的具体批量力/文件桥需要匹配版本验证。
- [LAMMPS 导热说明](https://docs.lammps.org/Howto_kappa.html)：NEMD、Green–Kubo 等计算路线；给出的示例势不代表 MLCC 势已合格。
- [openEMS](https://docs.openems.de/en/latest/intro.html)：开源全波时域电磁求解与 Python/Octave 接口，用于适用几何/频段的器件参数；不承诺原样解析全部纳米微结构。
- [ElmerFEM](https://github.com/ElmerCSC/elmerfem)：开源多物理 FEM，可作为器件/电热层候选，具体模块组合需验证。

## 材料与器件依据

- [C0G 高压 MLCC 技术说明](https://www.kyocera-avx.com/docs/techinfo/CeramicCapacitors/C0G-High-Voltage-MLCC-in-DCDC-and-OBC-Applications.pdf)：C0G 稳定性及 SCZT 的厂商案例，不支持把纯化合物直接认定成器件等级。
- [CaZrO3 结构记录](https://www.ctcms.nist.gov/~knc6/jsmol/JVASP-13829.html)：Pnma、No.62 及 20 原子胞。
- [CaZrO3 缺陷计算](https://pmc.ncbi.nlm.nih.gov/articles/PMC5559480/)：正交 CaZrO3 的空位、电子结构与缺陷热力学方法背景，不直接充当本项目参数。
- [BaTiO3 相结构研究](https://pubs.rsc.org/en/content/articlehtml/2021/ma/d1ma00651g)：不同结构/极性与温压相关性，具体相界受样品条件影响。
- [MgTiO3 晶体结构研究](https://www.sciencedirect.com/science/article/abs/pii/S221478531630089X)：钛铁矿 R-3 母体结构参考。
- [SrZrO3 晶格动力学](https://www.sciencedirect.com/science/article/pii/S0022369707005665)：相序及声子方法参考。
- [稀土占位](https://electroceramics.technion.ac.il/site-occupancy-of-rare-earth-cations-in-batio3/) 与 [稀土缺陷热力学](https://ceramics.onlinelibrary.wiley.com/doi/10.1111/jace.19168)：位点和补偿需按成分与条件研究。
- [Murata 阻抗/ESR 特性](https://article.murata.com/en-global/article/impedance-esr-frequency-characteristics-in-capacitors)：电容、ESR、ESL 与自谐振的器件关系。

用户给出的知乎页面本次抓取超时；方案中的产品分类和器件结论使用可核实的厂商资料与原始材料论文，不对该页面未读内容另作推断。
