# MD-04：原子示踪 MSD 与显式扩散诊断

2026-10-25。MD-04 合同范围已实现并随0.44启用；源码由 v100 Slurm **job453 COMPLETED/0:0（4秒）**验收：17项新增检查、2条公共命令；安装454 COMPLETED/0:0（3秒）仅核对绑定、help/参数解析与保存产品，未调用数值函数或重造输入。只复用 job45/job105 保存源；没有新 MD、DFT、训练、温度矩阵或 MD-06/RDF重算。证据：`workspace/reports/md-msd-v001/integration-v044/release-acceptance.json`。MD-05 replica/CI进入后续候选。

## 移植来源与对象

Photoresist 只读源 `Photoresist-agent-kit-main/Photoresist-agent-kit-main/bundles/arf-car-computation/mcp-servers/arf_properties_v2.py::_linear_fit`（522–534）计算带截距 OLS：斜率为 `Σ(x−x̄)(y−ȳ)/Σ(x−x̄)^2`，截距为 `ȳ−slope*x̄`，并返回残差平方和与 R²；`_msd`（560–593）对每个 lag 使用所有可用时间原点和所有 track，逐三维坐标求平方位移后等权平均，同时返回实际 lag 时间和 `origin_count`。`analyze_tracer_transport`（608–787）提供物理 lag 窗口解析、两半窗口斜率、log-MSD 指数和缺项保留的参考。MLCC 只复用这些数学关系；上游的聚合物 COM、replica 独立性、自动漂移诊断、0.75–1.25 指数门、1.0 Å² 最小变化和正态 CI 都不直接移植。逐函数修改和证据记录在本清单 MD-04 段。

MLCC首片对象为显式source atom ID集合的原子示踪，不复制上游聚合物实体COM输入。固定三维Cartesian标量MSD，明确`com_policy=none`，不隐式扣除整体或物种漂移，不声称已做实体COM或方向扩散。三维平方距离旋转不变，仍保留原生Prism/source坐标基底。轨迹固定胞，变胞坐标分解留后续。

## 原生展开坐标和来源

job45 原生列只有 `id/type/x/y/z/fx/fy/fz`，job105 保存的 collection 明确为 wrapped 且缺 image/unwrap。对此必须返回 `unresolved`，MSD 与 D 为 `null`；不能以最小镜像、短时间或相邻跳变补造展开轨迹，也不能只修改 wrapped 标志冒充证据。job45/job105 没有真实 unwrapped MSD 或 D 证据。

原生入口只增加协议可选项 `unwrapped_trajectory=true`，由 LAMMPS 输出独立的 `id/type/xu/yu/zu` 文件并保留旧 dump；不执行新 MD。`md_unwrapped.py` 只读取并校验该真实源文件，绑定现有 task/model/atom-map/Prism、native step、物理时间和 source files；`md_trajectory.py` 继续提供既有 collection/来源绑定，不能从 wrapped 坐标生成伪 unwrapped 数据。新字段必须有实际源文件和输入命令定义；当前没有原生 unwrapped 正例，格式夹具不计为原生轨迹证据。

## 算法和请求

复用已有 collection 来源/Study 选择与显式观察窗口。请求固定声明 `source_atom_ids: [...]`、`dimensions: 3` 和 `com_policy: "none"`；`com_policy=none` 表示不把原子集合改写成聚合物实体 COM，不隐式扣除整体或物种漂移。请求还声明 `fick_window: {start_ps, end_ps}`，并可选提供 `thresholds: {minimum_r_squared, maximum_relative_slope_spread, log_msd_exponent_range: [min, max], minimum_msd_change_A2?}`。每个 lag 使用所有可用时间原点和选中原子：先求三维平方位移，再作等权平均，输出 `lag_ps`、`MSD_A2`、`origin_count` 和 `atom_origin_pair_count`。时间必须来自真实 `physical_time_ps`，严格递增且均匀；不均匀采样保留明确不支持原因，不把 frame 序号当时间。

Fick 窗口只接受明确的正 `start_ps/end_ps`，保留实际匹配 lag、输入来源和原子选择。拟合至少 4 个 lag 点，两半各至少 2 点，末端至少 2 个原点；这些是算法可识别的最低点数，不是材料生产精度标准。输出有截距 OLS 斜率、截距、R²、残差、两半斜率/相对差、log-MSD 斜率和样本数。相对斜率差使用 `abs(left_slope-right_slope)/abs(full_slope)`；完整斜率为零时保留未决，不使用上游 `max(abs(slope), 1e-30)` epsilon。非正 MSD 或退化量保留 `null` 和原因，不裁剪原始数据。

阈值由请求显式提供，不移植上游 0.75–1.25 指数门、自动 drift/stationarity 门或其他默认材料阈值。没有阈值或阈值未通过时保存 MSD/拟合诊断，D 为 `null`。在明确阈值均通过且完整斜率为正时，可给单轨迹工程诊断 `D_A2_per_ps=slope/6`，并以 `1 Å²/ps=1e-8 m²/s` 转换；这仍不改变工程/未资格状态。不要求为软件开发新增 replica，不输出无依据 CI，也不把零 MSD 当作确定的零扩散率。

## 公共消费与验收

沿用 `deliver-md` 的保存 collection 路径与同 Study 交付，不新建 router。最薄接线是：`md_trajectory.py` 负责既有 collection、Prism、atom-map、task/model/potential/source selection；`md_unwrapped.py` 只解析协议声明的真实 `xu/yu/zu` 源并返回按原子 ID 对齐的轨迹；`md_msd.py` 只消费已绑定、已校验的物理时间和 unwrapped 坐标，不自行发现来源或重建坐标。缺展开坐标的 45/105 实例应实际消费并完整传递原生 job45、collection105、本次分析 jobID、单位/原子 ID 和缺项，不能变成无条件可消费 D。

job453在一次CPU后处理作业中完成7项算法、6项输入/读取和4项集合消费检查；`deliver-md`复用45/105交付真实缺项，`create-lammps`生成新展开输入且保持defined/jobnull。`request.thermo_summary=false`显式跳过旧thermo计算，本轮未请求RDF；新产品进入同一Ni Study的artifacts和报告。完整命令、输出和退出码见 `workspace/reports/md-msd-v001/run-453/commands.json`。

数学轨迹保存独立的 `math-msd-result.json`：lag 1–5 ps对应MSD 1–5 Å²，显式Fick窗口斜率1 Å²/ps，D=1.6666666666666667e-9 m²/s。真实45/105仍为MSD/D null；新展开输入未执行，真实原生正例未获证据。此缺项照实保留，不阻止已完成软件切片和后续系统开发。终态、资源及未提交任务见同目录 `scheduler-453.txt`、`run-453/acceptance.json`，主代理和独立只读复核均未发现阻断缺陷。
