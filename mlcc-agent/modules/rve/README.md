# RVE 0.1.2：静态线性材料均质化

Scientific Core V0.1：本模块 0.1.2 显式消费共享数值包 0.1.0，operation/物理模型/专业 schema 不变。部署须携带 Bundle 中的 `scientific_core/`。见 [本次接入与等价验收](SCIENTIFIC_CORE_ACCEPTANCE.md)。

四个独立 queued 操作：`homogenize_electrostatics_2d`、`homogenize_thermal_2d`、`homogenize_electrostatics_3d`、`homogenize_thermal_3d`。Windows 标准库 Adapter 使用唯一共享 UNIT 核心；现有 WSL/FEniCSx 只计算。模块迁移两个已验证实验内核，不开发新科学模型、不 import experiments/FEM/相场。真实执行与材料/器件科学适用性分开，后者 not_checked；是否首版覆盖由 main/负责人决定。

## 输入

四份独立 strict schema 在 schemas/，仅公共验证器子集。数量为 `{value,unit,source:{kind,reference}}`，来源必填非空；materials 为严格条目列表，每项有 region_tag（数字字符串）且不许重复，必须精确覆盖全部区域。该表示可被现有 AgentHost 严格输出编译器消费；没有默认材料、角色优先覆盖或按 grain ID 派生值。

|几何 kind|除 kind/physical_lengths/pore_fraction 外的必需且唯一字段|区域|
|---|---|---|
|homogeneous|无|10 matrix|
|layers|normalized_fraction, axis|10 matrix,20 inclusion|
|2D rotated_layers|normalized_fraction|10,20；固定原实验 45° 法向|
|2D circle|normalized_radius|10,20|
|2D ellipse|normalized_radius, normalized_aspect|10,20；固定零角度|
|3D sphere|normalized_radius, normalized_center|10,20|
|3D ellipsoid|normalized_axes, normalized_center|10,20；固定零角度|
|core_shell|normalized_radius, normalized_shell；3D另需 normalized_center|10 matrix,20 core,30 shell|
|polycrystal|grain_count, seed, normalized_gb_width, normalized_shell, jitter|100+i core/grain；有shell时200+i；有GB时3000|

pore_fraction>0 另有9000 pore；精确覆盖由代码检查。2D 多晶计数4/9/16/25/36，25/36仅来源生成能力，未充分验收；3D8/12/16/20/27，本版必须 GB/shell 都为0。源支持但有限验证的三维实体GB/核壳多晶和 extrusion 均未公开。当前公开组合的本轮实际验证清单见 ACCEPTANCE.md，未运行组合不写 passed。

physical_lengths 为 d 个 length 量值；2D必须正方形，3D可长方体。normalized_* 全部无量纲，不与物理半径/厚度混用。boundary_condition 为 periodic 或 affine_dirichlet（独立参考）；pore_model 为 explicit 或仅热 insulating_cavity（必须有孔）。热绝热孔仍需9000身份材料记录，正系数记录不参与求解；有效热流按完整单胞面积/体积平均。静电孔必须显式正介电相。

材料条目为 `{region_tag:"10",representation:"isotropic",scalar:<quantity>,applicability:<text>}` 或 `{region_tag:"10",representation:"tensor",tensor:[[<quantity>]],applicability:<text>}`；scalar/tensor互斥。静电输入是相对εr / 1，导热 W/(m K) 或公共登记非SI表示。张量全 d×d、有限、对称、SPD，负非对角项可以合法。取向元数据不执行本构旋转。所有示例是显式合成数据，非实测材料。

每载荷固定 G=eye(d)：电场1 V/m，热负温度梯度1 K/m，热场参考300 K；未开放任意温度梯度、角度单位或温度工况。2D只算x/y，3D真正x/y/z；不补z。量纲/审计/坐标见 [UNIT_DESIGN.md](UNIT_DESIGN.md)。薄层分辨率和单元上限来自源实现；宿主另有显式预算。错误不会自动换组织/网格/后端。

## 本机命令

在项目根 PowerShell，使用已核实解释器和独立绑定：

```powershell
$RvePython = 'C:\Users\Xiang\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$env:MLCC_RVE_DEPLOYMENT = 'D:\Zhaoxiang\code\mlcc-main\modules\rve\deployment\example.json'
& $RvePython -m unittest discover -s modules/rve/tests -v
& $RvePython -m unittest discover -s tests -v
& $RvePython -m mlcc check
& $RvePython -m mlcc describe rve
& $RvePython -m mlcc --bindings modules/rve/deployment/local-bindings.json preflight rve homogenize_thermal_2d --input modules/rve/examples/thermal-2d-layers.json
$RveTask = & $RvePython -m mlcc --bindings modules/rve/deployment/local-bindings.json run rve homogenize_thermal_2d --input modules/rve/examples/thermal-2d-layers.json --defer | ConvertFrom-Json
& $RvePython -m mlcc --bindings modules/rve/deployment/local-bindings.json worker $RveTask.task_id
& $RvePython -m mlcc result $RveTask.task_id
```

真实小任务全清单由显式 `& $RvePython modules/rve/harness/run_real.py --execute` 运行；默认测试绝不启动 WSL、Gmsh/FEM 或在线模型。每次 run 都是新任务，需要算力；读取已经完成 task 不用此命令。部署迁移、隔离、超时/原生PID核查见 [deployment/README.md](deployment/README.md)。

## 输出及核查

公共 results 是严格维度匹配的轻量摘要，引用 `artifacts/effective_material.json`、`readback.json`、`coordinates.json`、各方向VTU。有效材料包含完整张量/单位、区域身份/分数、材料/来源关联、各实际载荷/平均场通量/功、边界和孔模型、坐标/场引用与限制。归一化Gmsh网格和SI场区分。三份原始/SI/单位审计、kernel输入、来源/环境、网格与周期审计、逐载荷VTU/XDMF/HDF5/NPZ、metrics/原始求解误差均保留。

P1周期等价类消元、四角或三维面/棱/八角、零均值常数规范沿用来源；独立VTU/HDF5回读重建梯度、本构、平均通量/功、lifting和PBC。原始DG0法向跳跃只是诊断，弱反周期反力不是H(div)强守恒。数值协议出处见 protocols/ 与 SOURCES.json，不设材料或产品阈值。

状态/result/artifact/终态worker不重算，哈希证据见真实harness目录。失败保留原生stderr、配置、部分场；客户端超时不证明WSL终止，不删锁/不自动重提。不提供云/Slurm、Web/viewer、AC、弹性、热膨胀、断裂、铁电耦合或自动跨尺度注入。

交接入口：[MAIN_HANDOFF.md](MAIN_HANDOFF.md)、[ACCEPTANCE.md](ACCEPTANCE.md)、[MIGRATION_MATRIX.md](MIGRATION_MATRIX.md)、[SOURCES.json](SOURCES.json)。后续真实Agent闭环准备见 [LLM_ACCEPTANCE.md](LLM_ACCEPTANCE.md)，本轮在线模型 not_run。


## 2026-10-26 可选 native Linux 部署接口

新增显式 `transport=native_linux` 的独立部署 schema 与 `deployment/native.example.json`，保留原 WSL 配置和科学输入。依赖在所选 Deployment 预检中确定验证，module.json 不再无条件要求 wsl.exe；这不表示后端已安装或科学预检已通过。使用同一 science_entry.py、独立 Conda Python 和原 UNIT/QC，不经 shell/SSH/自动回退。

配置、版本、检查和临时服务器验证后清理边界见 [main 交接](../../docs/server-deployment-2026-10-26/main-handoff.md)。新增接口未在本机运行科学求解，也不表示服务器永久部署或远程 Agent 已上线。当前源码指纹见 `NATIVE_LINUX_SOURCES.json`；旧 SOURCES / SCIENTIFIC_CORE_SOURCES / UNITS_SOURCES 继续保留为历史冻结。
