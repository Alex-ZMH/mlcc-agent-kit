# 二维 MLCC 器件有限元来源审阅

历史审阅快照：基础静电现已实施，当前状态见README、module.json及ACCEPTANCE；本文的“本轮未实施/not_integrated”指审阅阶段。

审阅日期：2026-10-21（Asia/Shanghai）。本轮边界：只读审阅、现有小算例复核及迁移方案；没有实施科学代码迁移，没有新增可执行操作。

## 1. 目录与审阅基线

- 目标：`D:/Zhaoxiang/code/mlcc-main`。根 AGENTS.md、README、architecture/protocol/development/v1-scope、公共 schemas、`templates/module/`、`framework_selfcheck` 及运行层代码已读。
- **模块沿用 `fea`**：`modules/fem/module.json:2–12` 已登记 scientific / not_integrated / adapter=null / operations={}；`docs/v1-scope.md:13–22` 将器件层登记为 fea。遵照用户“已有 ID 优先”的要求，所有交付写入此目录，不建立 device_fem_2d。
- 来源：`D:/Zhaoxiang/code/fem-general-main`，HEAD `9ba35c43956aa28d7b19801570eed84b2edf0915`。本轮 `git rev-parse` 和跟踪文件 status 核对成功；status 未显示跟踪文件改动。
- 同级存在 `fem-general`。两个 README 都保留“canonical active root=fem-general”的历史文字；但指定来源的 `start-cae-web.ps1:6–8,29–34`、`scripts/start_cae_web.sh:6–16` 明确绑定 fem-general-main，且其 `src` 有实际 MLCC、耦合、CAD 实现。故选择用户指定且代码吻合的 fem-general-main，并非仅凭目录名。未修改 Git safe.directory；另一目录 Git 查询因 ownership 拒绝不影响本来源识别。
- 下文 **S/** 表示上述来源根，**T/** 表示目标根；行号对应当前磁盘快照，范围用于定位。`review_work/source_before.json` / `source_after.json` 保存 201 个源 Python/关键配置文件的 SHA-256；`source_integrity.json` 显示这些文件在单次求解前后不变。该核对不等于整库、所有运行数据或全文件系统审计。

## 2. 目标框架实际接入方式

| 环节 | 当前实现及新模块责任 |
| --- | --- |
| 发现 | 文档称 `modules/*/module.json`；实际 `T/mlcc/registry.py:116–139` 遍历 modules 的每个子目录并尝试读取描述，缺失也显示 load_error。不要另建一个无描述的并行模块目录。沿用 fea，自持 module.json，不改中央表。 |
| 操作与 schema | `registry.py:37–78` 校验 ID、接口 1.0、实现状态、模块内入口及操作 schema。not_integrated 必须空操作、空适配器。本轮保持原 manifest。专业 JSON Schema 仅支持 `docs/protocol.md` 第 5 节列出的受限子集，不能用 $ref/oneOf/if/default 注入。 |
| 输入与预检 | `T/mlcc/runtime.py:52–88` 先专业 schema、依赖，再 action=preflight；上限 min(10 秒, 操作超时)，task_id/artifact_dir=null。科学 Adapter 做确定性有限数、几何关系、单位/模型范围和环境支持检查，不造任务、不组装求解。 |
| 执行 | `T/mlcc/transport.py:15–48` 启动 `[module.python,-u,adapter绝对路径]`，cwd=模块目录；stdin 一个 JSON、stdout 一个 JSON（≤2 MiB），stderr 诊断。绑定只有绝对 Python 路径；不得把 WSL/Conda 命令塞入科学 payload。 |
| 排队 | `runtime.py:90–114,139–204` 创建公共 task；queued 由显式 worker 执行一次，核对 manifest/schema/python 快照。无后台自动 worker、无原生细进度、无自动重试。Adapter 在一次调用内等真实求解及采集完成，不能只返回旧系统 job ID。 |
| 结果 | `schemas/adapter-result.schema.json`：execution_status 与 quality 分离；provenance 含方法/后端真实版本、单位、工况、适用性及来源；results 通过专业输出 schema。旧 COMPLETED/VERIFIED 不能直接翻译为科学 passed。 |
| 产物 | `runtime.py:116–137` 和公共协议要求写给定 artifact_dir，声明 `artifacts/...` 相对引用；大数组/网格留文件。公共层保存 record、原始响应/诊断并检查路径/大小；模块可另存文件 hash 清单，但不重建公共 task/store。 |
| 验收 | `runtime.py:18–30` 缺报 required check 补 not_checked。公共 check、echo、自检或 exit=0 都不授予科学合格；真实运行、数值验证、物理适用性须分别记录。查询 status/result/artifact 只读，不触发求解。 |

当前可用公共入口是 CLI/Python Runtime，并无已连接 LLM 或 Web。`framework_selfcheck/adapter.py:1–67` 仅回显与质量传播，`templates/module/adapter.py` 是拒绝 stub；都不能作为器件求解实现复制。本轮 Windows `python -B -m mlcc check` 得到 valid=true/module_count=8，describe fea 仍 not_integrated。这只是框架结构检查。

**具体文档/代码差异或缺口**：来源 README 的旧根路径；来源 pyproject/`__init__.py` 为 2.1.0.dev0 而 docs 存在 V2.4 报告（阶段名称不等于安装版本）；目标发现规则与实际目录扫描细节不同；Windows-host binding 无 WSL launcher/path mapping（见 INTERFACE_PROPOSAL）；旧独立 qualification baseline 文件在本快照缺失。未擅自补公共设计。

## 3. 来源的真实执行链

```text
自然语言 Web
  web/service、router、qwen_provider._prompt/interpret
  -> 受限 InterpretationResult/CaseSpecPatch
  -> UserMode/CAEAgentService：单位归一、合并、完整性、能力/修订/授权
  -> ExecutionIR -> FEniCSxBackend -> LocalProcessRuntime -> runner.execute
  -> SimulationWorkflow.execute -> GmshBackend -> MLCC2DBuilder
  -> MeshContext -> ElectrostaticsSkill.solve -> validate_result
  -> 原生 metrics/VTU/验证记录 -> PyVista/Matplotlib 图片 -> 完整源码导出
  -> artifact_manifest/InteractionResult -> 前端结果卡/只读查询
```

可绕过前端/provider 的真实开发入口是 `CaseSpec.from_yaml(S/examples/mlcc_2d.yaml)`，然后 `CAEAgentService.run_case` 或更窄的 GmshBackend+ElectrostaticsSkill。证据：`S/tests/integration/test_v2_mlcc_agent.py:15–45`、`S/src/fem_agent/service.py:412–508`、`S/src/fem_agent/backends/fenicsx.py:9–37`、`S/src/fem_agent/execution_runtime.py:48–150`、`S/src/fem_agent/runner.py:17–85`、`S/src/fem_agent/core/workflow.py:49–74,161–206`。

**计算可以独立于 Web 和 LLM 运行，但当前包内部依赖较宽。** `core/registry.py:67–97` 初始化时注册所有 PDE；geometry registry 也加载多种模型；静电 Skill 导入 CaseSpec、Artifact、RegionManifest、MeshContext、GEOMETRIES。应抽取窄 DTO/几何/求解器边界，而非把 service、runtime、全 registry 和整个 fem_agent 包带入 MLCC。

## 4. 二维电场：实际模型与输出

### 几何和假设

`S/src/fem_agent/geometry/mlcc.py:11–46,58–85`要求九个几何参数；长度为正有限 SI 值，active_gap_count 为 1–79 整数。`left_margin + overlap + right_margin = body_length`，检查使用 rel_tol=1e-9/abs_tol=1e-15。**这些是来源工程限制/几何容差，不是已批准的目标科学阈值。**

- 电极数 N=active_gap_count+1；总高 `bottom_cover+top_cover+N*electrode_thickness+(N-1)*dielectric_gap`。
- OCC 生成陶瓷矩形，交替 A/B 电极矩形：A 从 x=0 到 L-right_margin，B 从 left_margin 到 L。电极矩形从陶瓷扣除；**没有金属实体单元**。
- 电极槽暴露边界作为 ELECTRODE_A/B，单一 CERAMIC 域；顶部/底部 cover、侧边 margin 都是同一种陶瓷的几何部分，未赋独立材料。端子是两组等势边界，未建端头金属、引线、外部空气或接触电阻。
- `mlcc.py:88–131` 按线段端点识别语义，拒绝空组、重叠、未知边界。曲线必须直线双端点；不支持随意曲边电极或圆角尖端。
- 横截面二维不随出平面方向变化。明确深度 t 仅将面积/线积分转换为总量；不是轴对称模型，也不是力学 plane_stress/plane_strain。无有限宽三维边缘修正。

### 方程、材料、边界、求解

`S/src/fem_agent/skills/electrostatics/skill.py:35–91,122–185`：线性、各向同性、无损、无体自由电荷的静电问题；一个 entire_domain 介质、常数 εr>0、ε=ε0εr。

```text
∫Ω ε ∇φ·∇v dA = 0     E=-∇φ, D=εE
φ|A=VA, φ|B=VB         未施加电势的外边界为自然零 D·n
```

要求两个不同电势；零压差被拒绝，不能声称该 Skill 支持零偏压电容提取。显式 insulation 只接受零值；外绝缘可采用自然边界，但语义边界标签仍需完整。非线性 ε、各向异性、损耗、AC、漏电、击穿、瞬态和三维均拒绝。ε0 在代码内固定为 8.8541878128e-12 F/m，应记录方法版本并与负责人确认常数来源。

有限元使用 Lagrange(spec.physics.element_degree)，PETSc 固定 preonly+LU、error_if_not_converged；reason≤0 报错。**静电路径没有使用通用 PETScSolverService，也未应用 spec.solver 的用户选择**（skill.py:141–163）；迁入时不要宣称用户给定求解器/容差已生效。首版建议仅开放已复核的一阶、串行配置；并行/高阶导出适用性 not_checked。

### 量纲、总量与质量

| 量 | 当前代码 | 迁移要求 |
| --- | --- | --- |
| 电荷 | `Q_i=-t∫Γi D·n ds`，n 为陶瓷外法向，skill.py:170–171 | signed terminal charge_C 是乘深度后的总量；另明确 Q'=Q/t，单位 C/m。 |
| 储能 | `U=t/2∫Ω E·D dA`，:172 | energy_J 是总 J；U' 为 J/m。不能再乘器件层数，几何已含所有间隙。 |
| 电容 | `C_U=2U/ΔV²` 主输出；`C_Q=|Q_first|/|ΔV|` 原始边界通量诊断，:173–182 | 总 F / 单位深度 F/m 显式分开。输入边界排序不应改变主值；A/B固定身份。 |
| 场 | potential 节点数据；E、|E| 为 DG0 单元数据，:187–199 | VTU 三分量显示补零不是三维求解；标明关联、坐标和单元顺序。 |
| 平衡 | `abs(QA+QB)/max(abs(QA),abs(QB),1e-30)` | 来源只检查两端，不保存生产路径的外绝缘位移通量；应补报告外通量及守恒残差，不能把 raw flux 当精确反力。 |
| 已有 QC | PETSc reason>0、边界 audit、两端电荷不平衡≤1%、正能量、有限正 C，:203–220 | 来源 1% 是历史代码策略，目标未经确认不继承为科学验收线；单次没有网格收敛、独立物理参考或残差范数。 |

生产 Skill 的 `validate_result` 明确 reference_available=false，所有内置检查过也返回 SOLVED_UNVERIFIED（`S/src/fem_agent/core/results.py:90–120`）。没有把参数落在旧 qualification 范围内当成本次收敛：不过 `featured/mlcc_qualification.py:14–79` 使用固定材料/BC ID、旧相对路径和基线范围，不能直接迁其资格标签。

尖角 |E|max 对网格敏感。来源报告 `S/docs/mlcc_electrostatics_qualification.md:189–209,221–230` 已明确不能作击穿安全判断；迁入保留此方法边界。

### 独立实验与已验证程度

`S/experiments/mlcc_electrostatics/spike.py:93–137,229–308,350–394` 有平行板/双介质串联板、DG0分区ε、双电容与外绝缘通量；`run_qualification.py` 有多参数趋势及大量导出，`physical_validation_2d.py:47–161` 有端子交换、镜像、外边距敏感性。这些是独立研究入口，不是生产 Agent 已支持分区介电材料、缺陷编辑或3D的证据。适合抽取基准方法，不能整段执行默认 sweep，也不能将其历史自定阈值直接移入目标。

旧 `experiments/.../results/qualification/baseline/metrics.json` 在当前来源不存在；`test_v2_mlcc_agent.py:34` 依赖它，故其 oracle 比较本轮 not_checked，不能拿文档中的 27 个 PASS 替代原生产物。3D/有限宽脚本存在但不在本轮二维范围，未执行。

## 5. 基础多物理：有界的导电到传热

**实际完整链是稳态欧姆导电→Joule体热源→稳态传热，单向顺序、同一网格。** 不是把多个独立求解器简单摆在一起；有源字段声明、文件 hash、mesh fingerprint、cell关联/单位验证和真实热方程消费路径。

- `S/src/fem_agent/coupling/electrothermal_profile.py:16–61` 明确 source=steady_electrical_conduction / consumer=steady_heat_conduction / ONE_WAY_SEQUENTIAL / EXACT_SHARED_MESH。要求2D稳态、一阶、相同几何/mesh设置和深度、无额外未限定体源、存在电势和温度Dirichlet。TWO_WAY_STAGGERED、MONOLITHIC 只是枚举，明确拒绝。
- 电传导 `∇·J=0, E=-∇V, J=σE`；热传导 `-∇·(k∇T)=q`。导电支持区域常量σ，热模型有区域常量k，参考包括 rectangle 与 layered_rectangle。具体 MLCC陶瓷/金属导电域构建和参数来源尚未因此获得验证。
- `S/src/fem_agent/coupling/joule.py:22–120` 从完成的 Stage A 索引读取电场和电流密度；核对运行/修订、文件 hash、声明、MSH/VTU网格、cell双分量及有限性，计算 q=J·E [W/m³]，保存 transform版本、来源/结果hash及 ∫q dA [W/m]。现函数本身只拒绝非有限q；非负/物理耗散需模型验证及测试，不能误称已逐单元硬门控。
- `S/src/fem_agent/core/workflow.py:114–160` / `S/src/fem_agent/skills/heat/skill.py:109–138` 验证来源、按canonical cell key匹配到实际求解网格并装入DG0右端。不是插值；`mesh/canonical.py` 的坐标量化约定应重新核验微米尺寸。禁止不同网格静默传递。
- `S/src/fem_agent/coupling/operation.py` 的执行器保留 A/transfer/B 失败位置与审批证据；计划/审批/会话store与旧系统紧耦合，不应整体进入新公共任务系统。
- 没有时间步/时间重采样：两阶段均稳态；没有温度反馈σ、迭代收敛、整体耦合，也没有热应变/压电/声学自动链。`S/src/fem_agent/coupling/models.py:8–59` 和 `tests/unit/test_coupling_models.py` 中 thermal→mechanical 只是计划合同示例；`skills/elasticity/skill.py:35–65` 无温度字段接收接口，不能据此声称热力耦合可运行。

**量纲需要在计算结果层统一**：导电路径 `electrical/skill.py:179–186` 已将边界电流乘t；Joule的 integrated_power_per_m_depth 和 `heat/skill.py:189–197,230–233` 热率保留二维积分。旧 `web/task_query.py:163–176` 才给 Joule/热率乘t后比较总W。迁移不能只拷贝 heat metrics 并标成 W，也不能在查询端再次给已转换结果乘t。旧参考t=1m会掩盖漏乘/重复乘问题，应增加非1m厚度验证。

**重复计入风险**：heat Skill会将 CaseSpec常数源与 runtime_field 相加（:107–135）；profile门控当前禁止额外source_terms。抽取后必须保留互斥规则。无损静电E不能凭空产Joule热；需要真实σ/J，交流介电损耗还需频率、ε损耗/损耗角、幅值约定及独立模型，当前链未覆盖。全堆叠几何不得再乘层数；ε有效响应与显式微结构的双重计入也应在材料来源审查中防止。

`S/tests/integration/test_v22_c3_electrothermal.py:38–122,155–240` 包含真实解析场/抛物温度、零电压、三网格、分层σ和能量/网格身份检查；后半有transfer/consumer失败测试。`docs/architecture/v22_c3_electrical_joule_heat.md` 提供历史实测，但本轮只执行2项计划合同测试，**耦合真实求解复跑、数值验证、器件物理适用性均 not_checked**。建议可选扩展，不承诺自动成为 MLCC 首版计算。

## 6. 必要 CAE 与 CAD 的取舍依据

| 能力 | 实际实现与状态 | 首版关系 |
| --- | --- | --- |
| 参数/单位 | `units/system.py:18–85` 及归一化代码；CaseSpec/Pydantic+各Skill确定校验。没有必要迁整套语言证据/稀疏patch系统。 | 显式SI输入、有限数、长度正值、整数、几何闭合/深度/压差规则保留；缺字段直接结构化拒绝。 |
| 区域/材料/BC | `geometry/mlcc.py` 构造标签；`geometry/regions.py:16–53` 检查外面覆盖/空组/重叠/内部错标；MeshContext:26–95 从真实网格拿tag/DOF。 | 必迁，规则进入代码和测试；数字tag只作产物标签，语义名决定物理含义。 |
| 网格 | `mesh/gmsh_backend.py:21–67,215–241` Python API/OCC；设置全局target_size；非空/物理组/拓扑报告和hash。CLI fallback :69–95 只支持rectangle/box，不能作为MLCC fallback。 | 抽取MLCC路径；未发现生产MLCC局部自适应细化。质量报告明确 not_yet_computed，不能说已查Jacobian/长宽比/最小角。几何尺寸与局部单元分辨率需新检查。 |
| 求解/失败 | 静电Skill固定LU与reason；旧runner捕获错误、保存日志/环境；其他物理有PETScSolverService。 | 提取专业异常/原生reason、补实际选项/耗时/残差依据；公共状态由MLCC runtime维护，不搬旧runner和status体系。 |
| 后处理/场图 | 静电 `metrics.json/fields.vtu`；`visualization/pyvista_backend.py:9–32,133–161` 有薄器件夸张纵轴细节与原比例图；独立实验有CSV/趋势图。 | VTU和JSON核心；图片薄适配、比例说明保留。生产静电未实现通用任意曲线探针接口，首版不宣称已有。批量曲线/参数扫研究暂缓。 |
| 格式 | 通用 `export/fields.py,coordinator.py` 有多格式；静电Skill直接写VTU，不走该协调器。 | 首版声明真实实现的VTU/JSON及必要PNG；不因为CaseSpec支持xdmf/npz就宣称静电已导出。 |
| 记录/复现 | `core/workspace.py`、runner保存输入/环境/manifest，portable_code.py:15–75 复制完整fem_agent源码并zip。 | 方法/输入/后端版本/hash/日志方法保留；不迁其完整包导出、历史运行库和第二套任务ID/store。 |
| 验证算例 | 平行板、串联介质、MLCC基线、趋势、耦合矩形/分层参考实际有代码。 | 优先重建小基准并保存新原生证据；双介质基准不能扩成首版分区材料产品承诺。 |
| MLCC CAD | 参数化矩形/槽、电极阵列、cut、边界语义、非空几何检查、mesh接口均实际存在。 | 此子集足以闭环；cover/margin非独立分区，若将来需多材料则单独设计。 |
| 通用CAD布尔 | `geometry/boolean.py:6–23` 薄封装fragment/cut/fuse/intersect；通用builders有分层/孔等。 | 只用当前MLCC需要的OCC cut，不引入完整通用几何注册体系。 |
| CAD导入 | `geometry/cad/worker.py:17–46,49–77` STEP/OCC、单个3D体、尺度/拓扑/单位事实；models.py:42–86 明确dimension=3且solver_ready=false。group/mesh审批另有hash绑定。 | 它不是可直接复用的二维任意CAD入口。首版不需要文件导入；网格MSH/场VTU导出即可。2D DXF/STEP截面提取/标签稳定性另议。 |
| CAD界面 | web/cad_setup、cad_upload、static/cad.js、geometry selection/preview workers依赖旧会话和审批。 | 不迁交互式CAD编辑界面，也不默认建设3D建模器。 |

## 7. Skill、prompt 与交互

这里的生产 **Skill主要是Python确定性PDE类**（`core/registry.py`），不是天然会被MLCC宿主加载的SKILL.md。`S/docs/skills/` 是方法文档，`docs/codex_context/cae_agent/` 是旧开发上下文；未发现当前src有可直接启用的独立MLCC SKILL.md包。实际LLM提示在 `web/qwen_provider.py:233–245,300–451`，另有开发用Codex provider（web/provider.py:1–5）。来源AGENT/prompt文档不能取代代码执行证据。

| 规则/体验 | 判断与目标归属 |
| --- | --- |
| 未知值不猜、层数歧义澄清、标明理想电极/ε适用性、不作击穿推论 | 保留为短方法Skill及结果限制；必填/参数关系也必须进schema+preflight，不能只写prompt。 |
| 明确材料来源、单位、面外深度；自然绝缘无需反复向用户补零 | 专业schema和确定性Adapter。交互只解释缺项，不决定方程或数值验收。 |
| Qwen只生成受限patch、不授权执行、不转换单位/不重写真实数值 | 原原则值得保留；provider/密钥/CaseState权限实现不迁入科学模块。MLCC当前没有LLM宿主，不为此安装provider。 |
| 运行授权绑定当前修订、结果绑定本次模型/产物 | 语义保留；以公共task输入快照/显式run/worker落实。旧session/revision/approval系统不照搬。修改输入应新任务，读取结果不再求解。 |
| 状态卡/错误/结果解释 | 重写为公共execution与quality分开展示；读登记产物事实，缺证据就not_checked。不给queued虚构后端进度；先显示字段级错误再提出下一步。 |
| 超时/失败 | 保留首错、结构化错误和原生日志；来源不同语义provider隔离/重试策略不应成为科学运行自动重试。公共interrupted后人工核对外部进程。 |
| 默认值 | `featured/defaults.py:10–29` 依赖相对 examples 和精确基线请求词；不照搬自动补材料/工况。下一版可以显式选择有版本的示例，但必须显示全部采用值；科学参数不可静默补齐。 |
| 文本大prompt | 已包含MLCC、电热、超弹、加载、材料身份、来源证据等多域规则；不要合并成更长prompt。可复用规则分流到schema、代码、测试、短Skill。旧前端/工具词和绝对路径全部移除。 |

**本轮复现的确定性交互缺陷**：`featured/boundary_requirements.py:16–26` 生成按region命名的required路径；`interpretation/policy.py:129–139` 却先按BC.id查找。同一基线 terminal_a/b 与 ELECTRODE_A/B 不同；本轮 `boundary_identity_probe.json` 中 required_boundary_missing=[]，但两条 completeness_path_present=false。无LLM参与、无源文件修改。故不能将“补prompt让用户再给电压”作为修复方向。

10月20日保留的 `workspace/mlcc_acceptance_20261020/backend_tests.xml` 与 capability_report.md:31–70 记录74项中46通过/28失败、正常前端被阻断；本轮未重跑这些交互测试，历史失败不是本轮新测计数。9月旧freeze报告也有自然绝缘重复澄清；不把后来其他能力报告的成功覆盖到本MLCC流程。

## 8. 环境、许可证与隔离

本轮读取WSL清单并核对真实元数据：Ubuntu-24.04 / WSL2；用户zhaoxiang；已有 `/home/zhaoxiang/miniconda3/envs/fenicsx-env/bin/python`。Python3.11.15，DOLFINx0.11.0、UFL2026.1.0、petsc4py3.25.5、mpi4py4.1.2、Gmsh4.15.2、PyVista0.48.4、NumPy2.4.6、Pydantic2.12.5、pytest9.1.1。记录见 `review_work/environment.json`；是FEniCSx/DOLFINx，**不是传统dolfin**。未换环境、未安装/升级依赖。

来源开发launcher `scripts/activate_dev.sh:11–112` 激活fenicsx-env、注入来源src、强制创建来源workspace，并输出启动文字；Web脚本还创建sqlite/runtime目录、启动Flask/Codex。已读后未执行这些脚本，改用已核实解释器、-B、仅本模块cache/output。本轮来源路径仅为**审阅探针的只读导入**，不能作为正式Adapter依赖或运行时sys.path方案。

直接计算需要dolfinx/UFL/PETSc/MPI/Gmsh及数值/格式库；当前源码DTO还依赖Pydantic/PyYAML，渲染用PyVista/Matplotlib。公共包保持标准库；下一轮从真实运行依赖锁定精确环境，pyproject的范围声明不是锁文件。当前WSL元数据和小算例已验证，但安装重建可重复性、MPI多进程、其他机器部署均not_checked。

来源根未发现通用LICENSE；pyproject无明确项目license声明，需用户/代码所有者确认复制/发布权及来源归属。捆绑 `src/fem_agent/web/static/vendor/vtk/LICENSE` 有第三方声明但不需要迁；Conda科学依赖各自许可证/分发条款应在打包前核对，当前第三方分发合规not_checked，不能由可导入推导可随包分发。

`S/env.txt` 含明文provider凭据（本报告不记录值）；所有env/私有配置/历史会话/SQLite/客户数据、workspace及release备份均禁止整包复制。来源维护者应单独处理已暴露凭据的轮换。审阅证据只选科学输入/求解产物/代码hash，不收录该文件内容。

未来COMSOL隔离建议：专业输入是几何/材料/边界/工况和量纲；科学后端内部实现几何、求解、字段读出；公用层负责WSL/进程/路径/task/artifact。不要在schema要求UFL表达式、Gmsh tag号、PETSc选项、Conda路径。两后端需要分别验证电极简化、厚度、符号、能量、边界标签、网格/求解与参考值，不能宣称无验证互换。本轮不实现COMSOL。

## 9. 本轮证据清单与未覆盖项

| 等级 | 本轮结果 | 原始位置 |
| --- | --- | --- |
| 静态代码审阅 | 已覆盖上表所指执行链；不是全仓库每个求解器审计 | 本文路径/行号及source hash快照 |
| 环境检查 | 实际WSL解释器/发行包版本已读，未安装 | review_work/environment.json |
| 确定性合同/标签测试 | 11 passed，约11.14s；2几何、7静电spec、2耦合计划测试；未调用LLM。1个pytest marker警告来自使用空配置，不是失败 | review_work/targeted_tests.xml、targeted_tests.stdout.log |
| 真实求解 | 一个原样六间隙MLCC基线，直接GmshBackend→ElectrostaticsSkill；约19.15s（含导入/JIT/导出/记录） | review_work/run_probe.py、baseline/mesh、baseline/results、probe.stdout.log / stderr.log |
| 单次数值检查 | reason=4；7392 cells/5354 DOFs；U=6.446561125083366e-7 J；C_U=1.2893122250166733e-8 F；QA=1.284511198879037e-7 C，QB=-1.2848189410149258e-7 C；相对电荷不平衡=0.0002395218；C_Q/C_U相对差=0.003723711。场有限，A/B/绝缘覆盖3314/3314，重叠/未知/内部错标0 | probe_summary.json；baseline/evidence/electrostatics_verification.json |
| 数值验证 | 本轮解析对照、网格收敛、厚度/电压/ε趋势重跑均not_checked；上述原生状态SOLVED_UNVERIFIED，未提升为科学合格 | probe_summary.json的not_checked字段 |
| 物理适用性 | 实物材料、温度/频率/偏压依赖、真实器件对照not_checked | 本文限制与V1_PLAN开放项 |
| 公共接入 | Windows及WSL公共结构check均通过；fea保持not_integrated。正式Adapter/public run尚不存在，not_checked | 本轮CLI输出；review_work/wsl_framework_check.json；module.json未改 |
| 历史原生证据复核 | 实读10月20日baseline metrics/verification、四算例汇总及VTU存在；基线与本轮数值一致。两级细化只是稳定性烟测 | S/workspace/mlcc_acceptance_20261020/backend_runs/baseline/results/metrics.json:1–45、backend_numerics.json:1–235 |
| 基础电热 | 静态完整链、历史报告/现有真实测试代码存在；本轮真实耦合复跑not_checked，不能登记首版已实现 | 第5节 |

本轮未运行全量回归/27例参数扫/远程任务/三维求解/旧Web；未修改来源或reference。公共unittest脚本 `T/tests/test_framework.py:25–48` 固定向公共tmp/framework-tests写入；为遵守本thread仅写本模块的边界，本轮没有直接运行该命令，也未改其临时目录逻辑，交main在集成时执行。交付文档不是科学模块完成记录。
