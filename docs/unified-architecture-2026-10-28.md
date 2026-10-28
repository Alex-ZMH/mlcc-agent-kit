# MLCC 同级能力架构与交接

0.59.0 候选；在 integration/four-scale-compute-20261028 分支整理，不合并 main。

## 结构与职责

同事已有 mlcc 是公共主干。一个 Bundle、Agent 和 Zeus 宿主继续使用原有任务生命周期；不复制光刻胶 worker，不新增聊天前端、队列服务或领域 MCP 服务。

```text
mlcc-agent/
  src/mlcc/
    capabilities.py                 六领域元数据目录，不导入科学环境
    task_service.py                 按清单选择领域创建器；读取保存结果
    tasks.py / site_runner.py       原 TaskRecord 与唯一 SSH/Slurm 生命周期
    workflow.py / result_views.py   公共任务关联、状态与结果投影
    abacus_tasks.py / lammps_tasks.py  原领域创建器与解析器，原地复用
    fem_tasks.py / phase_field_tasks.py / rve_tasks.py / spice_tasks.py
    adapter_tasks.py                Python 适配器任务的公共输入与打包逻辑
    module_contracts.py             既有专业 schema/描述文件校验，无任务存储
    contracts.py / units.py / adapter_transport.py
    legacy_scale_results.py         历史 bridge 结果只读兼容
  modules/{dft,md,phase_field,rve,fem,spice}/module.json
  modules/{phase_field,rve,fem,spice}/ 既有科学代码、schema、协议与来源
  scientific_core/                 原共享数值原语
  tools/mlcc_execute.py             一个已分配任务内的一次适配器调用
  tools/mlcc_environment_probe.py   不运行科学引擎的部署探针
```

compute/、私有包别名、嵌套 Runtime、Store 和内层队列已经移除。scale_tasks.py 与原四尺度命令保留为兼容别名。ModuleContracts 只读描述和校验契约，不生成任务。各模块依旧自持清单；公共能力发现不依赖科学包。旧科学 CLI 的领域依赖延迟至实际领域调用，目录与参数帮助可在标准库环境读取。

adapter_transport.py是JSON适配器子进程通信；同事已有transport.py属于科学输运业务，保持原文件与原导入路径，二者职责分开。

DFT/MD 清单当前将已有 create/parse 入口挂接到公共目录，不把它们伪装成新增科学操作，也没有穷举或替代同事全部领域命令。原建模、势训练、性质交付和 DFT→训练→MD 路线保留。它们是可选工作流；各领域无需等待上游任务。现有约107个CLI入口保留，原4个领域Skill及7个MCP生命周期工具保留。

## 调用与身份

```text
同一对话 → Skill/结构化请求 → task_service → 对应 *_tasks
→ TaskRecord → SiteRunner.prepare/transfer/submit/query/collect
→ 对应原生引擎或单次 Python 适配器 → 保存专业结果 → 公共读取视图
```

公共入口：

```sh
python -m mlcc list-capabilities
python -m mlcc create-task --module fem --operation electrostatics_2d_quantities --arguments args.json
python -m mlcc read-result --task /workspace/tasks/CASE/task.json
```

args.json 使用领域创建函数已有具名参数。例如 FEM 为 input_path/site_path/request_path；DFT 的 operation=create，使用原 study_path/model_path/method_path/site_path/request_path；MD 还使用原 potential_path/protocol_path。实际参数以现有函数签名与对应 Skill 为准，不推测或补造势与协议。

创建只准备文件，不提交。执行使用原生命周期命令或 MCP；固定脚本 tools/mlcc_scale.py 同样支持公共新命令及生命周期，用于标准库客户端。旧 create-scale/parse-scale 等命令继续有效。read-result 只读取已保存结果；DFT/MD 没有已解析结果时，要求先调用原显式解析命令，不在读取中启动解析或求解。

新适配器的 task_id 与平台 TaskRecord 一致，Slurm job ID 单独保存，不生成 runtime_task_id 或内层 record.json。任务目录包含 payload/ 源码、artifacts/、logs/ 与结果。native_linux 的显式 release 根为该任务目录，路径检查限定在这一个任务；源码仍位于 payload/。每次仅打包选定科学模块与公共依赖。排他执行收据保留，不自动重试或重提交。

engine 表示真实后端：abacus、lammps、dolfinx、ngspice；module_id 表示领域。Task 链视图允许没有原子 model_id 的任务，不伪造原子模型。geometry/mesh/circuit 等专业内容继续由各自 schema 描述，原子模型与方法字段原样保留。公共结果列表从已收集结果读取科学状态，避免持续显示创建时的 not_calculated。

站点配置同样按后端组织：已有site.abacus/site.lammps保留，新增site.dolfinx/site.ngspice，示例见configs/site.backends.example.json。独立模块和操作可以绑定不同解释器与部署预算；旧site.scales仅作显式兼容，同一后端同时声明新旧配置会拒绝，不自动回退。

新结果契约为 mlcc.task-result.v1，允许公共可读任务 ID；历史 mlcc.result.v1 不改名。读取按创建时保留的 schema 检查保存证据。公开 read-result 返回 mlcc.task-result-view.v1，专业结果嵌套保留；旧 parse-scale 的 delivery 兼容。执行、数值质量、科学质量、单位、来源和原生产物分别保留。DFT/MD 不接 SI 归一器，其余模块继续显式使用唯一 units 工具。无尺度传递。

## 验证与移交边界

本轮先验四模块，再验原子领域非计算部署链。机器记录见 verification/unified-architecture-2026-10-28/summary.json。

本地运行：

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -p test_scale_tasks.py -v
PYTHONPATH=src python3 -m unittest discover -s tests -p test_unified_architecture.py -v
PYTHONPATH=src python3 -m unittest discover -s tests -p test_site_runner.py -v
```

源码父项目公共回归另运行 python3 -m unittest discover -s tests -v。本轮并未宣称已运行同事全部原子科学测试。

首轮685–688在产物目录映射处失败，原记录保留；修正显式任务release边界后，689–692分别完成FEM、相场、RVE、SPICE的实际计算与收集。不是用退出码替代科学验收，原 quality.not_checked 保持。历史 bridge 成功任务可只读消费。

DFT/MD 探针只验证所选二进制存在与执行权限、服务器公共Python能导入本次源码中的原任务创建模块，以及 SiteRunner 的准备/传输/Slurm提交/查询/收集。不启动ABACUS或LAMMPS，不写科学输入，不做SCF、MD步进或势验证。其 native_engine_start 与科学验收均 not_checked；不能当作完整原生计算链路通过。

实际结果为部分通过：693/694使用现有公共.venv完成调度和收集，二进制存在且可执行，但领域导入缺numpy；695/696显式绑定到已核对具备NumPy/ASE/SciPy的MACE环境后，导入仍缺pymatgen，探针以失败退出并收集原错误。没有安装或更改同事环境，也没有自动切换科学引擎。最终宿主Python及其完整领域依赖须由同事确认；不能把上述调度通过写成DFT/MD领域调用通过。

创建器与解析器可以继续运行在同事原有的本地宿主，服务器只接收原生命令；本轮服务器导入检查针对探针明确选定的Python。正式接入应复用同事的宿主环境，不要求求解器Conda环境承载全部公共Python依赖。本轮没有核验该私有宿主，以上缺项不构成其既有工作台失效的证据。

交回同事后验收：使用其明确的模型/方法/势/协议，通过公共 create-task 创建真实DFT/MD任务；用原解析器保存结果，核对 read-result/任务列表/Study与原入口一致；在现有私有Zeus宿主安装本Bundle，检查同一对话中的六领域可达、单次提交与结果追问。私有宿主不在公开仓库，本轮未改动或现场验收它。DFT/MD科学阈值与精度由同事确认。
