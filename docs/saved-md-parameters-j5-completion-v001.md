# J5 剩余保存产品出口

2026-10-26。0.56已启用、0.55回退，源码0.57。原计划 `domain-parameter-json-development-v001.md` 的J5还包括MSD、两seed统计、迁移占据/几何事件；625只交付NEB势垒、法/切向曲线和局部应力，不能据此把J5或整个J1–J6领域JSON阶段标完成。

只消费566与549等已保存产品。先核对已有入口是否已经直接满足数值或引用、具名定义、单位、条件、坐标/映射、来源和状态的交付边界；满足时复用那一次实际调用，不增加同义包装。确有缺口才在现有 `saved_domain_parameters.py` 加显式kind，复用现CLI和domain delivery。

- MSD：保存时间/滞后及单位、原子选择、已有MSD曲线和已计算拟合/诊断；大数组引用原文件和JSON pointer。D原为null则保持null，不重拟合或补D。
- 副本：原两seed可观察量及保存的mean/SD、SE/CI与原状态；不重新统计，不以两seed宣称收敛统计。缺失SE/CI保持null。
- 迁移：原空位位点占据、几何事件/事件计数及原判据/未决；明确时间轨迹或NEB图像，NEB坐标不得伪装时间，不补速率或新势垒。

每类只用一个已保存真实源作首次出口demo，再交原Study。原生job ID和原分析job ID继承；新Slurm只记录本次保存值/引用的适配与交付。不得调用轨迹解析、拟合、统计、NEB/DFT/MD、校验哈希或旧检查。

一次合并预算：v100 Slurm CPU1、GPU0、2GiB、10min、no-requeue；最多每类1–2项新增路径必要检查，不收集625旧检查。root提交，失败仅修失败节点并续接未完成部分。

原实施独占 `saved_domain_parameters.py`、对应新增检查、必要CLI/Skill以及 `workspace/reports/saved-md-parameters-v001/consumer/`；root负责共有JSON定义、计划、资源、集成审收。第三窗口无新增范围，保持idle。包源码交回后root才制作一次候选和提交。所有人不得回退他人改动。

完成此出口后按原J1–J6清单逐项引用已有实际工程交付，明确当前领域JSON阶段的已完成/未决边界；不重复已有科学计算、算法检查、J4–J6安装或结果消费，不扩展JSON之后的FEM与材料精度矩阵。
