# RVE 分层验收（2026-10-23）

最终模块0.1.1 / mlcc.module.v1 / interface_version=1.0。只修改 modules/rve；公共 CLI 正常产生 outputs/tasks。没有可用 Git checkout，以 SOURCES.json / evidence.json 的文件 SHA256审计；不初始化/清理仓库。main 的首版状态/验收总账未修改。

## 框架与功能

19项默认轻量测试 passed，不启动WSL/FEM/模型；公共86项中85 passed、1 Windows符号链接权限 skipped。公共check valid；describe rve available、四项queued。测试实际覆盖strict schema/AgentHost provider编译、唯一单位核心/未来追加词表兼容/错误/超时、各分量SPD和负非对角项、原始快照与审计replay、精确覆盖/重复材料、错单位/来源/几何/计数/分辨率/预算、-I/其他cwd/含空格Bundle、预检无求解及不重试。日志见 work/module-tests-final.log、work/public-tests-final.log、work/structure-check.json、work/describe-rve.json。16份失败示例见 harness/failures.json，非有限JSON/overflow另由轻量测试覆盖。

## 真实本地求解

共15个成功新公共任务、38个接受的独立载荷：首批0.1.0为10任务/25载荷；最终0.1.1为5任务/13载荷，覆盖全部四操作及二维9晶粒、三维SPD负交叉项/绝热孔。另一次0.1.0原生3载荷已计算，但被Windows输出schema误拒绝，单列诊断，**不计成功任务或接受载荷**。历史实验95/81等张量只作只读来源，未作为新求解计数。

|案例 / 版本|task_id|单元|载荷|
|---|---|---:|---:|
|electrostatics-2d-layers / 0.1.0|task-e2be9198afa940259a55a2ba5a8ac1ac|254|2|
|electrostatics-2d-layers-equivalent / 0.1.0|task-7a42e6b7cfaa4702b652c1fd0c41ee2d|254|2|
|thermal-2d-layers / 0.1.0|task-a355d9306ad047c188f89c1f21e69ad9|254|2|
|thermal-2d-layers-equivalent / 0.1.0|task-7b6df883c2a041d181b07bfcafb7d982|254|2|
|electrostatics-3d-layers / 0.1.0|task-ef78a6a3120d470e90524b258e41e6b1|481|3|
|electrostatics-3d-layers-equivalent / 0.1.0|task-856561741c484db88cccb8582589b67e|481|3|
|thermal-3d-layers / 0.1.0|task-5581c7a6da844674aa2babae48cb77dc|481|3|
|thermal-3d-layers-equivalent / 0.1.0|task-5c491d406c1443a7be80e21698049584|481|3|
|electrostatics-2d-polycrystal / 0.1.0|task-d68cc63f65514f618361c6a56d8a4f77|9610|2|
|thermal-3d-sphere / 0.1.0|task-5e5916fe59c54552a10e20ed648124d7|3598|3|
|thermal-2d-layers-equivalent / 0.1.1|task-f672a40aad524cafbc16888980ae9ebe|254|2|
|electrostatics-3d-layers-equivalent / 0.1.1|task-e08b24fa8a9d4e56a4379be7388483a4|481|3|
|electrostatics-2d-polycrystal / 0.1.1|task-717c138243554387828b00419595d917|9610|2|
|thermal-3d-anisotropic / 0.1.1|task-9f711feb94b8404db2d3cc8d90514198|384|3|
|thermal-3d-cavity / 0.1.1|task-193677022bb44ac696993e44e6a25670|8053|3|


真实环境：Ubuntu-24.04，Python3.11.15，DOLFINx0.11.0，PETSc3.25.5 real float64，Gmsh4.15.2，NumPy2.4.6，UFL2026.1.0，h5py3.16.0，PyVista0.48.4；MPI rank1、OMP/BLAS/MKL线程1。每任务240s宿主预算，原生实际单元数见表，未安装/升级环境。

逐任务独立VTU/HDF5读回重建梯度/本构/平均通量/功、potential lifting与NPZ周期配对，保留原始误差。三维六面三角形双射和面/棱/角等价类审计；二维四角审计；网格/CAD分数、正单元、区域身份、线性求解、弱反力、Hill–Mandel、张量对称/SPD。不是只读取PASS字符串。全新接受任务各项最大原始误差：

- average_field_relative_error: 2.22063069e-15
- Hill_Mandel_relative_error: 6.64482487e-15
- weak_projected_residual: 6.39847926e-15
- PBC_fluctuation_relative_error: 0
- PBC_boundary_reaction_antiperiodicity: 9.8015045e-15

## 单位、解析与历史回归

四组2D/3D多单位对照canonical完全相同，有效张量及全部原生VTU点/单元数据最大绝对差0；原始Runtime输入逐字段等于input.original，shared core逐量replay通过，WSL无raw-unit二次缩放。8个分层任务解析相对误差最大 8.20661106e-16（源阈值1e-8）。最终0.1.1材料列表到canonical区域字典映射审计独立保存，最终来源关联与公共输入schema编译均核实。

|只读历史对照|相对张量差|绝对最大差|分数最大差|
|---|---:|---:|---:|
|electrostatics-2d-polycrystal|0|0|0|
|thermal-3d-sphere|0|0|0|
|thermal-3d-anisotropic|0|0|0|
|thermal-3d-cavity|0|0|0|


比较报告：work/real-20261023T045702Z/native-comparison.json；初批原始对照work/real-20261023T043741Z/native-comparison.json。各历史文件路径/SHA256与原始差值都在机器报告。相同网格确定性重放参考1e-12，源二维same_seed_replay；不推广为任意3D模型科学误差阈值。解析对照是额外证据，所有表内任务均实际FEM求解。

## 失败修复与证据分期

task-c37fb7fc74ad4e97b79dad399cd8ea49 原生计算与回读完成，单相体积分数1.0000000000000004被Windowsschema的maximum=1误拒绝，外层blocked，源记录/日志/场保留。修复schema按源面积/体积覆盖容差（2D1e-9、3D1e-8）接受浮点漂移，保留原始分数、不夹到1，不改变科学检查阈值。

另发现0.1.0动态材料字典不能由现有provider strict compiler消费；最终0.1.1改公开输入为带region_tag的严格材料列表，shared normalize_fields后确定性映射为源内核所需字典。早期任务保持其冻结schema/输入；无历史回写。最终5任务已使用新增来源关联/目录护栏/overflow-safe SPD/共享count与seed审计，sources.json中运行文件hash与交付一致。科学内核未因这次接口修复改变。

所有15个成功任务均在status/result/artifact及终态worker调用前后对record/产物/原生日志全文件SHA256比较，完全不变。证据为各work目录的*-read-only-hashes.json；未手改record或删锁重跑。没有新造真实原生超时/进程杀除试验，超时/不重试边界是离线控制测试；Linux终止确认not_checked。

## 科学适用性与未检查

真实执行real_computation与数值协议检查通过，不是mock；材料全部synthetic_test。每任务mesh convergence、统计代表性、真实材料标定/实际BaTiO3或器件适用性均not_checked，公共numerical汇总也因mesh_convergence保持not_checked。单次PBC/能量通过不代替网格研究。原始DG0跳跃是诊断，不声称H(div)逐点强守恒。三维GB/shell多晶公开拒绝，来源PARTIAL未升级；2D25/36与3D16/27生成能力未充分验证。未跑本轮核壳/椭球/旋转层/affine全组合、二维热孔、三维无GB多晶全范围；这些保留来源算法，不能宣称本轮全面回归。

在线LLM闭环not_run；离线AgentHost/Skill/strict schema消费通过，事实卡及后续真实两轮脚本见LLM_ACCEPTANCE.md。main/科学负责人独立审阅后再决定首版覆盖，不由本模块自授。
