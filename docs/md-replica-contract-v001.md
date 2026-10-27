# MD-05 单一标量的显式 replica 汇总

2026-10-25。MD-04 在原实施窗口开发；第三窗口可并行实现独立 MD-05 领域模块和新增测试，不编辑公共 CLI、property_delivery、版本或 plans。公共接线由主线在 MD-04 冻结后串行安排。沿原逐函数移植清单，不新增 MD/DFT/训练、温度矩阵或新指标。

## 最小功能与来源

只消费已有 MD delivery 中由请求明确选择的一个 observable，不重新解析轨迹或计算 thermo/MSD。首片支持已有 `MD_temperature_sample_mean` 或 `MD_total_energy_final_minus_initial` 的单一选择，不提供任意 JSON 路径或泛化分析路由。

参考 Photoresist `arf_properties_v2._sample_summary`（75–87）的等权均值、样本SD和SE结构；将默认n>=3/正态1.96区间改为显式 descriptive 或 Student-t。`hierarchical_replica_summary`（90–113）仅用于记录来源及不混淆block/replica的边界，本片不重复MD06块计算，不做bootstrap或自动方法选择。

直接复用 `md_sources.select_md_sources` 的模型/势/原生task/job/轨迹和原子映射校验。薄适配读取已保存delivery、其中collection路径和observable源，不修改原产品。比较observable ID/定义/单位/object level、模型/势/method_set、engine/units/atom_style、实际协议和边界、同一原子集合/晶胞及显式观察窗口。不得用不同分析jobID伪造独立轨迹；不得默默换算或混合不同比较条件。

## 独立性与统计

请求列出保存delivery路径及其已有replica ID/独立性依据。真实replica ID和velocity/packing seed必须与collection/task来源一致，不能由本次请求替旧job填造metadata。首片可支持同一固定母模型、明确不同原生速度seed且独立执行的不同native task/job；保留该独立性声明，不把不同seed本身当统计学证明。不同packing/实体拓扑留后续。

输出observed_source_count与已确认身份的replica_count，分别保留每个值、源原生job、分析job、条件和原始科学状态。单来源均值可作为描述量；不足两个独立replica、缺身份或独立性声明时，replica SD/SE/CI均为null并列原因，不把相关时间块拆成replica。

显式`interval.mode=descriptive`仅输出等权均值及（证据完整且n>=2时）样本SD。`student_t`还须声明置信水平0<confidence<1和iid replica estimates的统计假设；仅在条件/独立来源齐全时使用n-1自由度的t临界值、SD/sqrt(n)计算区间。使用既有SciPy环境，不新增独立统计框架或安装新环境；不能计算时保留原错误/缺项。没有生产材料或平衡资格自动升级。

## 当前证据与验收

job45是唯一原生轨迹，105为保存集合读取，450是统计分析；它们只能组成一个来源链。45的replica_id/packing_seed缺失、velocity seed为20261022，不能补成多个replica。复用450已保存observable，输出实际单源描述量、SD/CI=null及原始缺项，保留45/105/450角色，不重算450。

新增函数与薄保存源适配只做一次v100 Slurm后处理验收，数学多replica例明确标algorithm-only，验证等权均值/样本SD/显式t区间及同源拒绝；不伪造原生多replica。当前缺真实多轨迹数据是实例待证，不阻塞可审阅的软件函数。使用现有transport-v001解释器，1CPU/2GiB/5分钟/no-requeue；不得重跑旧检查或已有计算。

第三窗口独占 `src/mlcc/md_replica.py`（或同等单模块）、对应新增tests、`workspace/reports/md-replica-v001`和本项独立交接说明；不要改共享CLI/交付/移植清单（由主线合并准确函数和证据）。其余窗口正在修改其他模块，保留其编辑。
