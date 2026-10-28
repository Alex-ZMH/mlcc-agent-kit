# FEM 0.4.0：电热、AC-EQS 与二维电磁调用指南

保留原fem模块和公共协议，保留三个SI queued操作并新增三个 *_quantities queued操作；Windows固定adapter.py管理输入/单位、WSL调用、结果校验和产物，科学实现位于模块自有device_fem/extended/。不依赖experiments运行路径，不启动实验套件、参数扫描或另一套任务系统。

## 操作与支持边界

| 操作 | 模型 | 激励及结果 |
| --- | --- | --- |
| electrothermal_2d | 均匀线性介质、理想等势电极；DC导电/零损耗/规定AC介电损耗；陶瓷+Ni单向稳态热 | 实电势；C、Emax、U、P、T/温升/热阻；不声明完整复Y/Z |
| ac_eqs_2d | 双实数复电势EQS，均匀或半高度共形两介质；Ni理想等势、不发热；热可关闭 | RMS或peak复电势；Y/Z/Cp、导电+介电损耗及可选T |
| electromagnetic_2d | 严格二维Ex/Ey/Hz Maxwell，有限导电Ni+陶瓷+无损空气；mu_r=1；热可关闭 | 复RMS电流、显式闭合引导端口；Z/Y、分区P、电/磁能、能量等效C/L和可选T |

所有热模型为常系数顺序稳态：电/电磁场不接收温度反馈，无瞬态/磁滞/力学/3D/COMSOL。EM的PEC接触轨、有限Ni端柱、顶部馈电截面和底部磁壁是规定模型，不代表开域辐射或实际PCB回路。EM能量L包含参考面内馈电/回流，不是商业ESL；不声明已验收商业ESR/SRF。

## 科学输入和单位

[电热示例](examples/electrothermal.json)、[AC示例](examples/ac_eqs.json)、[电磁示例](examples/electromagnetic.json)全部是合成验证参数，不是标定材料或器件。各自严格schema位于schemas/*input.schema.json。

面向带单位输入，使用 `electrothermal_2d_quantities`、`ac_eqs_2d_quantities`、`electromagnetic_2d_quantities`，对应 `examples/<analysis>-quantities.json`。全部有量纲字段是严格 `{value,unit,source:{kind,reference}}`，units=`explicit_quantities`；旧 `_m/_V/_Hz/_S_m` 后缀去除。完整字段及schema见[多单位交接](EXTENDED_UNITS_HANDOFF.md)。允许公共白名单中的mm/μm、kV、kHz/MHz、mA、S/cm、热导/对流单位、°C等；未提供明确单位或来源则拒绝。count、eps_r、tan_delta、mu_r仍为有明确语义的裸计数/无量纲参数。

Windows通过唯一公共核心的normalize_fields转换；core1.0.0、catalog1.1.0。原始typed快照保持，另存canonical SI及逐字段quantity审计，含转换factor/offset/rule/version。无本地倍率表、摄氏偏移或fallback。SI副本重新经过既有科学validator，WSL仅接原SI操作，不重复缩放。电流RMS和电压rms/peak是物理幅值约定，单位转换不代替其处理。

原三个SI操作仍严格接受原字段：长度m、电势V、频率Hz、电导S/m、热导W/(m K)、h为W/(m² K)、绝对温度K、电流A RMS。其schema/示例未放宽；不得将mm/kV数字填入m/V字段。新多单位入口是增量契约，旧任务可读。

几何、材料、热参数、端口均要求来源。来源字段只是可追溯声明，不证明材料有效性；空白来源、未知/多余字段、不适定稳态散热、错模型/复数约定在部署之前拒绝。标准输入不接受后端命令或机器路径。

- ET loss_model=dc/lossless要求f=0、dc约定、实电势、tan_delta=0；lossless还要求sigma=0。ac_prescribed要求f>0、rms/peak、sigma=0，只用规定介电损耗，避免重复计入导电。ET必须启用热。
- AC要求f>0、rms/peak；DC由旧静电/ET入口处理。uniform时上下介质系数必须相同；half_height_layered以实际高度一半分区，不能自由指定隐式界面。两组复电势差必须非零。
- EM要求f>0、mu_r=1、非零可表示RMS电流，Ni为有限正电导且tan_delta=0、空气eps_r=1且无损；bus/feed/bottom全部明确为正。
- thermal.enabled=false时仍保留显式热配置供快照追溯，但不运行热或伪造T=300K，结果温度为null。定温边界要求h=0；Robin要求h>0；左右固体端冷却，其余绝热。

## Windows 调用

使用本机已核实的Windows Python3.11+（README中的绝对路径示例可用），项目根PowerShell：

```powershell
$FemPython = 'C:\Users\Xiang\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$env:MLCC_FEA_DEPLOYMENT = (Resolve-Path modules/fem/deployment/extended.example.json).Path
& $FemPython -B -m mlcc describe fem
& $FemPython -B -m mlcc preflight fem electrothermal_2d_quantities --input modules/fem/examples/electrothermal-quantities.json
# 下面会创建一次计算任务；仅在需要执行时运行
$r = & $FemPython -B -m mlcc run fem electrothermal_2d_quantities --input modules/fem/examples/electrothermal-quantities.json --defer | ConvertFrom-Json
& $FemPython -B -m mlcc worker $r.task_id
& $FemPython -B -m mlcc result $r.task_id
```

AC/EM分别替换操作及输入为ac_eqs_2d_quantities/ac_eqs-quantities.json、electromagnetic_2d_quantities/electromagnetic-quantities.json。旧SI操作和对应原例子继续可用。包装脚本run-windows.ps1也支持这些Operation，须显式传DeploymentFile。没有自动频扫或后台重试。

extended.example.json使用fem.deployment.v2/profile=device_extended_v1，仍为现有Ubuntu-24.04/fenicsx-env，单rank/单线程，最多150000实际三角形、240秒科学客户端预算；公共操作300秒外层预算。数值来自已审实验的资源包络，不是精度阈值。预检还使用保守面积网格估算；实际Gmsh在装配前检查单元上限。

**旧静电及旧多单位操作继续使用deployment/example.json（v1，50000单元、最长120秒）。** v2被旧操作拒绝，避免扩大旧操作预算。共享环境未安装、升级或替换。WSL超时/通信中断保留未知科学进程状态，禁止自动重提交，现有公共取消/原生回收限制不变。

## 结果与产物

输出使用[device.output.schema.json](schemas/device.output.schema.json)，完整科学诊断另存在diagnostics.json：

- electrical：总/陶瓷/Ni损耗、Emax、可适用的C/Y/Z、We/Wm/L；复数对为[实,虚]，AC/EM场均RMS exp(+jωt)。
- AC的capacitance_F=Im(Y)/ω（并联定义）；EM为2We/|Vport|²（能量等效）；ET为2U/ΔV²。不能混用三种含义。RMS能量使用0.5ε|E_rms|²、0.5μ|H_rms|²的周期平均约定，DC为静态储能。
- thermal：绝对T、温升、平均/热点热阻、热源与离散出热功率及独立原始梯度出热。零功率热阻为null，不是0。
- solution/含mesh.msh、VTU/XDMF/HDF5完整场、复数实虚/幅相、q/T/k/热流以及cell_transfer.npz单元映射；可选PNG直接从实际VTU绘制，注明纵向放大。零幅相位无定义，显示需屏蔽；z=0填充不是3D。
- input.original.json、input.canonical-si.json、unit_normalization.json、input.normalized.json、method_environment.json、native请求/响应/启动/logs及Windows校验hash完整登记。

查询status/result/artifact只读，不启动worker。原始场数组不塞入聊天；Agent从权威事实卡解释，不能改执行或QC。本轮无新LLM调用，新增操作的真实模型对话为not_checked；已有公共Agent框架/模块方法Skill可按已选operation使用。

## 验收与限制

[接入验收](EXTENDED_ACCEPTANCE.md)记录新公共任务、首次电磁序列化失败及修复、零损耗/Robin/分层/无热分支、旧静电精确回归和源函数AST一致性。科学适用性、真实材料/安装、独立器件对照、单任务收敛及原始通量/端口工程接受性保留not_checked。历史实验解析/频扫不自动附成新任务的通过检查。
