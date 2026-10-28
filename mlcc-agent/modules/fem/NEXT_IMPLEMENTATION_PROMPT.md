# 下一轮实施 prompt（可直接复制）

**基础静电首次移植已完成；以下是历史prompt，不应再次从头执行。** 后续先读ACCEPTANCE和TODO，仅处理用户选定的剩余事项，保留Windows公共运行边界，不把后续增强自动扩大为多物理/COMSOL。

你是MLCC项目的二维器件有限元模块开发助手。目标根 `D:/Zhaoxiang/code/mlcc-main`；本模块沿用main已登记的 `modules/fem/`，不新建device_fem_2d。本轮开始**最小科学实现迁移**，不要把审阅文件或来源研究结果当成新模块已实现。

先读取根AGENTS.md、docs/architecture.md、docs/protocol.md、docs/development.md、docs/v1-scope.md，以及本模块REVIEW.md、MIGRATION_MATRIX.md、V1_PLAN.md、INTERFACE_DRAFT.md、INTERFACE_PROPOSAL.md。核对这些文件以来的公共协议与来源代码是否有变化，不覆盖已有其他thread工作。

## 范围与决策入口

执行已有对话中用户最终确认的范围；目前建议为二维均匀线性各向同性无损静电、理想A/B电极、自然外绝缘、显式深度、非零直流压差、串行P1、现有DOLFINx后端。**若用户尚未确认最终首版范围、材料来源/科学阈值或main运行路线，先提出一次聚焦澄清，同时完成不依赖答案的合同/纯函数/失败测试；不得自行补科学数值或注册能力。** 已确认事项不重复询问。

可选导电→Joule→稳态热必须得到单独范围确认才实施；不做3D、AC损耗、击穿、非线性介电、热力声、COMSOL、通用CAD编辑器或跨尺度编排。

## 可改目录和禁区

仅编辑 `modules/fem/`。公共mlcc/、schemas/、tests/、docs/、bundle.json、其他模块、reference/和来源均只读。公共缺口更新本目录INTERFACE_PROPOSAL交main，不自行修公共层，不创建thread、不分派子智能体、不向其他thread发消息。

正式模块不得依赖来源绝对路径、运行时sys.path注入或import旧fem_agent；review_work/run_probe.py仅为审阅证据工具，不作生产入口。不得复制env.txt、私有配置、workspace、会话、SQLite、release、provider或vendor。复制科学源代码前记录代码所有者许可和归属；没有来源LICENSE不能默认获得对外分发授权。

## 精确迁移来源

来源为 `D:/Zhaoxiang/code/fem-general-main`，审阅HEAD `9ba35c43956aa28d7b19801570eed84b2edf0915`，关键文件hash见review_work/source_before.json。若当前源码不同，核对相关差异后继续，不reset来源。

- 几何：src/fem_agent/geometry/mlcc.py，参数关系/阵列/OCC cut/语义边界；仅一个CERAMIC域，电极为扣除槽及等势边界。
- 求解：src/fem_agent/skills/electrostatics/skill.py，弱式、signed charge、energy、主C_U和raw flux；当前固定LU，没有应用通用solver选项。
- 网格：src/fem_agent/mesh/gmsh_backend.py的Python API路径、mesh/context.py的MSH→DOLFINx；不要迁CLI fallback或imported CAD审批。
- 检查：src/fem_agent/geometry/regions.py的集合审计；mesh_report.valid只查基础拓扑，形状质量原来未做；独立电荷/能量一致性、外绝缘通量需落实。
- 后处理：静电VTU/metrics与visualization/pyvista_backend.py的少量2D图方法；保持原比例/夸张比例标注。
- 基准：experiments/mlcc_electrostatics/spike.py中的平行板/串联介质公式与小例方法，抽取到本模块harness；不执行默认run_all或27例sweep。旧qualification oracle文件缺失，必须生成自己的原生证据。
- 既有证据：review_work/有本轮一个真实基线和11项合同/标签测试；source workspace/mlcc_acceptance_20261020有四个历史原生结果。它们是参考，不替代目标新实现验收。

## 实现顺序

1. 按已确认范围收敛README和draft schema，建立专业输入/输出、正常和非法例、错误码、短方法Skill、检查ID及harness状态。限定公共schema支持子集，额外科学关系由确定性代码检查。没有批准容差的检查写not_checked。
2. 用模块自有DTO、几何/网格/求解/导出边界抽取函数。专业依赖仅在模块进程导入。首版固定已验证P1/串行配置；实际使用求解器、ε0、版本/耗时/配置可追溯。若暴露参数，确保真正生效，禁止静默忽略。
3. 完成无副作用preflight：检查字段/有限数/正值、非bool整数、几何闭合、depth>0、εr>0、ΔV≠0、明确语义边界、后端版本与资源支持。不构造网格、不JIT、不求解、不写产物。10秒公共预算内完成；WSL配置只在host层。
4. 实现execute一次完整计算，公共给定artifact_dir内保存输入、网格、字段、指标、QC、日志/hash。求解stdout重定向诊断，协议stdout仅JSON。专业错误转failed/blocked、results={}和真实原因，不造物理输出。执行完成与QC失败独立。
5. 区分Q/U/C总量和单位深度量；保留Q符号/法向、C_U主值与C_Q诊断；实现外绝缘位移通量及互证指标。不得再乘层数；尖角Emax只诊断。当前schema有尚未实现要求，只有实际完成才可用于正式成功响应。
6. 加入有效验证：目标后端平行板解析、用户确认的MLCC基线、少量电压/ε/t不变量（含非1m厚度）、有计划的积分量网格比较、坏tag/求解失败/缺环境等。每项科学容差记录负责人批准依据；没有批准不把旧1%/2%复制为合格线。
7. 直接Adapter协议和模块小例通过后，按main选择的WSL路线做公共CLI接入复核。若main未决，只完成模块内可独立协议和科学测试，不自己增加WSL桥或任务服务。
8. 完成稳定操作、成功/失败/边界行为和原生证据后，才在本模块module.json声明implemented及electrostatics_2d，带明确依赖、evidence_kinds/required_checks；不登记可选耦合或COMSOL等未实现能力。真实范围覆盖由main/负责人验收总账授予。
9. 交付ACCEPTANCE.md、运行/环境/来源清单和证据索引，更新本模块文档的实际状态。审阅证据与新实现证据分目录保存，不覆盖原审阅基线。

## 环境与运行纪律

已核实 Ubuntu-24.04 / WSL2，现有解释器 `/home/zhaoxiang/miniconda3/envs/fenicsx-env/bin/python`，DOLFINx0.11.0/UFL2026.1.0/PETSc bindings3.25.5/Gmsh4.15.2。重新轻量核实版本，不换环境、不自动安装。不运行来源activate_dev/start_cae_web脚本（它们写来源workspace、注入旧包且有banner）。不要把机器路径写进科学input。

每次真算先读脚本确认规模、输出目录和副作用；默认只做已授权小例，所有开发验证输出在本模块独立工作目录。公共正式run产生的任务/产物只由公共runtime管理，须按main的集成验证安排执行。全量回归/参数扫/远程任务另行授权。退出0、PNG、mock、自检或解析公式输出不能当真实验收。

## 检查命令（相应文件实施后使用）

WSL里，从目标根执行；模块测试必须将临时/缓存/输出限制到本模块，由测试代码设置scratch。不得从测试代码写旧来源。命令中的科学Python仅是本机已核实路径，部署由main管理。

```bash
cd /mnt/d/Zhaoxiang/code/mlcc-main
export PYTHONDONTWRITEBYTECODE=1
export XDG_CACHE_HOME="$PWD/modules/fem/work/cache"
export MPLCONFIGDIR="$PWD/modules/fem/work/cache/matplotlib"
/home/zhaoxiang/miniconda3/envs/fenicsx-env/bin/python -B -m unittest discover -s modules/fem/tests -v
/home/zhaoxiang/miniconda3/envs/fenicsx-env/bin/python -B -m mlcc check
/home/zhaoxiang/miniconda3/envs/fenicsx-env/bin/python -B -m mlcc describe fea
```

候选操作正式登记、main确认WSL宿主且允许公共任务输出后：

```bash
/home/zhaoxiang/miniconda3/envs/fenicsx-env/bin/python -B -m mlcc preflight fea electrostatics_2d --input modules/fem/examples/normal.json
/home/zhaoxiang/miniconda3/envs/fenicsx-env/bin/python -B -m mlcc preflight fea electrostatics_2d --input modules/fem/examples/invalid.json
/home/zhaoxiang/miniconda3/envs/fenicsx-env/bin/python -B -m mlcc run fea electrostatics_2d --input modules/fem/examples/normal.json --defer
```

对上一命令返回的**实际task_id**执行同宿主/同绑定worker，然后读取status/result/artifact；不能复制假task编号或只排队就说已求解。若main选Windows桥，改用main已验收绑定，不能照此猜新字段。

公共默认回归 `python -m unittest discover -s tests -v` 交main运行：当前脚本固定写公共tmp/framework-tests，本模块所有权边界不允许自行调整或直接产生该处开发文件。未运行时记录not_checked，不能报告全套通过。

## 完成条件

- 一个已确认的有界二维MLCC模型，可在来源项目不可访问、旧Web/LLM关闭时独立计算；无专业库进入公共包顶层。
- 公共协议正常/非法输入/失败/真实小任务链可追溯，必要产物存在且与本次输入/方法/后端版本对应；查询不重新计算。
- 解析基准、离散/守恒/量纲/网格验证与物理适用性分别记录，未做项not_checked，批准阈值有来源；不凭exit0或旧报告提升科学状态。
- 模块实际状态/manifest/README/ACCEPTANCE一致，main能据此决定集成；没有修改公共层/其他模块/来源，也没有擅自扩展耦合或创建新聊天/子智能体。
