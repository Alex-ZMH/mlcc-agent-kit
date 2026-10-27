# 已有原生力的公共收集缺口

2026-10-25。真实BTO来源为GPU job464和469–486，全部SCF收敛。job492完成19点公共结果解析后，在`phonon_forces.load_native_force_task`的PW-only门失败；493仅保存已有结果。不得将493称作标准公共phonon collection验收通过。

当前已验收494的0.46快照保持冻结。本项是下一源码阶段的实际接口修复，不要求材料重新计算。原实施窗口可先在报告适配范围消费493得到raw Γ；这不取代本项公共入口修复。

## 最小实现范围

1. `phonon_forces.py`显式支持PW/LCAO。LCAO核对原生STRU的NUMERICAL_ORBITAL与正式method中`numerical_orbitals`、`numerical_orbital_ids`及`orbital_header_snapshot`，并加入跨点共同方法比较。不采用旧报告字段别名，不只删除PW门。
2. 保留原生INPUT/KPT、PP、cal_force/cal_stress、映射、调度和收敛检查。已有ABACUS结果解析器无需为本项重写。
3. 增加显式父结构reference绑定。464是真实P4父结构SCF，没有`phonon_displacement`；不得改其task、捏造P7标志或child谱系。reference由所选task路径与plan.reference、父Model/Study、实际几何绑定；18个位移继续严格P7及child谱系。
4. `phonon_gamma.py`的源绑定相应区分reference与displacement，仍保留同方法、单位、顺序、来源和完整位移集合。旧合法P7 reference流程不变。
5. 沿现有CLI薄接线显式reference选择，不引入另一个调度器或新通用工作流。

## 验收边界

只验以上新增行为，复用493保存力及464/469–486元数据。LCAO方法不一致、NAO不一致、错误reference和错误child绑定须真实拒绝；正确保存源通过新的明确合同。不得重跑DFT、重复19点原生解析或重复已经获得的Γ数值结果；若必须读取某原生字段，只读取该新增合同所需部分并记录。

完整原生collection仍须如实区分数据可用与材料阈值。BTO未弛豫参考力较大，不以此阻塞软件接口，也不能把报告级493包改名伪装为既有collector通过。具体实现/验收job由下一项所有权交接后记录。
