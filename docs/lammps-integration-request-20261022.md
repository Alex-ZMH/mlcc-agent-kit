# LAMMPS 系统入口交接（2026-10-22）

**最新修订状态：** 交叉审查后的模型/势/方法/MD 轨迹绑定修复已编辑并重新冻结，最终代码尚待 v100 经 Slurm 验证。下文 25 项通过与 job41 验收是此前切片的历史证据；不能当作本次修订的测试结果。详见 `workspace/reports/lammps-system-v001/final-review-v002.md`。按最新执行位置约束，本窗口未继续本地科学测试或解析验收，未提交新作业。

本窗口只新增 LAMMPS 领域模块、任务薄适配器、局部测试、独立验收脚本和 workspace 数据。没有修改 CLI、MCP、site_runner、版本、PLAN 或公共阶段矩阵。本文件供集成窗口审查后接线；工程验收不授予生产势或 MD 采样资格。

## 当前 API

- `mlcc.lammps.export_lammps_data(model, directory, *, element_order, units, atom_style)`：接收已持久化 `ModelArtifacts`，导出 `model.data` 与 `atom-map.json`。支持三维周期、`metal/atomic`；保留原子 ID/type/元素/质量及 ASE Prism 坐标旋转。非零电荷、同元素不同质量、其他 atom style 明确拒绝。
- `mlcc.lammps.prepare_lammps(model, directory, *, potential, protocol)`：显式势与 `run0` 或 `md` 协议生成 `in.lammps`、`method.json`。MD 仅 NVE/NVT 输入能力，温度、随机种子、步长、步数、输出间隔均由调用者提供；NVT 还需显式 `tdamp_ps`。
- `mlcc.lammps.parse_lammps_outputs(directory)`：解析实际 `log.lammps` 和 `dump.final`，还原母模型原子顺序、坐标和力，绑定单位、版本、步数、box、ID/type。势能 eV、力 eV/Å、原生压力 bar，换算 GPa 使用 `1e-4`。
- `mlcc.lammps_tasks.create_lammps_task(*, study_path, model_path, potential_path, protocol_path, site_path, request_path)`：写已有 TaskRecord 合同，暂限定单 rank 工程 fixture。创建不提交。
- `mlcc.lammps_tasks.parse_lammps_task(task_path)`：要求已保存真实 Slurm `COMPLETED/0:0`，绑定任务与原生版本/模型/势/协议，写 `result.json`。
- `scripts/system/verify_lammps.py`：只读复核真实 Ni `run 0`，与运行前固定的准则比较。

## 集成窗口需要的明确改动

1. CLI 增加 LAMMPS 任务创建与解析入口，参数逐项对应上面的 API；不在创建时隐式 transfer/submit。
2. 集成窗口已确定 MCP 保留七个共用生命周期工具，不新增科学创建工具；创建与解析通过 CLI `create-lammps` / `parse-lammps` 接入。沿用已有 Slurm prepare/transfer/submit/query/collect；无需再实现调度器。
3. 站点配置显式提供 `lammps.binary/version/environment_script/launch_prefix`。本次单 rank 的空 launch_prefix 表示由 Slurm batch 内直接运行一个进程；不支持据此宣称多 rank 验证。
4. 工作流区分 `evaluated_engineering_fixture`（run 0）和 `executed_engineering_fixture`（MD 执行）。两者都不是物理收敛或平衡采样，不应加入通用“已收敛”状态集合。
5. 结果交付新增 LAMMPS 原生证据分支，至少保留 log、dump、method、atom-map、输入/势来源、task scheduler evidence；不要套用 DFT 原始标签或生产精度含义。MD 还回传独立 trajectory 文件，不用轨迹替换最终 dump。
6. 完成安装副本的 CLI/MCP 真实调用验收后，再由集成窗口更新 Bundle 版本和公共能力矩阵。当前仅可声明领域 API 与本文件下方记录的实际静态任务能力。

## 势与运行环境

独立用户环境固定为 `/home/v100/projects/mlcc/.venv-lammps-2025.7.22.4.0`，PyPI `lammps==2025.7.22.4.0` 是 njzjz 提供的非官方二进制发行。配置及安装原文在 `workspace/configs/lammps-environment-v001.json` 和 `workspace/reports/lammps-system-v001/`。实际二进制版本、MPI 链接、支持包须以安装后探测为准。

Ni_u3.eam 来自 LAMMPS `stable_22Jul2025_update4` 发布标签。势文件、来源、GPL LICENSE 与上游 README 留在 workspace；不进入 Bundle。文件引用 Foiles/Baskes/Daw 1986 Ni EAM，当前许可与适用范围记录在显式 potential 配置。EAM 文件内质量在输入中由母模型质量显式覆盖。

采用 ABACUS job 33 的 Ni 弛豫模型作为几何母体；其 DFT 原始能量不参与 EAM 绝对能量差比较。预先登记的宽松静态比较参照同一 Foiles Universal3 模型的近 fcc Ni 结合能，仅是接线错误筛查。它不验证材料温区、界面、缺陷或铁电响应。

参考来源：

- [固定发行的 PyPI 包](https://pypi.org/project/lammps/2025.7.22.4.0/)。
- [固定标签的 Ni_u3.eam](https://raw.githubusercontent.com/lammps/lammps/stable_22Jul2025_update4/potentials/Ni_u3.eam)、[LICENSE](https://raw.githubusercontent.com/lammps/lammps/stable_22Jul2025_update4/LICENSE)、[势目录说明](https://raw.githubusercontent.com/lammps/lammps/stable_22Jul2025_update4/potentials/README)。
- [NIST 同模型 fcc Ni 参考](https://www.ctcms.nist.gov/potentials/entry/1986--Foiles-S-M-Baskes-M-I-Daw-M-S--Ni/EAM_Dynamo_FoilesBaskesDaw_1986Universal3_Ni__MO_580571659842_000.html)。
- 官方 [metal 单位定义](https://docs.lammps.org/units.html)、[EAM 输入定义](https://docs.lammps.org/pair_eam.html)、[run 0 语义](https://docs.lammps.org/run.html) 用于审查单位和输入。在线文档版本更新于本地二进制之后；本机功能验收只认实际 help/log 与作业结果。

## 整体进度边界

读取 `plans/stages.json` 的 0.8.0 状态：H0 已完成，P4 的 Ni 工程闭环与若干电子/弹性/缺陷/交付软件片段已验收，H1 仍未完成。2×2×2、SCF 1e-4 的应力有限差分检查失败，不能由本轮 LAMMPS 静态结果修正这一结论。P7 在其他窗口推进；本窗口不修改其文件或状态。P9–P11 的本次工作是可运行入口，不是这些阶段的完整科学交付。

## 验收状态

唯一新增数值任务 `p9-ni-lammps-run0-v001` / Slurm **41** 已通过工程静态验收，终态 **COMPLETED / 0:0**，无 requeue/restart。原生版本为 `LAMMPS (22 Jul 2025 - Update 4)`；`-h` 与 `ldd` 确认实际 MPICH 4.3.2 / `abacus_env/lib/libmpi.so.12`，支持 MANYBODY/EAM。

任务申请 1 rank × 1 CPU、1 GiB、2 分钟，不申请 GPU。Slurm 实际 `AllocTRES=cpu=2,mem=1G,node=1`，日志为 1 MPI task × 1 OpenMP thread；这两项分别保留，不能把申请量当成实际分配量。Slurm 计时 0 秒（秒分辨率），进程日志约 3.209 MiB/rank；资源回查队列为空。

4 个 Ni、step 0 的结果：

| 检查 | 原生/复核值 |
|---|---:|
| 总势能 | −17.79999340275548 eV |
| 势能/原子 | −4.44999835068887 eV |
| 与预先登记 −4.45 eV/atom 宽松参考之差 | 1.6493×10⁻⁶ eV/atom；门限 0.01 |
| 总合力范数 | 2.8622×10⁻¹⁷ eV/Å；门限 1×10⁻⁸ |
| 最大原子力 | 0.0118448759 eV/Å；未声称 EAM 弛豫收敛 |
| run 0 前后最大 MIC 坐标差 | 2.2644×10⁻¹⁵ Å；门限 1×10⁻¹⁰ |
| 压力 | 0.7220017494 bar = 7.2200174935×10⁻⁵ GPa |

日志中的无时间积分 fix 警告符合本次 `run 0` 不移动原子的协议，完整保留。温度 0 是无速度静态原生输出，不是生产温度或热平衡结果。`scientific_status=evaluated_engineering_fixture`，production/MD qualification 均为 false。

证据位于 `workspace/reports/lammps-system-v001/`：`predeclared-acceptance.json`、`run0-acceptance.json`、`native-help.txt`、`native-link.json`、`final-scheduler-resources.json`、`task-events.json`。原生输入、势副本、log/dump/stdout/stderr 与 TaskRecord/result 位于 `workspace/tasks/p9-ni-lammps-run0-v001/`。提交前自身测试 16 项通过；补入真实回传解析回归后，最终自身测试 25 项全部通过（无跳过），见 `unit-tests-native.txt`。

本窗口的最小交付已经跑通数据导出→显式势/协议→Slurm→回传→原生解析→静态工程验收；CLI/MCP 的安装副本接线仍待集成窗口按上文实施。

2026-10-22 冻结记录：`lammps.py`、`lammps_tasks.py`、对应两个测试文件和 `scripts/system/verify_lammps.py` 本轮交付冻结。最终局部测试 **25 passed in 2.11s**，无失败或跳过。原生回归使用 job41 实际回传文件；错误、势命令、原子 ID/type、步数、版本和调度状态的损坏检查仅修改临时副本。当前没有未解决的本轮解析测试问题；没有新增作业。CLI/workflow/source_evidence 与 0.9.0 安装验收归集成窗口，生产及 MD 采样资格仍 false。

## 仍未覆盖

没有执行 MD、训练、陶瓷/金属界面、高分子任一分支或生产材料矩阵。未验证时间步/尺寸/采样收敛、势的 DFT 基准、热输运、极化或场耦合。P9–P11 科学阶段均不能据此标完成。LAMMPS 不承担通用 FEM、相场或完整器件反馈。

## 后续交付更新：中性参考绑定与候选势检索

2026-10-22 13:30，材料势比较器补齐新增带电 SCF 的衔接边界，只接受当前 atomic LAMMPS 可比较的中性 ABACUS 参考。修改仅为 `potential_qualification.py` 和对应测试；API不变，原生/方法/任务/模型电荷覆盖非零或gate开启即报错。历史 job37 中性原生读取继续通过。源码审查后 Slurm job73 **COMPLETED/0:0，13 passed、12 deselected、0 failed/skip**，没有新增 DFT/MD、没有重跑 Ni。代码和完整执行证据见 [v003台账](../workspace/reports/potential-qualification-v003/execution-ledger.md)，由主集成窗口统一处理候选安装及计划状态。

此前 job63/66 的张量比较与真实模型限定用途保持；job45/47的Ni短MD是后续历史工程证据，前文“没有MD”仅指最初job41切片。现仍缺实际完整张量材料配对、合格DFT参考、应力标定与材料势科学资格。

用户新授权从文献检索候选势。结果与DOI/资源/许可核对见 [文献审查](../workspace/reports/potential-candidates-v001/literature-review.md)。明确找到含CaZrO₃的2025年MTP/NEP论文，但权重需向作者取得；通用公开权重只作为候选，不自动切换/安装/训练。下一最小任务是取得一个确定候选的真实模型资源并声明静态对照范围和参考误差预算。版本仍保持0.9.0启用、0.10.0候选，未发布。

## MACE-MP-0b3公开候选静态筛选交付（2026-10-22 14:23后）

后续用户显式选用MACE-MP-0b3 medium，并给出10meV/atom、最大力分量0.15eV/Å、最大应力分量0.5GPa门限及力RMSE报告要求。本窗口完成独立资源/环境与三构型对照，未修改冻结的0.10.0公共源码或共享计划。当前版本启用状态由主集成窗口维护，前文0.9/0.10状态是历史记录。

最终报告：[mace-czo-static-v001/report.md](../workspace/reports/mace-czo-static-v001/report.md)。机器结果：[screening.json](../workspace/reports/mace-czo-static-v001/screening.json)，原始MACE接口/同几何数据：[comparison.json](../workspace/reports/mace-czo-static-v001/comparison.json)，运行时交接：[runtime-handoff.json](../workspace/reports/mace-czo-static-v001/runtime-handoff.json)。

- 原生ASE/CUDA接口job84通过；MACE0.3.10、Torch2.5.1+cu121、e3nn0.4.4、ASE3.26.0、NumPy1.26.4，V100SM7.0，float64。环境`/home/v100/projects/mlcc/.venv-mace-0.3.10-torch2.5.1`已完成安装（job93）且不再修改。
- 精确模型路径`/home/v100/projects/mlcc/resources/mace-mp-0b3-medium-v001/mace-mp-0b3-medium.model`。MIT及DOI10.1063/5.0297006来源保留；模型训练方法族与ABACUS标签分离。
- 中性job50原始几何复用；job85完成0.995/1.005各向同性缩放构型的两次SCF，time=0，电子分别9/10步收敛。未重跑Ni或借用带电参考。
- job87三构型筛选：相对能全部配对最大误差**6.03312834meV/atom**，力分量最大误差**0.145225883eV/Å**，力分量RMSE**0.0527608968eV/Å**，应力最大分量误差**2.80989157GPa**。**应力门限失败，静态筛选未通过，生产资格false。** 静水符号核对通过；中性ABACUS参考精度、剪切响应和目标温度/性质资格仍缺。
- 模型只能登记“可用公开候选/对照工具，ASE/CUDA接口通过”。不能授予用户指定的“在已测试范围内通过静态验证”标签。MACE不替代ABACUS→DeePMD-kit→LAMMPS专用势主线。
- 主集成窗口负责独立LAMMPS-MACE编译与GPU run0，直接复用job84原始字段；本窗口没有重复构建或发起额外接口验收。公共API/源码本轮无需改动。

全部原生终态与安装/准备失败、明确取消及修正记录见[执行台账](../workspace/reports/mace-czo-static-v001/execution-ledger.md)。下一科学最小任务是中性参考力/应力精度收敛与应力偏差核对，不能自动更换势、改变门限或启动温度矩阵来消除当前失败。

## 中性同几何参考收敛诊断完成（2026-10-22 15:00后）

本窗口仅新增原base几何五个ABACUS单点，job100/102/103均COMPLETED/0:0、单V100、time=0，未改公共源码或共享计划。详见[诊断报告](../workspace/reports/czo-neutral-reference-convergence-v001/report.md)、[最终原始分析](../workspace/reports/czo-neutral-reference-convergence-v001/analysis-103.json)、[限定验收](../workspace/reports/czo-neutral-reference-convergence-v001/acceptance.json)。

- 原1e-4→1e-8最大应力变化0.173718GPa，原222→333变化0.149661GPa，粗参考存在可见误差。
- 100→120Ry、1e-8→1e-10、333→444的应力尾差分别0.00949087、0.00195562、0.00839227GPa；对应能量/力增量也在本轮1meV/atom、0.015eV/Å、0.05GPa诊断预算内。该预算仅为筛选门限10%，用户材料门限未改。
- 120Ry/444/1e-8最终base与固定MACE84：应力差仍2.70825794081GPa，力最大差0.116605500468eV/Å、力分量RMSE0.0563026635564eV/Å。**仍未通过0.5GPa门限**。
- 复用主窗口98/101的ASE↔LAMMPS应力差4.72081e-7GPa，不重复接口。这些结果不支持以已测数值或接口误差解释剩余偏差，但还不能唯一划分模型与参考赝势/训练方法差异。
- 单base所测尾差检查不能替代三构型统一精度复筛、赝势科学资格或温度/目标性质资格。原87筛选失败不变，MACE仍仅公开候选/对照工具；没有启动训练或温度矩阵。

下一最小工作为当前Ca UPF扫描提示与参考方法来源的只读追查，必要时再用细化协议的两侧小应变验证能量导数与静水应力。主窗口继续负责整体阶段/版本归集，本窗口没有把H1/P9等科学阶段改为完成。

后续中性host链可复用的精确原生路径、方法、能量定义与科学缺口单列为[host-reference-handoff.json](../workspace/reports/czo-neutral-reference-convergence-v001/host-reference-handoff.json)。job103的120/480Ry、444、1e-8固定几何参考总电子能为原生`!FINAL_ETOT_IS -14816.9752634190499521 eV`；这是整20原子晶胞fixed占据的E_KohnSham，未加有限温度或外压焓项。它不是新弛豫平衡host，也不是已登记的公共runner TaskRecord，不能直接视作已通过缺陷/化学势参考链资格。
