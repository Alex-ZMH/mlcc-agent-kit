# 交 main：RVE 0.1.1

已完成审阅、迁移实现、Windows公共CLI真实计算和独立回读。四个queued操作为homogenize_electrostatics_2d、homogenize_thermal_2d、homogenize_electrostatics_3d、homogenize_thermal_3d；接口1.0，公共层无需修改。仅modules/rve交付，outputs/tasks由Runtime正常生成；未改主验收总账或首版覆盖。无阻塞公共缺口；部署冻结/外部终止确认与未来梯度/角度kind建议见INTERFACE_PROPOSAL.md。

最终公开材料输入为严格条目数组，条目有region_tag，精确覆盖且不许重复；数量source非空，矩阵逐分量经唯一UNIT核心。Windows规范化/部署/外壳，WSL只算已验证的维度专有内核；专业环境未安装/升级。源路径、版本、SHA256、改动说明与79个只读审阅文件、35个运行文件hash见SOURCES.json，当前核对无变化。初始模块未接入登记、分期修复原因见REVIEW/ACCEPTANCE。

验证：模块19项、公共86项（85通过/1跳过）、structure valid、describe available；15成功任务/38接受载荷，最终0.1.1为5任务/13载荷、四操作全覆盖。另1次原生已计算但schema误拒绝的3载荷保留为诊断，绝不算成功。四组多单位原生场差0，四项历史张量回归通过，原始差见下表。完整原生索引[evidence.json](evidence.json)、[ACCEPTANCE.md](ACCEPTANCE.md)。

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


|只读历史对照|相对张量差|绝对最大差|分数最大差|
|---|---:|---:|---:|
|electrostatics-2d-polycrystal|0|0|0|
|thermal-3d-sphere|0|0|0|
|thermal-3d-anisotropic|0|0|0|
|thermal-3d-cavity|0|0|0|


## 实际可复制命令

以下worker/result/artifact读取已完成真实task；run命令会新建任务，其新ID应使用该次输出，不能把新run和旧worker当成同一任务。完整已执行argv分别保存在work/real-20261023T043741Z与work/real-20261023T045702Z各*.command.json，未要求新求解时只执行读取命令。

```powershell
$RvePython = 'C:\Users\Xiang\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$env:MLCC_RVE_DEPLOYMENT = 'D:\Zhaoxiang\code\mlcc-main\modules\rve\deployment\example.json'
& $RvePython -m unittest discover -s modules/rve/tests -v
& $RvePython -m unittest discover -s tests -v
& $RvePython -m mlcc check
& $RvePython -m mlcc describe rve
& $RvePython -m mlcc --bindings modules/rve/deployment/local-bindings.json preflight rve homogenize_thermal_3d --input modules/rve/examples/thermal-3d-cavity.json
& $RvePython -m mlcc --bindings modules/rve/deployment/local-bindings.json run rve homogenize_thermal_3d --input modules/rve/examples/thermal-3d-cavity.json --defer
& $RvePython -m mlcc --bindings modules/rve/deployment/local-bindings.json worker task-193677022bb44ac696993e44e6a25670
& $RvePython -m mlcc result task-193677022bb44ac696993e44e6a25670
& $RvePython -m mlcc artifact task-193677022bb44ac696993e44e6a25670 artifacts/effective_material.json
```


两批显式harness实际调用：`python modules/rve/harness/run_real.py --execute`（首批0.1.0十例）以及`python modules/rve/harness/run_real.py --execute --case electrostatics-2d-polycrystal --case thermal-2d-layers-equivalent --case electrostatics-3d-layers-equivalent --case thermal-3d-anisotropic --case thermal-3d-cavity`（最终0.1.1五例）。首批材料格式随最终接口升级，重放请用当前examples的列表格式；历史任务原始输入保持不变。最终对照命令在README/原生比较脚本，报告work/real-20261023T045702Z/native-comparison.json。

## main 审阅边界

先看公开execution/evidence_kind/quality，再看原生input/环境/网格/材料/各load/独立readback；不能以代码0或PASS字符串代替。实际张量和负交叉项、热孔full-cell平均均可由场复核；原始DG0通量跳跃不等于强守恒。MSH坐标归一化，VTU/XDMF/HDF5/NPZ为m，二维材料单位无虚设深度。所有status/result/artifact/终态worker后record和产物hash不变。

mesh convergence、统计代表性、实测材料标定、器件适用性、未跑的形态/组合及Linux超时终止确认保留not_checked；3D复杂GB/核壳多晶拒绝，未推广历史PARTIAL。可调用能力与本轮新算例覆盖在MIGRATION_MATRIX/ACCEPTANCE中分开，main自行核对科学负责人签核并更新主状态。

现有AgentHost四操作严格schema编译和方法Skill加载通过。真实LLMnot_run，最小合成输入examples/thermal-3d-anisotropic.json、真实任务事实卡和一次计算＋同会话只读追问脚本已备好，见LLM_ACCEPTANCE.md。在线数据外发应由后续chat明确授权；本轮没有在线模型调用。
