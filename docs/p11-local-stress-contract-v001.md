# P11.13 显式原子组 virial 应力切片

本片实现固定胞、零速度 `run0` 的逐原子 virial 输出及显式原子组消费，不增加材料MD、DFT或温度矩阵。0.41热路径445/446及既有法向442/443不重复。

## 直接复用

- `lammps.export_lammps_data`、`validate_lammps_model`：source/native原子ID、type、Prism、晶胞与单位绑定。
- `lammps.pressure_tensor_to_source`：在求和并除显式体积后，输入压缩正bar张量，执行Prism旋转及bar→GPa，返回拉伸正张量。不能直接向它传bar Å³广延量。
- `md_thermo._observation_rows`：显式whole_record或step_range，不选稳态。
- `lammps_tasks.read_lammps_task`及`interface_sources`：实际Slurm终态、原生日志、来源、势和双父Study校验。
- 新dump仅含id/type和六个stress/atom分量；薄读取器复用原生整数/有限数值/Prism bounds函数，不改旧固定坐标/力dump或MD collection框架。

job45/105只有整体标量压力与位置/力；442/443有全胞压力张量和组力，均无逐原子virial。439是未运行Ni/BTO输入。它们不能直接生成局部应力，仅复用已有模型、Study、势和来源。

## 原生输入与输出

沿用create-lammps，`kind=run0`、`purpose=interface_local_stress`、`static_tensor=true`、metal、ppp、显式timestep及experiment_scope。`local_stress={"schema":"mlcc.local-stress-protocol.v1","contribution":"virial"}`。

在run0之前定义`compute mlcc_local_stress all stress/atom NULL virial`及逐原子dump，使原生per-atom tally由真实输出需求触发。结束后解除dump/compute。保存`local-stress.lammpstrj`的单帧step0及原始六列，不从全胞压力分摊到原子。

LAMMPS顺序为xx、yy、zz、xy、xz、yz，定义S=−(kinetic+virial)。本片关键词virial明确排除kinetic；原生metal输出为bar Å³，符号对应拉伸正stress×volume，并非已除原子体积的GPa。没有局部温度或热膨胀推断。

已读本站源码：GPU MACE为10 Sep 2025，固定`-sf kk`走`pair_mace_kokkos.cpp`，原始限制为`ERROR: mace/kokkos eflag_atom and/or vflag_atom not implemented.`。CPU EAM环境为22 Jul 2025 Update 4。两者版本/路径分别见`workspace/reports/local-stress-v001/native-source-observation.txt`。MACE允许显式准备输入，未经执行不伪造失败job；如果用户以后运行并失败，消费保留真实状态和原始日志，不替换引擎/势或填零。

## 指定原子组和体积

analysis schema `mlcc.local-stress-analysis.v1`，含显式observation_window和regions数组。每组为`region_id`、source `atom_ids`、`volume_angstrom3`及`volume_definition`。体积和定义可为null；不得按原子数、界面数或默认原子体积补值。regions为空代表尚未选组。

每个选中帧按ID求六分量广延量之和；先除声明体积V并取负得到压缩正P=−ΣS/V（bar），再复用现有Prism函数得到source Cartesian下的σ（GPa）。固定胞、固定V下逐帧张量的算术均值与先平均广延量再除V一致；保留逐帧/均值及体积定义。输出称`fixed_atom_group_virial_average`；这是所选原子对指定体积的平均贡献，不自动成为空间欧拉场、唯一原子应力或连续体应力。

缺体积时保留ΣS而σ=null；缺窗口/原生帧/组时只将依赖量保留unresolved。未知原子ID、错误type或胞映射、损坏原生表直接报原错。不从全胞pressure代替缺失的逐原子量。

没有显式无应力参考与温度/载荷历史时，`local_thermal_stress`仍为null；本片不构造热应力差量，该缺项不阻塞已实现的软件功能。

## 公共路径与最小验收

`local-stress --task <task.json> --request <analysis.json> --output <product.json>`；`deliver-properties --local-stress <product.json> --study <Study.json> --output <delivery.json>`。保留同Study、双父源、atom-map、协议、分析定义、Slurm状态和错误证据。

仅新增检查在v100 Slurm执行。原生命令检查明确选用既有job442的8原子Ni/Ni模型、Study、Ni_u3.eam和CPU站点，在1任务/1CPU、2GiB、5分钟allocation中执行一次run0（无积分）。将真实逐原子S对全胞显式体积求和，与同一次原生全胞pressure交叉核对；这只验证新输出的符号/单位/映射/求和闭合。另保留一组缺体积的真实广延量，数学夹具验证非平凡局部分组和旋转。

复用job439创建Ni/BTO MACE未提交输入和unresolved交付，不运行不受支持的MACE逐原子任务。CPU EAM是预先选定的独立工程fixture，非引擎失败后回退。准备job不伪造自身终态，后续消费job读取实际scontrol终态后接公共入口；主线负责版本/计划。
