# P11 小载荷法向响应首切片合同

输入来源复用 job439 的双源周期界面/Study/LAMMPS 接口。首个明确实现为固定晶胞、A 层固定、B 层刚性平移的约束静态响应；不自动执行材料 run0、MD、DFT 或训练。本轮在 v100 Slurm 只验收新增数学、输入和解析路径。主线管理版本和 plans。

## 物理定义

显式单位法向 n 与已保存界面 +z 法向一致，面积 A 与模型面内面积一致；调用方逐个列出 fixed_atom_ids（全部 A 层）和 moving_atom_ids（全部 B 层），两组不交叠且覆盖模型。全胞坐标除 B 层沿 n 的位移 q 外全部固定，没有最小化、温控或时间积分。加载点由调用方显式提供，不代选范围、速率、温度或势。

q 为 B 相对参考构型的刚性平移（Å），原生 B 层合力为 F_B（eV/Å）。外部约束反力 R=-F_B·n=dU/dq；归一化广义牵引 T_q=R/A×160.21766208 GPa。同时保存 A/B 合力及总力残差。它是该复合胞沿 q 路径的响应。

两个周期界面数明确保存为 2，AB 开口导数 dq_AB/dq=+1，BA 为 -1；因此 T_q 对应两处贡献之差。**不除以 2，不把它标成串联界面的传递牵引**。若共同开口使两界面均增加 q，则 dU/dq=A(T_AB+T_BA)；只有另外证明等价并定义共同开口后才可能用 2A 归一化。本切片不实现共同开口路径，也不从现有刚性平移推断该结果。

逐相邻点输出 ΔT_q/Δq（GPa/Å）以及 ΔU/(AΔq) 对应的区间能量导数（GPa）；这是显式路径区间割线，不做平滑、自动拟合或材料模量推断。同 q 的相邻点斜率为 null 并标记 undefined_zero_displacement_interval。若最终卸载点显式回到首点 q，则报告原始能量/反力闭合残差；这是规定坐标返回的闭合检查，不代表弛豫后的卸载恢复。缺返回点保留 unresolved。

## 输入与函数

沿用 create-lammps 的 study/model/potential/site/request，protocol.kind=`interface_normal`；units=metal，boundary=ppp，ensemble=none，static_tensor=true，purpose=`interface_normal_response`，experiment_scope 明确工程范围，timestep_ps 显式。最小扩展既有静态候选势验证，保留真实任务用途；势仍由请求明确提供。新增 protocol.normal_response：

```json
{
  "schema": "mlcc.interface-normal-protocol.v1",
  "kinematics": "fixed_cell_rigid_side_translation",
  "normal_cartesian": [0, 0, 1],
  "area_angstrom2": 16.0,
  "interface_count": 2,
  "fixed_atom_ids": [0],
  "moving_atom_ids": [1],
  "points": [
    {"point_id": "reference", "branch": "reference", "displacement_angstrom": 0.0},
    {"point_id": "load", "branch": "loading", "displacement_angstrom": 0.01},
    {"point_id": "return", "branch": "unloading", "displacement_angstrom": 0.0}
  ]
}
```

上例仅说明格式，不是生产参数；实际原子 ID 必须完整明确。首点 q=0/reference，至少两点，点序由请求决定。

- `lammps_interface_normal.validate_normal_protocol(protocol)`、`normal_input_commands(protocol, atom_map)`、`normal_output_files(protocol)`、`parse_normal_outputs(directory, method, atom_map)`：薄原生适配。复用既有数据导出、势装载和 Prism/原子映射。
- `interface_normal.normal_response_from_points(protocol, atom_ids, points)`：纯领域计算。points 每项携带 point_id、energy_eV、positions_angstrom、forces_eV_per_A；只处理显式原生源或明确标为 mathematical_fixture 的检查数据，不生成伪原生数据。
- 公共 `interface-normal --task task.json --output product.json`：完整原生任务调用已有 read_lammps_task 后计算；未运行实例返回 unresolved/null 并保存真实 TaskRecord 状态，解析错误保留原错。
- `deliver-properties --interface-normal product.json --study ... --output ...`：将同 Study 的约束法向响应或该实例的未决状态接入交付。

## 原生输入/输出

复用现有 v100 LAMMPS 输入基础。先显式 group ID 映射；每个点按相邻 q 差值 displace_atoms moving move ... units box，随后 run 0（默认 pre yes，更新力）、write_dump 保存全部原始力和 unwrapped 坐标（xu/yu/zu）。禁止 fix setforce 抹掉反力。每点用 print 保存可定位的 MLCC_NORMAL 索引与原生 pe，dump.normal-0000 等文件按顺序编号，不从用户标签构造路径。

原生 consumer 核对 method、单位、Prism、原子 ID/类型、点序和 unwrapped 显式位移路径，保存每点原始能量/力、log/dump 来源。现有 Slurm runner、TaskRecord 和四个 task-local 界面来源文件继续复用，新的采集文件随协议列明。

当前无已保存的真实材料界面响应。主线补充允许一次极小 Slurm 无积分 LAMMPS 工程命令接口检查：使用现成 Ni EAM 工程势及 CPU 引擎，显式 Ni/Ni 8 原子输入夹具，q=[0,0.01,0] Å，1 CPU、1 GiB、2 分钟，证明原生命令→输出→consumer；不作为材料性质/候选势筛选，不下载或另选势。具体已有引擎/势路径在只读核对后记入验收脚本。其余数学检查明确标为 mathematical_fixture，不用手写假日志替代原生验收。job439 的已有模型/Study复用于未运行实例输入，不重复439生成或11项旧检查。

已只读核对的引擎为 `/home/v100/projects/mlcc/.venv-lammps-2025.7.22.4.0/bin/lmp`，已有版本记录 `LAMMPS (22 Jul 2025 - Update 4)`，环境脚本 `configs/lammps-mpich-env-v001.sh`。势来自现成 `development/0.10.0/project/workspace/resources/lammps/Ni-u3-stable22Jul2025-update4/Ni_u3.eam`，来源 LAMMPS stable_22Jul2025_update4，Foiles/Baskes/Daw, Phys. Rev. B 33, 7983 (1986)，保留同目录 source.json/LICENSE/README.potentials。仅显式复制 descriptor 的新工程模型 ID 绑定，原势身份/来源/许可不变。两侧使用已有 ni-fcc-engineering/v001，target=3.52I Å、repeat=[1,1,1]、gap_ab=gap_ba=1.76 Å。该输入为命令接口夹具，不新增材料配方。

验收分为两项Slurm软件作业：第一项仅新增单测/输入生成和一次原生引擎执行，TaskRecord绑定其真实作业号，执行期间不伪标COMPLETED；第二项读取第一项实际scontrol终态后消费原生输出并同Study交付，既有材料缺数据实例单独保持unresolved。

命令语义参考官方 displace_atoms、run、write_dump 文档：https://docs.lammps.org/displace_atoms.html 、https://docs.lammps.org/run.html 、https://docs.lammps.org/write_dump.html 。本轮不把线上新版本文档作为本机新增能力证据；只使用现有版本长期支持的基础命令，实际引擎执行留给显式计算任务。
