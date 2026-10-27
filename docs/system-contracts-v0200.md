# MLCC 0.20.0：静电势原生来源与公共入口

2026-10-23。**0.20.0已验收、启用并冻结，0.19.0回退，源码进入0.21.0候选。** 本次交付是MLCC系统的静电势输入、原生输出和来源传递，未进行MACE材料精度优化。

## 本次实现

- 方法配置唯一入口为顶层`output_control: {"out_pot": 2}`，通过现有`prepare_abacus`及`create-abacus`生成INPUT，保存method/TaskRecord预期产物。未请求时保持原行为；误放字段或不支持的输出类型明确报错。
- 限ABACUS3.10.1、PW/NC、固定胞SCF、非SOC共线nspin1/2，无外场、偶极、栅极或溶剂；本次真实实验只覆盖中性nspin1固定占据。输入资格沿用已有NC证据。
- `read_abacus_electrostatic_cube`保留原生标量、Ry、Bohr、原点、三网格步向量和z最快顺序；`read_abacus_electrostatic_task`核对自身任务的Slurm终态、电子收敛、方法、INPUT/OUT.INPUT、模型、Study、STRU/原子映射、版本和精确产物。
- 公共入口：`mlcc electrostatic-potential --task <任务目录或task.json> --output <JSON>`。所有数值后处理在v100 Slurm执行；现有runner、七MCP和MatterAI Bundle架构不变。
- 势的定义为离子局域势加Hartree，单位Ry，符号为电子势能；不含XC或非局域赝势。Hartree G=0为零，离子局域势零点保留，未减EF、均值或真空值。结果不等同正电荷电势。

## 实际验收

| 环节 | 原生job与终态 | 验收范围 |
| --- | --- | --- |
| 新reader | 203，COMPLETED/0:0，1秒 | 24项格式、单位、非正交网格、映射、打印精度及软件来源拒绝检查；不当作原生正例 |
| 新writer及输入准备 | 204，COMPLETED/0:0，1秒 | 11项定向检查，通过现有创建器准备唯一宿主任务 |
| 原生GPU输出 | 205，COMPLETED/0:0，33秒，UNLIMITED | 既有CZO Pnma中性20原子；原生电子收敛，产生ElecStaticPot.cube；1V100、1MPI、1请求CPU、8GiB，time=0/no-requeue |
| 安装公共入口 | 206，COMPLETED/0:0，4秒 | 安装0.20副本执行一次新task结果解析、一次同task电子解析、一次公共势入口；来源均为205 |
| MatterAI原版宿主 | passed | 加载0.20及七MCP声明，一次只读mlcc_list_tasks调用；registry/MCP/Python精确版本一致 |

原生势网格为72×72×100，20原子的元素分组顺序还原至源atom_id；native_output_observed和native_GPU_accepted为true。GPU证据同时保留实际Slurm TresPerTask、OUT.INPUT device和V100硬件清单。声明的旧物理/数值配置保持PBE/原NC/100Ry/2×2×2/88bands/scf_thr1e-4/scf_nmax100；唯一新增DFT为205，没有材料网格加密、重选势、MD或训练，也没有重跑冻结版本测试。实际电子收敛不等于该配置取得生产精度资格。

输入生成、解析以及安装验收使用有限CPU墙钟；DFT没有墙钟限时。执行前协议、审阅、原生命令/状态/文件和安装报告均在[交付目录](../workspace/reports/electrostatic-source-integration-v001/)。[最终验收](../workspace/reports/electrostatic-source-integration-v001/acceptance.json)、[安装验收](../workspace/reports/electrostatic-source-integration-v001/installed-206/acceptance.json)、[reader检查](../workspace/reports/abacus-electrostatic-potential-v001/acceptance.json)。

## 未完成边界

单个宿主势不能建立host/defect公共能标。势对齐、aligned VBM、FNV/eFNV和带电形成能保持null，科学/生产资格false。化学势参考源、介电屏蔽、尺寸检查，以及完整Born、原生Γ力集合/端到端、电子epsilon_infinity仍缺。不得用总能差、费米差、电荷密度或数学样例填补。

下一最小工作是审查并接通P4化学势的原生参考来源，复用现有热力学/中性形成能函数和已保存输出。缺少相或组成选择时显式保留缺项；没有经审阅协议不新增DFT。MACE/CZO约2.708GPa误差继续后置，不阻断系统开发，不改成科学通过。

发布与安装127个文本文件直接一致，未做哈希。旧0.10删除审批阻断不变，0.11–0.18旧软件副本待退役；本轮无删除，保留科学证据及共享0.9环境、0.15依赖/构建工具，不能声称磁盘已只剩两版。
