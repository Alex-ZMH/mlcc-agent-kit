# 四尺度接入实施方案：对齐 DFT/MD 调用方式

2026-10-28；本文件以用户本轮最新范围为准，补充此前准备材料。阶段仍为探索与实施设计，没有迁入生产科学代码或提交服务器计算。

## 已确认的目标和边界

- 沿用同事按 Zeus 构建的本地调试工作台，未来沿同一路径上线 Zeus；本项目负责接入已有相场、RVE、FEM、SPICE 四模块。
- 各尺度独立计算，通过同一个对话入口选择能力；不实现尺度传参、材料包自动注入或强制 DFT→MD→FEM 流程。
- 对齐同事 DFT/MD 的调用组织：专业输入/创建器 → TaskRecord → 同一 SiteRunner → SSH/Slurm → 收集/专业解析 → 结果交付。
- **用户最终决定：DFT/MD 保留自己的单位体系，不接本项目单位归一器，不要求走 SI。** 本轮不扩展其单位词表、输入或解析器。四模块已有单位处理原样随包部署。
- 原子尺度代码、势、方法与科学验收仍由同事维护；不因集成而重写科学内核。

## 可行性与已经核对的依据

可以接入，主要工作是确定性适配、任务合同和能力包装。四模块已具备 `module.json`、专业schema、Adapter、科学入口与 `native_linux` 部署；FEM/相场/RVE使用现有fenicsx环境，SPICE使用现有spice环境。它们在Slurm分配的计算节点中调用本机科学进程即可，不需要WSL转发或第二层SSH。

同事的 `site_runner.py` 已接受显式command/environment_script/resource_request/transfer_paths/collect_paths，负责prepare/transfer/submit/query/cancel/collect。collect支持 `{remote,local}` 显式映射，能够收回我们的独立结果目录。上述是源码可行性判断，不是新服务器闭环已通过。

同事的实际工作台源码没有随公开仓库提供，但这不阻塞先开发能力包、CLI、任务创建和结果适配。聊天宿主阶段只需把新增专业入口接到已有工作台，不另建前端。最终同会话调用验收仍需在该实际工作台完成。

## 用户最终会看到的路径

```text
同一个对话框
  → 选择 DFT / MD / 相场 / RVE / FEM / SPICE 的实际操作
  → 领域 Skill 收集明确输入，程序验证并准备任务
  → 既有 prepare → transfer → submit
  → 公司服务器 Slurm 中执行所选尺度
  → query / collect → 专业结果与 QC
  → 同一对话解释、追问、查看图和文件
```

一个尺度的结果不会自动进入另一个尺度。统一的是调用方式、任务管理和结果入口，各自模型、参数、单位和科学判断仍按专业合同。

## 与 DFT/MD 对齐的新增入口

建议在同事 `mlcc-agent/src/mlcc/` 增加小型 `scale_tasks.py`、`scale_results.py` 与受控执行桥接，复用其CLI分派和TaskRecord。命令名称为设计示意，尚未实现：

```text
mlcc create-scale --module fem --operation electrostatics_2d_quantities --input INPUT.json --site SITE.json --request REQUEST.json
mlcc prepare --site SITE.json --task TASK.json
mlcc transfer --site SITE.json --task TASK.json
mlcc submit --site SITE.json --task TASK.json
mlcc query --site SITE.json --task TASK.json
mlcc collect --site SITE.json --task TASK.json
mlcc parse-scale --task TASK.json
```

前一条专业创建器相当于现有create-abacus/create-lammps；中间六步直接复用，末尾接专业结果。是否额外包装为MCP工具由实际宿主接线决定；不把现有7个生命周期工具误当成已经支持自然语言创建新专业任务。

| 改动位置 | 实施内容 |
| --- | --- |
| `scale_tasks.py`（新增） | 白名单module/operation；读取专业schema与输入；生成专业请求及TaskRecord，不启动科学求解或提交作业 |
| `scale_results.py`（新增） | 读取收回的完整 `mlcc.result.v1` 与已登记产物；核对platform/runtime任务关联、模块/操作，保留execution、QC、单位和错误 |
| `cli.py` | 注册创建/解析/交付入口；现有DFT/MD命令及参数保持可用 |
| `agents/mlcc/AGENT.md` 与模块Skill | 更新“FEM/相场不支持”的旧范围，新增四尺度操作、输入要求、单位/模型限制和调用说明；仅在接通后标为可执行 |
| Bundle / 能力迁移账本 | 保留旧Bundle能力，登记新增四模块操作；不向Bundle v2虚构modules字段，不复制第二套AgentHost |
| `standalone/continuum/`（候选） | 放完整受控计算包：四模块 + Runtime/契约 + 唯一UNIT实现 + Scientific Core，保持相对路径；独立解释器和固定入口执行 |
| 新增桥接 tests | 创建不提交、固定命令、结果/失败读取、只读不重跑、任务身份与路径映射、旧DFT/MD入口兼容 |

当前两套Python包都叫 `mlcc`，不能直接装进同一解释器。首切片可用固定进程隔离并显式验证加载路径；也可在实施时将我们的执行包改为 `mlcc_compute` 等无冲突名字。四模块科学代码不因公共包重命名而变化；最终取舍以实际迁移成本与兼容性为准。

## TaskRecord / 执行 / 结果的具体合同

1. **平台任务是调度权威**：新任务使用实际backend/模块标识，不冒充abacus或lammps。保留module_id、operation、module/interface版本、输入schema、科学输入和明确资源；只提供该模块真正需要的几何/网格/电路引用，不伪造原子模型。
2. **创建与预检分开**：客户端可做schema和静态约束检查；科学环境探测在已选站点上执行，不用客户端WSL缺依赖判服务器不可用。若需要远端预检，经明确的Slurm路径完成，不能SSH到登录节点运行科学探测或后处理。
3. **同一个Slurm作业内运行计算包**：已有SiteRunner提交一次；桥接在分配内调用模块Runtime/worker与native_linux入口，不再提交第二个Slurm作业。现有Runtime可作为内部执行/QC/产物封装，不另启动其AgentHost或常驻任务服务。
4. **部署显式绑定**：保留fenicsx/spice独立环境，配置本轮冻结源码根和预算，不自动换后端或安装环境。模块请求只含科学输入；部署路径/解释器由宿主管理。源根、输出路径必须满足native_linux映射约束。
5. **输出目录显式回收**：运行期结果必须落在已声明的可信根；通过同事现有collect映射收回 `record/result`、公开artifacts及诊断。原生场文件/轨迹不进LLM请求。任务间不覆盖，TaskRecord关联平台task、内部Runtime task和Slurm job，三类身份不混用。
6. **状态不压成一个成功字段**：Slurm完成、Runtime执行成功、numerical/scientific QC分别保留。parse-scale不把COMPLETED/0或读取成功升级为科学通过。取消先走现有scancel，核对实际终态，再对账内部状态；不删除锁重跑。
7. **前端结果尽量复用**：摘要、图/曲线、张量/标量、原生文件链接接到原查看器；Study只负责归属和来源，不触发尺度转换。独立科学任务不应因为缺少不相关原子模型/上游材料包而被阻止。

## 实施顺序与完成标准

1. 在当前集成分支白名单导入四模块与必要公共依赖，排除work、outputs、密钥、机器配置和参考树；记录源码版本与模块26操作清单。保持DFT/MD原有入口。
2. 先完成一个操作的create-scale → 共用runner → parse-scale。建议从已有小规模FEM静电quantity操作起步；这是实施建议，实际工况/资源按明确请求确定。原有单位审计与原生产物同时贯通。
3. 在WSL做不依赖服务器求解的合同/错误回归，再在公司服务器个人目录 `/home/v100/projects/mlcc/zhaoxiang/` 的独立批次验证一次真实完整任务；后续按模块逐个补相场、RVE、SPICE真实切片。
4. 补同一工作台会话的专业请求/执行/解释/只读追问，及从已有DFT/MD结果查询切换到四模块任务的测试；切换不继承另一尺度的科学参数，不重算原任务。
5. 逐项接通26操作，按新增适配路径保留适当真实/失败证据，更新能力迁移账本；公共/专业回归及实际工作台调用验收完成后再PR/merge。

本次不将历史119项公共回归或13项调度层单测当成新集成验收。真实服务器计算、六尺度统一会话和新桥接行为在实施前均为 `not_checked`。

## 单位归一器探索结论与最终决定

本轮先做了16项只读准入探测，记录在 `units-admission-probe.json`：现有工具接受5项（nm、ps、K、摄氏温度、热导率），拒绝11项原子尺度单位/种类（Å、angstrom、Bohr、fs、eV、Ry、Hartree、力、压力、应力、摩尔质量）。这是现有词表范围的证据，拒绝不表示求解器故障。

代码也显示同事已有自己的单位处理：ABACUS显式Ry/Bohr及原生应力记录，LAMMPS限制metal体系、显式ps/angstrom等；`continuum_parameters.py`另有领域出口换算和坐标/Voigt/应力符号逻辑。

**用户随后明确决定不接DFT/MD单位归一器，因此以上探测仅归档，不转化为实施任务。** 不扩展eV/Ry等词表，不替换ASE常数，不迁移既有转换，不把DFT/MD输出强制转SI，也不为后续可能的尺度传递提前搭建转换层。四模块现有UNIT继续工作；单位共存不妨碍共用对话和Slurm调度。
