# MD-06 显式热力学统计诊断

2026-10-25。本合同范围源码0.43已由v100 Slurm450验收：COMPLETED/0:0、3秒、10项新增检查和2条公共命令。复用job45原生MD及job105保存collection，不增加MD、DFT、训练或温度矩阵。证据见`workspace/reports/md-thermo-diagnostics-v001/acceptance.json`；当前发布仍为0.42启用/0.41回退，0.43待集成安装。

## 来源与最小改动

- 直接复用 `md_thermo.analyze_md_thermo` 的来源绑定、原始 thermo rows、单位和 `_observation_rows`；`md_conditions.read_md_conditions`、`md_sources.select_md_sources`、`property_delivery.deliver_md_properties` 以及 CLI 的 `deliver-md` 继续沿现有路径。
- ACS `VASP_MDAnalyzer._analyze_stability`（`md.py:1176-1234`）只提供时间序列编排和结果保留的参考；`_detect_equilibrium_index`（`md.py:1236-1247`）提供带截距 OLS 斜率的数学参考；`_detect_anomaly`（`md.py:1249-1255`）提供异常索引形状的参考。它们不是 MLCC 的直接输入层或默认参数来源，准确边界见 `docs/md-postprocessing-statistics-porting-list.md` 的 MD-06。
- 不移植自动寻找平衡起点、默认 50 点窗口/1e-4 斜率/3σ 阈值、1 ps 缺省时间或分母加 1e-12。时间来自原生物理时间，非有限值保留错误。
- 块均值/样本方差为本项必要的直接统计补充，参考树没有该完整函数，不虚标为移植。保留现有 runner、collection 和 deliver-md；不新增任务框架。
- 实现文件为`mlcc-agent/src/mlcc/md_thermo_diagnostics.py`，由已有`md_thermo.py`消费；`deliver-md --collection`直接读取已保存集合，核对task/job/model/potential/Study身份，不重解析原生日志。`thermo-diagnostics.json`和同Study交付清单分别保留原生job45与分析job450。缺窗口时诊断null。

## 输入和输出

在现有 `deliver-md` 分析请求内加入可选 `thermo_diagnostics`。请求形状为 `{"fields": {"temp": {"max_abs_slope_per_ps"?: number, "anomaly_z_threshold"?: number}, "etotal": {"max_abs_slope_per_ps"?: number, "anomaly_z_threshold"?: number}, "press": {"max_abs_slope_per_ps"?: number, "anomaly_z_threshold"?: number}}, "blocks"?: [{"block_id": string, "start_step": integer, "end_step": integer}]}`；省略该字段时只保留现有描述量路径。由请求显式选择原生字段和诊断参数，不能把 VASP 的 kbar 当 LAMMPS 的 bar。字段分别使用 MLCC 原生行中的 `temp`（K）、`etotal`（eV）和 `press`（bar）；斜率阈值单位分别为 K/ps、eV/ps 和 bar/ps，异常阈值无量纲。观察窗口沿用当前 `whole_record`/`step_range`；`blocks` 的步端点为包含端点，必须明确、互不重叠且位于观察窗口内。没有 `blocks` 时不推断默认块长。

每字段输出原始序列/原生单位、均值与样本方差、每个显式块的样本数/时间/均值/样本方差，及块均值的描述性离散度。少于两个样本时样本方差为 null 并写原因。未指定块或不足两个块时对应块间量为 null。不得把块当独立 replica，不输出未经相关性分析的置信区间或标准误。

漂移采用有截距的普通最小二乘拟合 y 对真实时间 ps，保留斜率及单位/ps、截距、拟合残差或 R²、窗口跨度。该 OLS 是 MLCC 的直接领域函数，不是 ACS 的移动窗口平衡索引移植。时间点不足或退化时保留未决原因；不自动移动窗口。比较阈值必须是该字段显式提供的有量纲最大绝对斜率。

异常指标按窗口有限样本的总体标准差（`ddof=0`）计算绝对 z-score，阈值由请求显式提供；返回原始行索引、step、物理时间和原始值。精确常量序列的 z-score 定义为零并注明零方差，不添加数值 epsilon 或丢弃异常样本。缺阈值时可保留量但不代定通过/失败；非有限字段保留原始错误。

块均值和样本方差是 MLCC 新增的直接统计函数，不声称来自 ACS。每字段输出原始序列、均值、样本方差、显式块统计、块均值的描述性离散度、漂移拟合和异常记录；不足两个样本的样本方差为 `null` 并写原因，不输出未经相关性分析的置信区间或标准误。比较结果称本次显式阈值的诊断，不自动认定平衡、生产采样或时间步收敛。阈值失败保留原始数值和失败项，不自动截断/扩窗/重跑，也不把工程结果变成不可消费。已有 `sampling_equilibrium_qualified=false`、真实势和来源状态继续保留；全系统未实现功能不应沿用旧版本硬编码缺口。

## 工程验收和所有权

只在 v100 Slurm 对新增统计函数和其现有公共接线做必要检查。用已有 job45 的 11 条原生 thermo 数据，明确标注短工程序列；数学参考检验非零斜率、显式块、异常阈值和零方差分支，不能当新材料数据。一次后处理作业复用同一 collection，保留 job45 和本次分析 job ID，绝不重跑原 MD。当前实现/验收状态待定，job 证据由 root 后补。

交付记录每个移植来源函数、实际修改和验收证据，更新既有 MD-06 清单该项。原实施窗口独占必要的 md_thermo/薄统计模块、相关 tests、property_delivery/必要 CLI/Skill；主线独占版本元数据、阶段计划和安装集成。工程通过后继续原队列，不为短轨迹追加生产采样。
