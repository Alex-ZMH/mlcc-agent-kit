# J4：单方向 bulk NEMD 到领域参数 JSON

2026-10-26 root 明确分工与首个最小工程协议。0.55 已启用冻结、0.54 回退；修改 live 0.56 源码。用户已授权按原队列推进，完成当前数值与单位/定义/来源到领域 JSON 和 Study 的路径即推进，不追稳态、材料精度或理想热导率，不重复 J1–J3/615。

## 唯一首次协议

- 复用 CZO Pnma host20 与 DeePMD 势146。用既有 supercell 函数在 v100 Slurm 一次生成 `[1,1,4]`、80 原子固定胞；保留原子谱系/子 Study，势 descriptor 副本只声明该新模型，不改模型文件或训练势。
- `purpose=bulk_thermal_transport`，`kind=md`，metal，p p p，NVE；初始300 K、seed202610261、步长0.0001 ps、6000步。热浴从本次运行开始作用，无自动预平衡或续跑。
- 热浴按初始 source atom ID 固定组：hot 的 z/L 在 `[0,1/8)`，310 K；cold 在 `[1/2,5/8)`，290 K。两者 damping0.01 ps，seed分别202610262/202610263，`zero yes tally yes`。不重新按位置更新组。
- 沿原胞笛卡尔 +z 分16个等宽 bins，thermo/dump/热量/profile均每10步；不伪造0步的热量/profile行。保留实际输出原样。
- 显式观察窗 step1000–6000（两端包含）；初始化/排除窗0–990。温度按原生 instantaneous bin temperature 的选定帧算术均值；仅使用所选帧都非空的指定 bin，不把空 bin 的0 K当数据。如指定 bin 有空帧，保留该 bin 及其计数，梯度/κ unresolved，不自动换 bin。
- 只拟合 +z 通道 bins3–8，坐标递增，热浴bins1–2/9–10排除。周期胞存在两条路径，显式声明 `periodic_channel_count=2`、`heat_fraction=0.5`、`heat_fraction_basis=declared_equal_split_not_measured`。本轮不拟合反向通道，不自动除2。
- xy面积由固定胞得出；坐标限现有直角z方向支持（a/b在xy、c沿+z，无xz/yz倾斜）。不以层状界面模型冒充 bulk。
- 准备及新增检查：CPU2/GPU0/6GiB/10分钟；唯一原生：1V100/1rank/CPU2/6GiB/20分钟；一次解析+消费：CPU2/GPU0/6GiB/10分钟。提交与资源由root统一负责，Slurm原生ID与终态保留。MD有限时限不适用于DFT。

## 最薄源与公共接口

第三窗口：`lammps_bulk_heat.py`（writer/parser/函数）与 `tests/test_lammps_bulk_heat.py`；独占 live `lammps.py`、`lammps_tasks.py` 的新 purpose 薄hook；准备脚本仅在 `workspace/reports/lammps-bulk-heat-domain-v001/native-producer/`。不碰 CLI/Study/旧界面语义。复用旧 `_parse_energy_rows`、`_parse_profile_frames` 和真实热浴命令，不要求重构公共框架。

源文件 `bulk-heat-source.json`，schema `mlcc.md-bulk-heat-source.v1`。`read_bulk_heat_outputs(directory, protocol, atom_map)` 保存：

```text
schema, units="metal", protocol
energy_rows[]: step, physical_time_ps, hot_reservoir_eV, cold_reservoir_eV
profile_frames[]: step, physical_time_ps, total_count,
  bins[]: bin_id, coordinate_reduced, coordinate_angstrom, atom_count, temperature_K
source_atom_ids, atoms (source/native ID及元素), cell_angstrom, atom_mapping_ref
geometry: area_angstrom2, normal_cartesian=[0,0,1], z_length_angstrom
source_files, missing_evidence
```

native result 键 `bulk_heat_source` 及保存源路径由第三窗口同时写明。步骤和时间行沿用原表定义。任务/job/Study/potential来源保存在既有Task/Result及消费者请求，不再复制整套来源框架。函数可直接读取source映射；所需额外字段双方点对点对齐并记录，不改旧schema语义。

原实施窗口：新 `bulk_thermal_transport.py`、`tests/test_bulk_thermal_transport.py`、live `cli.py`/`property_delivery.py`/MD Skill 的串行薄接线。公共 `build_bulk_thermal_transport(request_path)`；CLI `bulk-thermal-transport --request ... --output ...`；既有 `deliver-properties --domain-parameters` 同Study。消费者只读取保存源，不重解析轨迹/原始表。

请求schema `mlcc.bulk-thermal-transport-request.v1`，含 `study_path`、`model_path`、`source_path`、`task_path`、`result_path`；`observation_window={kind:step_range,start_step:1000,end_step:6000}`；`transport={direction_cartesian:[0,0,1],profile_bin_ids:[3,4,5,6,7,8],periodic_channel_count:2,heat_fraction:0.5,heat_fraction_basis:declared_equal_split_not_measured}`。80原子子Study为本次同Study；parent20源引用保留，不错误套用20原子的atom map。

root：本合同、计划、共享资源、Slurm/集成与审收；`workflow.py`若确需识别新源由root独占。所有人不是独占代码库，不回退或覆盖他人修改，交回后才改共享文件。

## 计算定义与最小结果

- 对选定原生热浴累计量与实际 ps 时间做普通线性拟合，复用已有 `_linear_fit`（单位/字段须改为实际变量，空间拟合不得携带duration_ps标签）。现有 LAMMPS tally 储能符号沿原生/已有接口核实：`P_hot=-slope(Q_hot)`，`P_cold=+slope(Q_cold)`，单位eV/ps并转W。原始两斜率/源定义均保留，不取绝对值，不翻转成期望方向。
- `J_z=heat_fraction*P_hot/area`，W/m²，显式沿+z；冷热收支/残差只报告，不设数值通过线，不用端点差代替拟合。
- 将选定 bins 的时间均温对 z(Å) 做线性拟合，输出梯度 K/Å 和 K/m、bins/坐标/温度/拟合残差。
- `kappa_z=-J_z/gradT_z`，W/(m K)。零梯度或缺必要数据时该量null并给直接原因；热流/梯度能单独计算的仍可用。负值及不匹配原样保留，不裁剪、不以稳态或势资格阻断系统交付。
- 领域产品至少包含 hot power、cold power、hot-cold net power、+z heat flux、+z temperature gradient、directional thermal conductivity；每项定义、单位、条件、坐标、atom mapping、source refs、status。`steady_state=unresolved`、有限采样及声明分流写入条件，生产资格不宣称。
- 仅新数学/空bin/零梯度与薄hook必要检查加一次真实demo；已经通过的节点不重跑。若失败只修失败节点。完成本路径后回原队列J5/J6，不做单字段发布或旧安装复验。

符号依据已由root读取官方 `stable_22Jul2025_update2` 的 [FixLangevin::compute_scalar](https://raw.githubusercontent.com/lammps/lammps/stable_22Jul2025_update2/src/fix_langevin.cpp)：累计力做功在输出处取负，故热源向系统输入功率采用原生tally斜率的负号。使用普通Langevin（不启用GJF），与现有interface_thermal._power符号一致。原始tally仍完整保留。
