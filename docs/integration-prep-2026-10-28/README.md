# mlcc-agent-kit 集成准备

日期：2026-10-28。阶段：框架学习、分支与合并前基线；没有实施计算模块迁移。

**本轮最新范围与执行建议见 [四尺度实施方案](implementation-plan.md)**：复用同事工作台和DFT/MD的TaskRecord→SSH/Slurm生命周期，四尺度独立计算，不做尺度传递。用户已明确DFT/MD保持原生单位体系、不接本项目单位归一器；单位准入探测仅作探索记录，不转成DFT/MD改造任务。

用户补充确认的最终目标是一个对话框调用所有尺度。重点分析见 [DFT/MD 实际调用链与统一对话设计](dft-md-and-unified-dialogue.md)，包括同一 Agent 的四个 Skill、两条专业创建链、共用 Slurm，以及现有 MCP 缺少专业请求创建/通用结果读取入口的边界。

用户进一步确认合理需求允许调整架构。最终取舍补充见 [光刻胶/同事平台/本项目对照](photoresist-comparison.md)：已找到同事明确参考光刻胶的文档依据；实际Zeus聊天宿主位于未随公开仓库提供的私有workspace。隔离包只是可选首切片，长期可调整包名、公共运行层和专业入口，传输可复用受控脚本或具名工具。

## 工作副本与版本

- 上游：https://github.com/Alex-ZMH/mlcc-agent-kit
- 审阅基线：`b5cbc711211dd78d37beb7e7aecb00882cb4bb97`，默认分支 `main`，Bundle / Python 包版本 `0.57.0`。
- 本地工作副本：`D:\Zhaoxiang\code\mlcc-main\tmp\integration\mlcc-agent-kit`；WSL 路径 `/mnt/d/Zhaoxiang/code/mlcc-main/tmp/integration/mlcc-agent-kit`。
- 集成准备分支：`integration/mlcc-compute-prep-20261028`。实际 Git 状态以同目录 receipt.json 为准。
- 当前 `mlcc-main` 是无 Git 元数据的源码目录，不能对它直接执行 Git merge。后续以同事仓库为 Git 主线，按白名单迁入本地源码，保留来源快照。
- 认证：WSL 用户 `zhaoxiang` 的 SSH 仓库读取成功；GitHub 连接返回 push 权限。本轮没有通过实际 push 验证写入。

工作副本放在已忽略的 `tmp/` 中，具有自己的 `.git`，不应随父项目打包。集成准备报告在父项目 `docs/` 持久保存；准备分支内也保存报告副本。首次完整下载超时，改用浅获取；正式评审历史时再补历史，不能把浅克隆当成完整历史。

## 已确认的框架

| 边界 | 同事仓库 | 我们的框架 | 接入处理 |
| --- | --- | --- | --- |
| 包与 CLI | `mlcc-agent/src/mlcc`，命令 `mlcc`，Python >=3.12 | 根目录 `mlcc`，命令也为 `mlcc`，Python >=3.11 | 两者不能安装到同一解释器；不靠 PYTHONPATH 顺序决定加载谁 |
| Bundle | `mlcc-agent/bundle.json`：`matterai.bundle.v2`、7 个任务 MCP 工具、4 个 Agent Skills | `bundle.json`：`mlcc.bundle.v1`、独立 CLI 与受控 Codex 宿主 | 不是同一协议，不能覆盖清单或宣称直接兼容 |
| 发现 | CLI 显式注册/分派领域命令 | 扫描 `modules/*/module.json` | 平台增加薄入口，内部模块仍保留自己的描述和专业 schema |
| 执行 | `SiteRunner.prepare/transfer/submit/query/cancel/collect`，SSH/scp + Slurm | `Runtime.preflight/run/work/status/result/artifact`，JSON 子进程与持久任务 | 远端 Slurm 负责调度，计算包 worker 负责一次模块执行；避免二次提交 |
| 结果 | DFT/MD 等各自领域结果，Study 交付；调度、科学与设计状态分开 | `mlcc.result.v1`，执行状态与 numerical/scientific QC 分开 | 保留原结果，增加引用与显式映射；禁止由退出码或非空数值推导科学通过 |
| 参数交接 | `mlcc.domain-parameters.v1`：kind/model/study/properties/execution；已有保存产品适配 | 各模块专业 schema + 共享 UNIT 核心 | 先保持独立操作；有具体消费需求再逐字段定义映射 |
| 科学依赖 | 包依赖 ASE/NumPy/SciPy/Phonopy 等，另有 deepmd bridge | 公共包标准库；FEniCSx/ngspice 留在独立环境 | 不把 DFT/MD 依赖并入我们的公共环境，也不升级现有科学环境 |

源码定位（相对于同事仓库）：

- `mlcc-agent/src/mlcc/modeling.py`：模型身份、原子 ID 与结构产物。
- `tasks.py`：普通 JSON TaskRecord，保留领域扩展字段；本身不是完整领域验证器。
- `site_runner.py`：显式 command/resources/transfer/collect；不是领域科学内核。
- `results.py:make_dft_result`：消费已解析 ABACUS 结果，核对任务/Study/原生来源；不适合作为 FEM/SPICE 通用结果基类。
- `domain_parameters.py:domain_parameter_product`：当前实际合同中的 properties 是列表；函数只封装显式值，不做单位转换或科学验证。
- `saved_domain_parameters.py:build_saved_domain_parameters`：消费已保存产品，不重新求解；支持 NEB、界面、MSD、replica、占位等明确种类。
- `property_delivery.py`、`studies.py`：Study 消费和领域交付。
- `continuum_parameters.py`、`comsol_export.py`：已有连续介质参数与目标导出，需要按消费者核对坐标、单位、状态。
- `cli.py`、`mcp_server.py`：平台命令/工具的薄接线。

对方 `docs/modular-stage-handoff-v001.md` 有历史提案示例。当前源码已经有 `domain_parameters.py` 与保存产品适配，不能把该历史文档中的“尚未实现”套到全部当前能力，也不能把提案的 properties 对象格式当成实际列表合同。

公开仓库明确排除真实轨迹、模型权重、站点私有数据和运行证据。因此本次可审阅实现与文档，不能仅凭 clone 确认所有 DFT/MD 科学验收已完成。真实记录的可访问位置、具体已验收操作和负责人确认仍需在实际接入时核对。

## 建议的首个集成切片

建议保留同事平台作为统一的 Bundle/CLI/MCP/Study 外壳，将我们的完整独立计算包放入同仓的隔离目录（候选 `standalone/continuum/`），由显式解释器和固定入口调用。目录名是方案，不表示本轮已经迁入或已经获得平台接口。

1. 白名单迁入 `mlcc/`、`schemas/`、`scientific_core/`、四个科学模块、接口自检模块、必要 Agent/Skill/配置模板、公共 tests 与发布说明，保留它们的相对位置。Scientific Core 和唯一 UNIT 实现必须随包迁入，不能只复制四个 adapter。
2. 对方 `mlcc-agent/src/mlcc/` 原样保留。在独立虚拟环境/固定绝对入口运行我们的包；包根 cwd 和 `--project` 必须显式。桥接禁止在平台进程中 `import mlcc.runtime`，因为这会碰到对方同名包。
3. 第一条平台入口先做 list/describe/check 与已保存结果读取，证明包选择、schema、引用和只读边界。此步骤只是接口验收。
4. 再增加明确的 preflight/submit/collect 桥接。远端 Task.command 调用隔离包的 queued worker；记录 platform task ID、Runtime task ID 和 Slurm job ID 的关系。平台 query 不能隐式运行 worker，prepare/preflight 不能提交作业；cancel 必须核对实际 Slurm 终止，不能伪装成 Runtime 已有取消 API。
5. 首个真实操作选哪一项，在执行切片确定时明确；不预先承诺把 26 个操作同时做参数耦合。已保存结果导入、轻量接口验收、新科学计算分别记录。
6. 通过双方回归与一个明确小任务后，再按同样边界接入其余操作；数据参数传递和跨尺度自动化另立接口需求。

当前本地待迁入能力：FEM 0.4.2（8 操作）、phase_field 0.4.0（10 操作）、RVE 0.1.3（4 操作）、SPICE 0.2.1（4 操作），共 26。相场绝对 D/E 或 F/m 张量不能自动变成相对介电常数，更不能直接当作 RVE 输入；模型、参考尺度、分支、坐标、背景贡献必须显式核对。

## 分支与验收顺序

准备分支 → 隔离源码导入提交 → 只读桥接提交 → 执行桥接提交 → 回归与限定真实案例 → PR → 审阅后 merge。每个实现提交都应带来源版本和测试证据，提交前从 origin/main 检查同事新增改动，避免覆盖其开发。

导入排除：`outputs/`、`tmp/`、`reference/`、实验工作目录、大体积历史运行目录、`__pycache__/`、`.venv*/`、`config/local*.json`、`.env*`（模板例外）、`server_credential.txt`。不能直接 `cp -r mlcc-main` 或 `git add .`。需要发布的真实案例证据另外按最小可公开清单审阅。

后续服务器路径继续使用 `/home/v100/projects/mlcc/zhaoxiang/` 下独立子目录；不照抄上游 README 的共享根目录示例，不重建或升级已有 fenicsx/spice 环境。

验收至少核对：

- 两个包/CLI 在各自进程加载正确文件，平台环境不吸收 FEniCSx/ngspice 依赖。
- 现有 26 个操作的描述/schema 保持可读，旧任务不被迁移改写。
- 预检无提交；一次授权只执行一次；只读查询不重算；错误/超时/取消不升级成功。
- `not_checked`、未收敛、null、单位、张量顺序/坐标、来源与原生产物引用逐项保留。
- 保存结果的导入不能伪装为新执行；远端私有路径不伪装成本地可读取产物。
- 默认公共回归与两个项目各自适用的轻量测试通过；新科学计算按明确操作、环境与原生证据单独验收。

## 待定项

实际接入时确认首个操作、平台产品入口命名、部署目录/解释器绑定、Task/Study 身份关联、真实 DFT/MD 验收记录访问，以及哪些参数是首个消费者真正需要的。以上不阻塞本轮克隆和框架准备。当前没有执行 DFT/MD、在线 LLM、服务器求解或修改对方科学内核。

本轮检查及实际分支状态见 `receipt.json`、`local-check.json`、`local-unittest.log`。上游测试依赖是否可用以 receipt 为准；缺依赖不得记为回归通过。

本轮实际验证：本项目WSL公共结构检查通过，公共unittest **119/119通过**；上游SiteRunner的FakeExecutor单测 **13/13通过**，109个Python源文件语法解析通过。上游workflow测试在导入阶段因缺少pytest未运行；该WSL基础Python也没有上游声明的科学依赖，因此完整上游回归为 `not_checked`。没有安装/替换科学环境。以上均不是新的科学或统一对话端到端验收。
