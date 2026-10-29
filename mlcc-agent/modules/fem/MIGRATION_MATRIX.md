# 二维器件模块迁移矩阵（方案，未实施）

历史方案快照：已完成的基础静电抽取与真实Windows接入见README、SOURCES.json和ACCEPTANCE。此表保留原取舍依据，不作为当前实现状态表。

来源根 `S=D:/Zhaoxiang/code/fem-general-main`；表中 Python 简写 `src/…` 指 `src/fem_agent/…`。目标均相对于 `modules/fem/`，**目标位置是下一轮建议，不代表文件已实现**。真实状态分清“本轮运行”“历史原生结果”“静态存在”“仅合同”。复用方式只使用用户指定的六类。

| 来源能力 | 代码位置 | 真实状态 | 依赖 | 复用方式 | 建议目标位置 | 适配工作 | 风险 | 验证方法 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| MLCC参数关系/阵列/布尔几何 | src/geometry/mlcc.py:25–85 | 本轮原样基线+几何标签测试真实运行 | Gmsh OCC；原DTO/contract | 抽取重构 | geometry/mlcc.py、model.py | 改为模块自有不可变输入；保留几何公式和A/B交替；剥离旧registry | cover/margin同材；1–79是工程界限；尖角 | 单间隙/奇偶电极数、几何闭合、非空域、基线面积/高度对照 |
| MLCC边界语义识别 | src/geometry/mlcc.py:88–131 | 本轮3314/3314 facet审计通过 | Gmsh | 薄适配 | geometry/mlcc.py | 语义名称保持；tag值不进入科学输入；输出真实tag映射 | 端点容差/直线假设，不适合曲边 | 空组/未知曲线/A-B重叠/边界覆盖失败案例 |
| 原几何参数中文别名合同 | src/geometry/mlcc.py:11–22,49–52 | 静态存在、旧语义测试部分历史失败 | GeometryParameterContract | 抽取重构 | skills/linear-electrostatics/SKILL.md | 只保留层数歧义/术语说明；结构输入用明确active_gap_count | 不应按文本猜层数或补工况 | 字段说明人工审阅；确定预检拒绝歧义输入 |
| Gmsh生成MLCC网格 | src/mesh/gmsh_backend.py:21–67 | 本轮真实7392 cells | Gmsh；旧Artifact/GEOMETRIES | 抽取重构 | mesh/gmsh_2d.py | 固定MLCC builder；产物目录注入；Gmsh输出进日志；保证finally finalize | 全局尺寸不等于局部充分分辨 | 网格非空、尺寸记录、区域/边界真实检查、基线MSH |
| Gmsh CLI fallback | src/mesh/gmsh_backend.py:69–95 | 仅rectangle/box，MLCC明确不支持 | gmsh可执行程序 | 不迁移 | 无 | 缺Python API直接preflight拒绝 | 静默fallback错误模型 | 依赖缺失拒绝用例 |
| 通用网格报告 | src/mesh/gmsh_backend.py:215–241 | 非空/组检查已运行；quality=not_yet_computed | Gmsh、hash | 抽取重构 | quality/mesh.py | 保留拓扑与hash；补必要几何退化/单元质量记录；未做项not_checked | 不得把valid当形状质量/收敛通过 | 零单元/错维/空tag/退化单元；阈值待确认 |
| MSH→DOLFINx及边界DOF | src/mesh/context.py:26–95 | 本轮真实导入求解 | dolfinx.io.gmsh、MPI、Gmsh | 抽取重构 | backends/fenicsx/mesh.py | 去掉3D imported CAD审批分支及旧registry；保留实际tag/dim/DOF检查 | 原代码含Web线程兼容和别名；MPI导出未验 | 串行基线、非空DOF、标签错维/丢失失败 |
| 外边界集合审计算法 | src/geometry/regions.py:16–53 | 本轮真实+确定性计算 | 标准库dataclass/集合 | 直接复用 | quality/regions.py | 保留来源归属；接口用纯dict/集合，不复制渲染部分 | cell域完整性仍需另查 | 缺覆盖、重复、内部错标、空组的单元测试 |
| 线性静电弱式/电荷能量积分 | src/skills/electrostatics/skill.py:122–185 | 本轮真实基线，SOLVED_UNVERIFIED | DOLFINx0.11/UFL/PETSc/MPI | 抽取重构 | backends/fenicsx/electrostatics.py | 拆掉CaseSpec/Skill/Artifact；明确串行P1固定LU；输出总量及每米量 | 一介质、无外空气、零压差拒绝、raw flux偏差 | 平行板解析+MLCC基线+电压/ε/t缩放+守恒 |
| 静电输入验证 | src/skills/electrostatics/skill.py:35–91 | 本轮7项spec测试通过 | 旧CaseSpec/Pydantic | 重写 | validation.py、schemas/draft/*.json | 直接针对窄专业输入；拒绝extra/非有限/不支持机制；禁止隐式单位 | 旧id/region身份混淆；有些通用字段实际无效 | 正常/缺项/负值/bool/零压差/未知字段/不支持物理 |
| 固定静电PETSc配置 | src/skills/electrostatics/skill.py:157–163 | reason4，本轮已运行 | PETSc LU | 薄适配 | backends/fenicsx/electrostatics.py | 显式记录真实选项、版本、耗时；不暴露被忽略的solver输入 | 通用solver字段在此不生效 | 原生reason/选项一致；失败原因结构化 |
| 静电QC阈值与资格标签 | src/skills/electrostatics/skill.py:203–220；featured/mlcc_qualification.py | 内置检查本轮过，非独立验证；旧范围标签 | 旧VerificationResult/基线目录 | 重写 | quality/electrostatics.py、harness/ | 按公共numerical/scientific与not_checked；1%等仅记历史来源，由负责人确认 | 把历史参数范围或passed bool当本次科学验收 | 漏检查补not_checked、QC failed不伪造执行异常、负责人批准profile |
| 单位换算/参数有限性 | src/units/system.py；geometry/mlcc.py | 原代码存在；本轮spec归一化测试通过 | 旧schema/丰富语义 | 抽取重构 | validation.py、units.py（如需要） | 首版优先SI专用schema；只抽所需确定性关系，不拷贝全字段注册 | 混合单位、重复换算、LLM转换 | m/mm/um仅在显式支持时测试；首版非SI拒绝 |
| VTU场与JSON指标 | src/skills/electrostatics/skill.py:176–201 | 本轮真实生成 | PyVista、NumPy、DOLFINx plot | 薄适配 | postprocess/fields.py、metrics.py | 明确point/cell、x/y及补零z；文件名相对artifact_dir；导出请求按实际支持 | 3分量显示被误认为3D；高阶/MPI顺序 | VTU重新读取、有限性、网格单元顺序与数组shape |
| 薄器件场图/语义标签图 | src/visualization/pyvista_backend.py:9–32,133–161；geometry/regions.py:56起 | 旧原生图片存在；本轮仅生成标签图 | PyVista/Matplotlib/offscreen | 薄适配 | postprocess/render.py | 原比例与放大图分开标注，单位/色标；图片失败不掩盖已完成求解 | 视觉变形、色标/极值误导 | 重新读VTU渲染、人工看全图/标注；不可代数值验证 |
| 通用多格式OutputCoordinator | src/export/coordinator.py、fields.py | 其他物理使用；静电当前未使用 | meshio/PyVista等 | 暂缓 | 后续postprocess/ | 首版只承诺VTU/JSON；有需求再适配单一格式 | 迁入大量不必要格式依赖 | 各格式数据/单位/标签往返，不以存在文件代通过 |
| 平行板/双介质基准方法 | experiments/mlcc_electrostatics/spike.py:93–137,229–308,350–371 | 可执行代码存在；旧oracle产物缺失，本轮未跑 | Gmsh/DOLFINx/NumPy/PyVista | 抽取重构 | harness/benchmarks.py | 小规模、明确输出目录；独立解析C；阈值需确认；不复制默认多例入口 | 独立实现与产品实现应有可比桥接，防同源自证 | 用目标求解内核跑同模型与解析比较，原生证据保存 |
| MLCC 27例参数扫/镜像/缺陷研究 | run_qualification.py、physical_validation_2d.py | 静态与历史报告；本轮not_checked | 额外Matplotlib/CSV等 | 暂缓 | 后续harness/研究 | 抽取电压/ε/t少量必要不变量；全扫不默认运行 | 固定来源路径/默认写来源；新缺陷几何未经产品验收 | 授权后逐项小例，网格/材料证据分开 |
| 独立三维/有限宽研究 | experiments/mlcc_electrostatics/*3d.py、refine_finite_width.py | 有研究代码；非当前产品能力 | 3D FEniCSx/Gmsh | 不迁移 | 无 | 仅保留物理边界说明 | 越出二维首版及资源范围 | 本轮not_checked |
| 欧姆导电与稳态热叶求解器 | src/skills/electrical/skill.py、heat/skill.py | 有真实测试与历史报告；本轮真实复跑not_checked | constitutive、region、PETSc、field exports | 暂缓 | 可选backends/fenicsx/conduction.py、heat.py | 用户选择扩展后抽取；显式σ/k/热BC；二维积分量单位统一 | 并非MLCC漏电/交流损耗模型；与无损静电混淆 | 参考矩形/分层导体解析、非1m厚度、物理负责人确认 |
| q=J·E转换与来源绑定方法 | src/coupling/joule.py:22–120 | 完整代码；现有真实测试，本轮未重跑 | NumPy/PyVista、旧run manifest和hash | 暂缓 | 可选coupling/joule.py | 抽取纯字段变换+真实网格身份；结果层直接区分W/m和W | E无J不能发热；负耗散/重复热源；坐标量化 | shape/unit/hash篡改、same_mesh、非负耗散、∫q与UI对比 |
| 同网格字段协议/校验 | src/field_contracts.py、field_validation.py、mesh/canonical.py、runtime_input.py | 明确字段/单位/关联、网格/字节检查；本轮静态 | Pydantic、VTU/MSH转换 | 暂缓 | 可选coupling/contracts.py、quality/transfer.py | 保留必要科学传递校验，减少session/task引用 | 坐标13位量化对微米模型适用性需重验；不得静默插值 | 改网格/标签/坐标/字段字节拒绝；重排同网格正确 |
| 两阶段执行器与审批存储 | src/coupling/operation.py、plan_authority.py、case_agent.py | 历史完整运行链，耦合计划2项本轮通过 | 旧session/revision/approval/run store | 不迁移 | 无 | 若扩展，用单个公共task内科学阶段组织，不另建公共工作流系统 | 重复提交/两套权限/两份状态权威 | 公共单次执行/失败保留A产物；阶段日志不另建任务服务 |
| 热→力计划示例 | src/coupling/models.py；tests/unit/test_coupling_models.py | 仅合同示例，无温度→弹性接收链证据 | 旧CouplingPlan | 不迁移 | 无 | 文档明确不承诺电热力 | 将合同测试冒充真实多物理能力 | not_checked；独立立项后再定义物理 |
| 通用OCC布尔包装 | src/geometry/boolean.py:6–23 | 简单真实API封装；本轮未单测 | Gmsh OCC | 不迁移 | 无 | MLCC所需cut已在builder内 | 没必要为四个转发函数带入通用CAD包 | builder布尔结果直接验证 |
| STEP预处理/3D实体/分组/网格审批 | src/geometry/cad/*、mesh/imported_cad.py、cad_contract.py | 代码完整但只准入单个3D体；不是2D MLCC模型器 | OCC/meshio/旧store | 不迁移 | 无 | 保留来源hash/标签不可猜的原则，不引入导入链 | 维度不符、源单位未知、标签漂移、审批复杂 | 本轮not_checked；未来2D导入单独需求 |
| CAD编辑/选择/UI | src/web/static/cad.js、cad_setup.py、geometry_selection.py | 旧Web绑定；不属科学最小环 | Flask、WebTaskManager、viewer | 不迁移 | 无 | 首版用参数化输入+静态标签/场图 | 首版被拖成通用CAD编辑器 | 无需迁移验证 |
| 输入快照/环境/hash方法 | src/core/workspace.py、runner.py | 旧产物和本轮hash/原生结果存在 | 标准库 | 薄适配 | evidence.py | 只保留科学版本/输入/网格/产物hash；公共record由runtime写 | 不要泄漏来源路径、凭据或历史输入 | 同任务输入与结果对应、文件hash、必要源归属 |
| 旧公共运行/任务/状态系统 | service.py、execution_runtime.py、runner.py、web/tasks.py、sessions/* | 功能存在，当前MLCC准入有回归 | 旧业务、Pydantic/Web/权限 | 不迁移 | 使用T/mlcc | Adapter转换契约，科学进程由公共层管理 | 第二套队列、状态/授权漂移、重复执行 | main公共协议回归；模块stdout单JSON/失败产物 |
| 整包源码zip导出 | src/export/portable_code.py:15–75 | 每次workflow复制整个包 | 旧包结构/资源 | 不迁移 | 无 | 改为模块版本+必要方法来源/hash/最小输入，发布源码Bundle由main冻结 | 无必要Web/provider/vendor与许可证进入每次产物 | 检查产物清单不含旧包/密钥/数据 |
| 方法纪律/范围解释 | docs/skills/*、静电/研究脚本限制 | 文档/确定性方法实际存在 | 无需LLM | 抽取重构 | skills/linear-electrostatics/SKILL.md | 短方法说明：理想电极、深度、C主值、Emax边界、证据等级 | 文档被误当门控 | 与代码/检查ID对照审阅；缺项代码必拒绝 |
| 大prompt与参数提取 | src/web/qwen_provider.py:300–451、interpretation/* | 实际生效；含多域及旧状态 | Qwen/provider、CaseState、source evidence | 重写 | 模块Skill + 未来宿主交互说明 | 分流schema/preflight/tests；自然语言只生成待核对输入 | 提示与代码身份不一致、LLM担任准入权威 | 不依赖provider仍能全流程；缺参数字段级错误 |
| 完整性与默认baseline逻辑 | interpretation/policy.py:129–139、featured/defaults.py、mlcc_qualification.py | 本轮内存探针复现id/region矛盾；旧资格路径缺失 | 固定ID/旧examples/旧状态 | 重写 | validation.py、versioned examples/ | 窄输入、固定语义terminal_A/B、不自动补科学值 | 基线注入覆盖用户事实、旧范围假合格 | 不同BC标识不改变物理；参数来源/默认采用明确 |
| 状态/失败/结果展示原则 | web/task_query.py:163–176、result_query.py、presentation.py | 有确定性查询；Web MLCC准入历史失败 | 旧Web store/正则路由 | 抽取重构 | INTERFACE_DRAFT.md、未来宿主展示约定 | 使用公共task结果；总量在计算结果层转换；解释读取事实与not_checked | 重新乘t、读旧结果、不必要调用LLM、错误卡笼统 | 查询无副作用、结果匹配task、缺证据不编造、错误保留首错 |
| Web provider/Codex桥/密钥配置 | src/web/provider.py、qwen_provider.py、start-cae-web.*、env.txt | 旧前端工程资产，存在机器路径和凭据 | Flask/LLM/Codex/机器绑定 | 不迁移 | 无 | 明确排除所有env/private/session/SQLite；不读取密钥到报告 | 泄密、供应商/权限强耦合、启动副作用 | 迁移文件白名单与secret扫描只输出文件名/位置不输出值 |
| 本地/WSL启动与路径映射 | scripts/activate_dev.sh、start_cae_web.sh | 已核实环境；启动脚本会写来源workspace | WSL/Conda/机器路径 | 不迁移 | main管理的执行绑定 | 优先评估整个公共CLI在WSL运行；Windows桥最小需求见提案 | stdout污染、Windows路径传Linux、超时遗留子进程 | main执行适配验收，不塞入科学schema |

## 迁移文件白名单原则

下一轮仅按已确认范围抽取上述选定函数/方法与必要测试；每份复制内容记录原路径、HEAD、hash、修改说明和归属。来源项目根没有找到通用许可证，项目所有者需确认复制和对外交付权；第三方依赖优先使用现有环境，不随包复制二进制。未确认许可证/素材来源的资源不得默认进入交付。

正式实现必须可以移除/不可访问S后独立运行：模块自有包、模块内相对导入或安装到独立环境；禁止来源绝对路径引用、运行时sys.path注入及import旧fem_agent。审阅探针 `review_work/run_probe.py` 为有意读取来源的证据工具，不是正式入口、不参与发现、不进入生产发布包。
