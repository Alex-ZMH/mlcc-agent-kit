# 0.12 系统交付（已验收启用）

2026-10-22，0.12.0已通过v100安装副本job113（COMPLETED/0:0）、七工具MCP连接与原版MatterAI真实会话并启用；回退版为0.11.0，开发源码转0.13候选。0.10旧软件清理被自动审批拒绝，副本仍在，未执行删除；见[清理状态](../workspace/reports/system-v0120/retirement-blocked.json)。材料误差筛选未过不阻塞软件开发，也不改写为科学通过。

新增`deliver-md`沿同一个Ni Study串通原生任务45→现有workflow完成态/空依赖→MD-00 collection→MD-01显式窗口→MD-02来源→MD-06 thermo→property_delivery→可读结果包。没有混用CZO/MACE，EAM保留独立文献来源，不宣称由本项目DFT训练。真实请求选取50–100步的6个记录，输出温度样本均值180.53342075570822 K和全体系总能首末差4.2334518504105745e-6 eV；这些是工程观测，生产/平衡资格仍false。未新增MD/DFT或材料精度研究。

可读交付：[report.md](../workspace/reports/system-v0120/installed-113/ni-md-delivery/report.md)；机器结果：[delivery.json](../workspace/reports/system-v0120/installed-113/ni-md-delivery/delivery.json)；发布验收：[acceptance.json](../workspace/reports/system-v0120/acceptance.json)。真实命令、各阶段JSON、原生job和94文件发布/安装文本一致记录均保留于同目录。未知窗口不自动选全记录，错误Study/势拒绝交付，现有设计比较器对未资格观测量返回证据不足。

## 已具备证据的切片

| 项目 | 工程状态与证据 | 保留缺口 |
| --- | --- | --- |
| MD-01条件/窗口合同 | 模块109、入口111通过；安装纵向113消费显式窗口，沿用45/105 | 没有平衡、采样或材料生产资格 |
| MD-02来源选择 | 模块110通过；源码审查、公共入口及安装113消费通过 | 未建立replica独立性；不把来源集合当作统计聚合结果 |
| MD-06描述量 | 模块112的14项新增检查通过；安装113读取明确子窗口观测 | 平稳性、块统计、不确定度、时间步资格未实现 |
| 单Study交付 | 安装113的5项新增入口/交付检查和真实命令成功；原生记录未修改 | 完整P0–P12、科学资格与专用势训练仍未完成 |

MD-01来源函数、最小改动和资格边界见[逐函数移植清单](md-postprocessing-statistics-porting-list.md)，公共入口实证见[验收记录](../workspace/reports/md-conditions-cli-v012-v001/acceptance.json)。本轮不重跑冻结版本、MD-00/MD-01旧检查或原生MD/DFT。

## 下一最小开发

晶体缺陷优先补齐真实中性host/defect能量来源链：先审查现有job50能否按原生输入、模型谱系、同方法和同胞条件复用，仅为确实缺少的数据制定任务。化学势缺失时可交付原始能量与原子增减，但形成能必须为空，不填造参考值。此项当前为方案审查，不表示新DFT已经提交或形成能已实现验收。

只读审查已确认job50的原生SCF、显式中性电荷、模型/原子映射及方法证据可作为复用候选。下一实现限`neutral_formation_from_tasks`在严格原生绑定通过后接受显式缺失chemical point；输出Ehost/Edefect、差值、deltaN及来源，形成能保持null，非空参考继续走原有严格检查。CLI沿用`neutral-formation`的可选化学势输入，不新增路由框架或同时扩大输入对创建器。唯一可能新增的原生任务是同一已有O8空位的中性q0固定几何SCF；必须从job50原始父模型路径派生，保持其方法物理身份，GPU及time=0。当前未生成/提交该任务，须先完成实现和明确协议，不借机追加精度矩阵。

后续铁电/介电数据链继续独立推进。MACE约2.708GPa材料差异后置，不为0.12追加选势搜索、精度矩阵或参数追因。DeePMD专用训练路线与匹配LAMMPS接口仍保留，尚未部署部分不标完成。
