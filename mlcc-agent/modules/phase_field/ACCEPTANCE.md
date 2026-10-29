# 相场迁移验收（2026-10-22，Asia/Shanghai）

已完成实际接入，不仅是审阅。Windows公共CLI→模块Adapter→既有WSL/FEniCSx→原生产物→公共结果与只读查询均真实运行。科学范围是无量纲标量LGD P/phi，不是材料/实物适用性签核。完整机器索引为[evidence.json](evidence.json)。

## 来源与改动

fem_solver.py、physics.py、initial_conditions.py、v02.py、v03.py五个当前文件与results_v03/frozen_sources.json逐项SHA256一致，见SOURCES.json。仅抽取必要物理内核与连续初态；没有运行时experiments导入、绝对来源路径或sys.path注入。实验编排、扫描、统一PASS worker和报告脚本未搬入生产。

保留原弱式/Jacobian、初始phi一致化、固定电压电焓、直接求解、失败回滚/缩步/接受态提交、原始Gauss/反力和RT0。公开构造仅物理2D/3D，移除1D/MMS/pin_wall/验证边界；故障注入只在harness修改真实SNES迭代上限。新增独立契约、Windows部署/执行/规范化、原生读回、图像、资源上限、唯一中心线交点语义及严格有限JSON。来源和迁移范围详见README。

## 五个真实公共任务

前四例位于 `work/qualification-984a69f62b534b94abcdfc7c4f1aca8f/project/outputs/tasks/`；最终核演化位于 `work/final-4bfd6bfa/project/outputs/tasks/`。这些是模块内逐字节公共源码副本，所有状态由Windows公共Runtime管理。没有修改根outputs、公共源码、fem或experiments。

| 新任务 | task_id | 单元 / 总DOF | 完成 |
|---|---|---|---|
| 2D uniform稳态 | task-0b7efac05aad4217bc5362976b41fbe3 | 128 / 170 | 非线性稳态；无瞬态终止要求 |
| 2D wall演化，E=.12 | task-a25bf9e6d79e4e7a868f7550c663c6c6 | 128 / 170 | t≈0.5，10接受步 |
| 3D uniform稳态 | task-d6e812ed18c04346bb04c22f1996d1b3 | 1536 / 850 | 非线性稳态 |
| 3D连续随机场，seed11/modes3/幅值.05 | task-2d33f47197e945e78ab5b60da29a63c4 | 5184 / 2450 | t=2，40接受步 |
| 最终代码3D核演化＋非平凡RT0 | task-ae91ac377f234c308732703fcd6c1d5c | 768 / 450 | t=.15，3接受步 |

五例均succeeded、real_computation；原始数值和逐项QC以公共record/result为准。前四例为初次迁移源码快照，后续增加总接受步资源护栏与严格JSON后，由最终三维核任务和native-regression-final补充验证，不重写旧任务。

三维随机场初始P梯度RMS约[.00167475,.00521185,.00523014]，最终约[.00548364,.00136189,.01029429]，确有z变化。最终三维核梯度约[.123598,.197722,.254912]，也不是挤出。最终核自由弱Gauss残差5.8072e-15，电极反力平衡6.3838e-15，RT0散度RMS1.0651e-15、内部法向跳跃8.4861e-16、侧面法向RMS3.0056e-16；但raw侧面法向RMS约.177437、重构修正RMS约.161958，独立保留，不称CG1强守恒。

XDMF/HDF5/NPZ回读核查网格维度/单元、每个接受态P/phi及最终DG0 E；三维全体数据不是切片。图像已查看2D E和3D P，单位标明dimensionless、z位置明确；图像不作为科学验收替代。全部查询及终态worker前后record和原生产物hash相同。

## 与V0.3相同配置对照

`work/baseline-comparison-01.json`：2D对应results_v03/numerics/extruded_2d_n16（16×4、wall width1、E=.12、dt=.05、end=.5）；3D对应initial_conditions/seed11（24×6×6、三维连续谱、dt=.05、end2）。对照前核对配置和初态映射，不把锚定壁或MMS当自由物理问题。

两例P、phi、E、times、P_history、phi_history的最大差均为0，fields.npz文件SHA256也分别相同。使用来源audit同配置重复1e-10数值准则，仅证明这两组配置的迁移一致性；不替代新网格/时间/材料验证。均匀稳态为新公开无锚定问题，电焓2D≈-16、3D≈-64，不声称与来源pin_wall稳态同配置。

## 回滚、终止和资源护栏

`work/native-regression-final/regression.json`和子目录为独立真实科学回归。2D/3D各在t=.05成功接受后用SNES max_it=1制造真实失败，失败试步确实改变场，恢复所有状态后以.025缩步，最终各5接受步、1拒绝步；与相同接受步序列清洁对照的混合场最大差为0。日志保留拒绝reason/monitor/rollback_exact。

另各连续3个失败尝试，在允许2次缩步后终止；保留最后接受t=.05、P/phi/old和原生诊断，不输出失败试步为接受态。非平凡2D/3D核的RT0、原始Gauss与读回同时核查。

最终资源护栏测试用真实分隔失败持续缩小proposal，达到7接受步后在t=.09921875停止，明确资源cap，不冒称完成t=.15。该护栏限制历史/工作量，不改变源BE算法或自动重提公共任务。mock超时只验证SCIENTIFIC_STATE_UNKNOWN和同目录拒绝重启，不能当作已确认Linux进程终止。

## 接口、回归与宿主

- 模块轻量unittest：20项通过；无WSL/网络/专业导入。
- 公共mlcc check：valid=true，8个模块，仅结构证据。
- 公共默认测试逐字节副本：56项，55通过、1符号链接权限跳过；`work/public-tests-extended.log`。深路径首次测试失败保留，使用Windows长路径前缀复核通过，未修改公共实现。
- 最终Windows规范化器重新接受四份真实原生结果，20种内存篡改（身份/网格/缺原生文件/hash）全部拒绝：`work/normalization-f3dee9d8/checks.json`。只改独立副本，不修改原任务。
- 现有AgentHost离线消费Skill、严格输入schema编译、输入引用均通过：`work/host-compatibility.json`。synthetic_unit_test，不是在线模型。真实LLM外发未获本chat授权，not_checked；闭环命令见LLM_ACCEPTANCE.md。
- Skill的frontmatter/相对链接按模块交付检查验证；skill-creator quick_validate因已有Windows环境缺PyYAML未运行到检查阶段，记录not_checked，未安装依赖。

早期失败保留：qualification-83abd...缺隔离副本文档；qualification-d71f...二维HDF5坐标列数与NPZ不同导致读回失败；qualification-984...验收脚本曾误读QC外壳及公共深路径/编码问题。修复后未重提已成功科学任务，前四例汇总原summary的in_progress表示旧harness未完成公共回归收尾，正式分层收口由evidence.json及单独日志给出，不伪造原历史为全程PASS。

## 复现

Windows命令见README。原生针对性回归（显式新增小算例）从本模块根在既有WSL解释器执行：

```text
python -B -m harness.regression --output <全新模块内目录>
python -B -m harness.compare_baseline --qualification <已有qualification目录> --baseline <只读results_v03> --output <新对比JSON>
```

不运行v03.py all、全套MMS/扫描/性能研究。已验证环境Python3.11.15、DOLFINx0.11.0、UFL2026.1.0、PETSc3.25.5、MPICH5.0.1、NumPy2.4.6，单rank；实际完整环境与argv在各任务，未安装/升级环境。

未实施或未确认：任务特定网格/时间收敛、稳态Hessian/稳定性、材料标定/SI映射、实物对照/科学负责人签核、远端强制终止/取消确认、MPI和其他物理。保留not_checked，不把来源PASS或退出码0复制成当前科学适用性通过。当前没有公共接口阻断；部署快照、远端进程协调与Windows长路径增强建议交main，见INTERFACE_PROPOSAL.md。
