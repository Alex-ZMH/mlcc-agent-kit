# 0.33 原生 Born 分支转换与介电消费

0.33已安装验收并启用，0.32回退，源码0.34。v100 job360终态COMPLETED/0:0，9秒，14项新增领域检查和4个公共命令通过。没有重跑旧测试、DFT、PYATB或宿主验收。

新增`born-affine --family FAMILY [--review REVIEW] --output NEW`：消费原生LCAO完整分支族，按显式审定整数计算`Z(n)=Zbase+ΣnC`。不搜索整数、不最近量子选支、不做ASR。无审定/拒绝/推迟/缺连续证据时返回未决；身份、标签、轴、整数及证据引用的错误保留。外部审定是可追溯输入，不是软件证明物理连续性，资格始终false。

新Born产品可进入既有离子介电、总介电和Study路径；Study消费从保存族与审定重新推导，防止编辑张量冒充源结果。另修复`calculate_ionic_dielectric`忽略明确未决Gamma状态的问题：完整Born或放宽容差也不能绕过，未决原因与原矩阵来源保留。未改Gamma/Hessian或有效输入的旧求解算法。

job360从安装候选真实执行`born-affine→ionic-dielectric→dielectric→deliver-properties`，复用CZO的54个来源job；电子ε∞保留，物理Born/离子项/总静态ε为null。另有明确数学正例证明新分支转换后Born→弹簧Gamma→离子项→总ε的解析值与传参；不属于CZO/BTO科学结果。

主线审查涵盖Luna的Gamma修复、实施窗口Born/CLI/Study改动及实际证据。目录中的初始v0330候选从未执行；job360使用提交前修正的v0331归档/candidate-0.33.0-r2，不存在数值重试。160文件直接字节比较一致，未计算哈希。registry/MCP/Python均绑定0.33；未变宿主复用0.26原证据。

[发布记录](../workspace/reports/native-born-review-v033-v001/release-acceptance.json)、[实际安装验收](../workspace/reports/native-born-review-v033-v001/run-360/acceptance.json)、[实际Study结果](../workspace/reports/native-born-review-v033-v001/run-360/delivery.json)。

下一步是已选BTO P4mm工程结构的实际模型/Study绑定；CZO真正物理闭环所缺连续路径和Gamma适用证据见[恢复条件](p5-physical-completion-dependencies-v001.md)。不因软件发布宣称两陶瓷全部场景或完整物理响应已完成。
