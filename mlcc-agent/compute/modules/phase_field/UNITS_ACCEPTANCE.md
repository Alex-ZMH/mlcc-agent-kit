# 单位系统增量验收（0.2.0，2026-10-22）

已实际实施steady_si/evolve_si、独立schema、Windows公共单位核心调用、四尺度无量纲化和独立SI结果/场/历史/图。旧steady/evolve及原始0.1验收、记录、失败和evidence.json未改写。本轮只写phase_field目录，不改Agent/Runtime、执行权、公共代码或其他模块。

## 模型与映射

推导见UNITS_DESIGN.md。独立尺度为l、P0、T、f0，均由输入明确给出正有限值与来源；耦合项导出phi0=f0*l/P0、E0=f0/P0，epsilon*=epsilon*f0/P0²、g*=kappa*P0²/(f0*l²)。固定profile约束a=-f0/P0²、b=f0/P0⁴、gamma=0、M=P0²/(f0*T)，不是任意SI Landau材料。二维电焓乘f0*l²后为J/m，三维乘f0*l³后为J；未生成没有厚度依据的二维总J。

单位倍率、别名、量纲校验仅来自公共mlcc/units.py 1.0.0 normalize_fields；模块只声明字段kind并核对payload/records及原值/语义一致性，没有私有单位表或fallback。原始用户input.payload保留，canonical SI和solver nd另存。新SI入口拒绝bare有量纲值、缺单位/来源/尺度、错维度、归一化记录、冲突/未知字段、非有限/不相容参数。网格/seed等离散字段不缩放。

## 真实任务

六个等价小任务位于`work/u-2ef28dde/project/outputs/tasks/`，均通过Windows公共CLI run/worker生成，3接受步至无量纲t=.15；无外部LLM。

| 维度 / 表示 | task_id | 单元 / 总DOF |
|---|---|---|
| 2D旧nd对照 | task-45faf932fb7b40c2a4865aedf8c8e3d5 | 64 / 90 |
| 2D SI | task-a318fa500d10471ebda8bbfec152fc99 | 64 / 90 |
| 2D等价单位 | task-64798864b6e944da940e176ca5819491 | 64 / 90 |
| 3D旧nd对照 | task-b1dd239fa87d4227a15ffff909c4c4c9 | 768 / 450 |
| 3D SI | task-7a4ebb353ac345b58711a9b653ac4b40 | 768 / 450 |
| 3D等价单位 | task-c00f2b50b7a548128eb2807a101945f4 | 768 / 450 |

合成尺度l=.001m、P0=1C/m²、T=.001s、f0=1000J/m³，仅为单位验收；每个source都明确synthetic_test，不是材料默认、用户材料或标定。等价表示包括1mm、100uC/cm²、1ms、1kJ/m³及pF/m、kV/m等；所有canonical SI输入、solver nd输入及SI摘要分别完全一致，原始输入hash不同。原始fields.npz（P/phi/E、坐标、连通性、全部P/phi时间历史）在每个维度的三种表示中逐字节SHA256相同，逐项数值最大差0；SI数组精确等于nd数组乘相应尺度，SI历史每帧核对。

读回证据`work/u-2ef28dde/native-unit-checks.json`不执行求解。二维电焓约-0.01284476835 J/m，三维约-7.548210205e-5 J；绝对值仅对应上述合成尺度和已列模型。三维核有实际z变化，SI图标明切片位置与m/C/m²，另保留完整体数据。已查看SI三维P切片和二维SI时间曲线，未把图片当数值验收。

另一个最终稳态任务`work/us-aa03098f/project/outputs/tasks/task-93baaa1ec2324b4e9e2a9ad048d1c1c9/`真实执行steady_si，64三角形/90总DOF。实际非零E*=.12下P*≈1.0553241847，核对P³−P−E*=0及均匀电焓解析式，SI电焓≈-0.02435881346 J/m。completed_time和energy_nonincrease为not_applicable，unit_mapping通过；预检明确“输入/物理视图SI、kernel/QC nd”。

稳态harness第一次错误套零外场固定点断言，原科学任务其实成功；修正验收断言后只读复用原任务，没有重算。失败脚本及调用文件保留，不改写为从未失败。

## 最终接口、审计与兼容

最后将审计拆为独立original_input/normalized_input/normalization_report/solver_input/reference_scales JSON。`work/ua-7157eef9/checks.json`在独立副本用最终WindowsAdapter重放稳态真实native响应，校验身份/字段/文件hash和新增审计文件，物理摘要不变；运输层为mock，明确属于保存原生证据重放，不算第八个科学任务。原任务未改动。

QC的原始非线性残差、Gauss、RT、能量判据一直在nd域，SI视图只增加映射/读回检查。RT系数和原始XDMF/HDF5/NPZ仍明确nd，未将其数值强贴SI。材料标定、独立实物、稳定性、每任务网格/时间收敛保持not_checked；提供尺度不等于获得材料有效性。

模块离线检查35项通过，含旧记录只读仍为0.1.0/dimensionless；公共精确源码副本76项、75通过/1符号链接权限跳过，见work/units-public-tests-final.log。公共新版测试需要原模块examples，初次隔离副本漏拷示例失败，补齐只读副本后通过，原失败日志保留。公共框架/核心原文件未改。core后续由main修复超长pointer索引异常边界，未改倍率；科学任务的执行时core SHA单列，当前核心的正常输入用离线对照，不重新求解。

原有AgentHost离线消费四操作、严格输入schema与input=null原值引用通过：work/host-compatibility-units.json。未新增在线LLM测试，不重写main此前真实Agent相场闭环验收。

复现：`python -B -m unittest discover -s modules/phase_field/tests -v`；`python -B -m modules.phase_field.harness.check_host --units`；显式新小任务用harness.verify_units --deployment FILE --run-real，已有数据只读对照在WSL模块根执行`python -B -m harness.check_units_native <qualification>`。入口/字段详见README和Skill。

机器索引为units-evidence.json，新增源码/共享核心指纹为UNITS_SOURCES.json。当前无公共接口阻断；部署快照、进程终止和长路径边界仍沿原INTERFACE_PROPOSAL，未扩大本轮物理范围。
