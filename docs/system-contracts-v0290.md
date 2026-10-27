# 0.29 Γ 点指定方向 NAC 交付

2026-10-23：0.29.0 已验收、启用并冻结；0.28.0 为选定回退版，开发源码版本为 0.30.0。Bundle registry、MCP 启动路径和正式 Python 绑定一致；发布/本地安装副本的 148 个文本文件直接比较一致，未做哈希校验。

## 实现和边界

新增公共命令 `phonon-nac --request --born --electronic --output`，对保存的力常数、完整 Born 张量和电子介电张量计算 Γ 点沿指定方向的 Wang NAC。方向基底为 `primitive_reciprocal_fractional`，保留原始方向并规范化用于计算。产物通过 `deliver-properties` 的 P5 `nac` 项进入同一 Study 的统一交付，保留产品自身和上游来源、上下文、方法、频率及资格状态。

核对 v100 实装 Phonopy 4.8.3 后，采用底层 Rust 动力学矩阵接口，显式 `hermitianize=False`、`is_symmetry=False`；检查并记录原始虚部和 Hermitian 残差，不自动对称化 Born/ε∞、不施加 ASR、不裁剪负频率。现有 `phonon_gamma.py`、`dielectric_response.py` 和 MCP 实现与 0.28 相同，离子介电 Hessian 未改。完整接口要求见[限定合同](p5-v029-directional-nac-contract.md)。

## 真实执行

只复用 job197 的 `NaCl-math-fixture` / `p5-math-study-v001`。全部数值和测试由 v100 Slurm 执行；该实装 Rust 小矩阵接口没有配置 CUDA 路径，申请 1 CPU、2 GiB、10 分钟、no-requeue，实际分配 2 逻辑 CPU。

| Job | 动作 | 原生终态与结果 |
| --- | --- | --- |
| 256 | 收集精确新增 core 节点 | COMPLETED/0:0，9 项 |
| 257 | 新 core 检查 | COMPLETED/0:0，9 passed |
| 258 | 收集精确新增 delivery 节点 | COMPLETED/0:0，6 项 |
| 259 | 新 delivery 检查 | FAILED/1:0，5 passed、1 failed |
| 260 | 仅复验修正的失败断言 | COMPLETED/0:0，1 passed |
| 261 | 安装副本 NAC 与交付公共命令 | 两命令均 exit 0；最终清单断言失败，job FAILED/1:0 |
| 262 | 仅复验安装副本交付公共命令 | COMPLETED/0:0，完整验收通过，复用 261 NAC |

259 的测试对体积 63.99999999999998/64.0 作整字典严格相等；仅修正该体积断言为绝对容差 1e-12，其余身份比较不变。261 暴露清单缺少 NAC 产品自身路径，增加两行路径登记后由 262 验收。原始失败、stdout/stderr、命令和退出码均保留；没有自动重试/requeue。15 个唯一新增测试节点最终通过，旧测试 0、跳过 0；不重复已通过节点或完整宿主验收。

## 数值与资格

解析 NAC 修正最大差为 2.7755575615628914e-17 eV/Å²/amu；修正秩为 1，旧 Γ 基线差、横向项、方向缩放差均为 0。转换因子 14.39965172592227 eV·Å。夹具横向光学频率 9.061496523455437 THz，指定方向纵向频率 11.337641468419204 THz；微小负声学频率如实保留。原始输入和保存 Γ/离子结果未变。

这只验收数学夹具及系统路径，`scientific_qualification=false`、`production_qualification=false`。无新增 MD、DFT、训练或力常数拟合。完整原生 Born/Γ、物理 Berry 分支、ABACUS 电子介电 producer、收敛 relaxed 响应和具体材料生产资格仍未完成。P0–P12 未整体完成。

## 证据和下一最小项

- [发布验收](../workspace/reports/phonon-nac-v029-v001/acceptance.json)
- [安装交付验收](../workspace/reports/phonon-nac-v029-v001/installed-delivery-262/acceptance.json)与[同 Study 完整交付](../workspace/reports/phonon-nac-v029-v001/installed-delivery-262/delivery.json)
- [数值检查](../workspace/reports/phonon-nac-v029-v001/core-execute-257/numerical-checks.json)、[独立审查](../workspace/reports/phonon-nac-v029-review-v001/review.md)、[执行记录](../workspace/reports/phonon-nac-v029-v001/control-events.md)

下一最小项是只读界定旧 Γ `run_qpoints` 隐式 Hermitian 化行为与其声明合同的差异，再决定限定后续任务；本版未修改该旧路径、未启动新计算。0.27 及更旧软件副本待退役，尚未清理，不宣称磁盘只剩两版。见[版本保留记录](version-retention-policy.md)。
