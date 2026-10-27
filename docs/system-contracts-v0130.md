# 0.13.0 系统交付

0.13.0已验收、启用并冻结；回退选择0.12.0，后续源码0.14候选。v100安装job127为COMPLETED/0:0，原版MatterAI宿主会话与MCP连接通过，96个发布/安装文件直接文本一致；正式Python及MCP均指向0.13安装目录。没有提交Git或修改上游树。

本版交付两项真实系统路径：

1. 中性host/defect原始能量绑定。复用host50，仅新增同方法O8/q0 GPU SCF121，准备120、原生解析/公开入口123完成。省略chemical point时交付Ehost/Edefect、deltaN、能量差及原生任务/job来源；形成能与修正形成能均为null。空chemical point、错误参考身份仍拒绝。固定未弛豫胞、2×2×2/scf_thr=1e-4的工程协议未获生产精度资格。
2. 固定胞周期RDF最小移植与交付。模块119复用Ni MD45，127把可选RDF接入既有deliver-md；沿用显式观测窗口。缺窗口不计算；rmax=1.75Å范围内真实无配对，first_peak=unresolved，不能解释为完整近邻配位数为零。未新增MD，未重做模块119或冻结版本测试。

job127只补安装入口：中性结果与123一致、RDF交付、缺窗口RDF保持空值。所有数值工作在v100 Slurm；本地只有编辑/传输控制/安装连接及证据查看。新DFT121为GPU、time=0、原生电荷密度收敛，正常完成31秒。0.13不授予材料势、形成能、介电、尺寸或采样资格。

证据：[系统验收](../workspace/reports/system-v0130/acceptance.json)、[中性链报告](../workspace/reports/neutral-energy-v013-v001/report.md)、[安装RDF结果包](../workspace/reports/system-v0130/installed-127/ni-md-rdf-delivery/report.md)。本地任务的远端解析状态已同步为只读展示视图，原始result.json保留；未在本地重算。

下一主线直接进入[P5极化与响应接线](p5-polarization-delivery-next-slice.md)。主窗口负责物理/方法合同、公共入口与集成；既有实施窗口负责明确独立的极化差/分支函数与验收。暂停扩展基础Ni MD、RDF精调、MSD/统计/聚合物切片，原执行清单仍保留；P6/P8/P11未完成。DeePMD独立专项保持现有所有权，待交付审查，不重复安装。

0.10旧软件副本删除此前被自动审批拒绝，仅返回blocked by policy，未执行删除；本版没有绕过，0.11更旧副本也登记待退役。0.13/0.12为当前/回退选择，不能宣称磁盘上已只剩两版。历史科学输入、原生输出、验收和共享环境保留。
