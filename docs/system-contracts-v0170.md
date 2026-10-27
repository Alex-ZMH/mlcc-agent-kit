# MLCC 0.17交付：P5分支、Born与介电数据消费

2026-10-22 21:58。0.17.0已经启用冻结，0.16.0回退，源码进入0.18候选。v100安装job197为COMPLETED/0:0、10秒；真实MatterAI宿主0.17与mlcc_list_tasks通过，registry/MCP/Python绑定一致，119个发布/安装文本文件直接一致。见[总验收](../workspace/reports/p5-v017-integration-v001/acceptance.json)与[安装产物](../workspace/reports/p5-v017-integration-v001/installed-197/acceptance.json)。

本切片增加六个公共后处理入口：`berry-branch-review`、`berry-branch-consume`、`born-charges`、`phonon-gamma`、`ionic-dielectric`、`dielectric`，沿用原CLI和领域函数，不增加runner/MCP框架。

| 环节 | 行为 | 当前证据与边界 |
| --- | --- | --- |
| 分支审阅 | 相对整数及邻整数建议；明确review记录绑定response/parent/target/原生任务/P/Q；不自动批准最近分支 | 192 COMPLETED/0:0、6项检查及真实188来源消费通过；真实审阅deferred |
| Born汇总 | 按明确Model的稳定atom_id和位移x/y/z列形成N×3×3张量；禁止复制列或补零 | 193的10项检查通过、1项测试异常类型预期失败留档；194修正后3项定向检查与真实188消费通过，真实CZO缺60列 |
| Γ Hessian | 读取已有P7力常数，复用Phonopy映射与质量去加权；限制primitive=parent、固定胞E=0、无NAC/ASR/隐式对称化 | 195 COMPLETED/0:0，5项定向检查通过；197安装公共链通过。验收范围为software_math_only。原生P7集合缺Berry兼容的pw_diag_thr/kpoint_shift来源字段，native接线仍未完成，完整原生力集合也缺失 |
| 离子介电 | 在三个平移方向的正交补求解；记录对称/平移/Born和残差，负或近零光学模返回未定 | 完整数学输入测试证明公式与单位；真实Born/Γ集合缺失时null |
| 电子/总介电 | 同方法、同父胞、同边界的epsilon_infinity与离子增量相加一次 | 未有本站3.10.1原生电子张量来源；电子消费合同不是引擎producer，真实总量null |

所有数值测试与后处理在v100 Slurm执行；没有新增DFT、MD、训练、温度矩阵或MACE精度研究。192/193/194只检查新增模块；公共安装链只补新入口，不重跑188收集器和冻结版本验收。当前没有已通过的材料铁电/介电生产资格。

科学合同见[p5-v017-integration-contract.md](p5-v017-integration-contract.md)。精确版本能力边界见[p5-native-response-capability-20261022.md](p5-native-response-capability-20261022.md)。公共安装协议见[protocol.md](../workspace/reports/p5-v017-integration-v001/protocol.md)。

恢复真实完整介电链需要：可审计分支/绝缘路径、同父胞完整Born列、同方法完整原生力集合与Γ映射，以及来源明确的电子介电张量。真实材料输入缺口独立保留，不通过填数或发布版本消除。

196在第一个CLI子进程启动时因验收脚本解析venv软链接而找不到NumPy，尚未执行数值步骤；修复仅保留venv解释器绝对路径，197完成未执行的安装检查，未改Bundle科学算法或参数。旧0.10审批拒绝未绕过，0.11–0.15旧软件物理副本仍待退役；共享0.9环境、0.15依赖/构建工具与科学证据保留，不宣称清理完成。
