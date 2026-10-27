# 0.31 公共 LCAO 创建器最小接线合同 v001

状态：已按用户最新授权实施并验收。一次合并Slurm job357为COMPLETED/0:0、3秒，29项新增检查通过；0.31已启用冻结、0.30回退、源码0.32候选。请求1CPU/0GPU/2GiB/10分钟，Slurm实际分配2线程；没有运行ABACUS/PYATB或旧测试。[正式验收](../workspace/reports/lcao-public-creator-v031-v001/release-acceptance.json)。以下保留冻结接口与已执行验收方案。

## 范围和现有依据

复用实施窗口已交回的短接口清单，以及现有 `AbacusMethod / abacus_method_from_config / _input_text / _write_stru / prepare_abacus / create_abacus_task`。真实输入依据为 `workspace/reports/czo-native-dielectric-v001/producer/prepare_reference.py` 及269、284–307保存的INPUT/STRU/方法/映射；不复制其CZO元素、路径、相或数值为系统默认。0.30的355/356消费和完整宿主不重验。

首切片新增ABACUS 3.10.1 LCAO、中性、非SOC、nspin=1、fixed occupations、固定胞SCF、GPU/cusolver。PW已有行为保留。LCAO relax/NSCF/Berry、带电、自旋2、CPU其他solver不在本切片，明确拒绝，不能靠放宽通用校验顺带支持。Gamma/Born/物理branch不是SCF创建前置；它们只约束后续响应消费和科学结论。

## 最少配置字段

| 位置 | 字段/规则 | 去向 |
| --- | --- | --- |
| 方法顶层 | 既有 `basis_type`，值pw或lcao；不新增CLI basis开关 | AbacusMethod、INPUT、method.json、task.json |
| 方法顶层 | 新 `numerical_orbital_ids: {element: resource_id}`，LCAO逐元素完整且不含多余元素 | 站点资源解析、STRU、run脚本、method.json |
| 站点abacus | 新 `numerical_orbital_files: {resource_id: remote_path}` | 与赝势同样按显式ID解析，便携Bundle不写v100路径 |
| 方法input_qualification | 新 `orbital_header_snapshot`，相对method文件或绝对路径 | 保存原生NAO header、来源路径、method_set/site绑定及UPF配套审阅来源 |
| 方法顶层 | 新 `lcao_output`，可省略；如提供须显式含 `out_chg/out_bandgap/out_mat_hs2/out_mat_r` 四个整数0/1 | INPUT及method.json；不与既有out_pot output_control混用 |
| 方法/请求其余字段 | 复用science、execution、parameters、element_order、UPF选择、kpoints、Model/Study和resource_request | 沿既有创建链透传，不自动替换或加密 |

LCAO首切片不接既有PW electrostatic `output_control`。请求级不得重写basis/轨道/输出合同；方法是唯一科学配置来源。NAO header检查元素、XC、cutoff/径向基组信息、源路径/所选ID与UPF配套审阅绑定，不以“文件存在”授予材料精度或高能未占据态资格。元数据保留原生摘录、库/版本及配套依据，不能自造已通过的配套记录；没有快照时报告输入缺项。

## 冻结的函数接口增量

以下仅列新增参数/字段，其余既有参数和返回类型保留。

```python
# abacus.py：实施窗口所有
AbacusMethod(..., basis_type: Literal['pw', 'lcao'] = 'pw')
abacus_method_from_config(config) -> AbacusMethod  # 从顶层注入basis_type
AbacusExecution.validate(self, *, basis_type: str = 'pw') -> None
_input_text(..., lcao_output: Mapping[str, int] | None = None) -> str
_write_stru(..., numerical_orbitals: Mapping[str, str] | None = None) -> list[int]
prepare_abacus(...,
    numerical_orbitals: Mapping[str, str] | None = None,
    lcao_output: Mapping[str, int] | None = None,
) -> AbacusPreparation

# method_inputs.py / method_tasks.py：主线所有
parse_nao_header(text: str, source_path: str) -> dict
qualify_lcao_orbitals(config, orbital_headers, orbital_paths) -> dict
method_numerical_orbitals(config, site) -> dict[str, str]
check_method_configuration(model, config, site, method_path) -> dict  # 签名不变

# abacus_tasks.py / CLI：主线所有
create_abacus_task(*, study_path, model_path, method_path, site_path, request_path)
# 签名和create-abacus五项路径参数不变；无需新命令或runner。
```

旧直接PW调用的默认basis保留历史语义，不默认选择LCAO；公共creator仍要求方法顶层basis。若science中另有basis副本则必须与顶层相符，不静默选取。`prepare_abacus`用method.basis_type调用execution校验；PW仅沿既有cg路径，LCAO首切片仅GPU/cusolver。`_input_text`从method写basis，LCAO写 `orbital_dir ./` 和显式输出字段。`_write_stru`在ATOMIC_SPECIES之后、LATTICE_CONSTANT之前按同一element_order写NUMERICAL_ORBITAL文件名，复用现有分组及atom-map，不改变原子ID。

既有 `qualify_method_inputs`仅把basis识别扩展到pw/lcao；原UPF、价电子、电荷和电子数规则继续执行。`check_method_configuration`在LCAO分支读取NAO快照、调用 `qualify_lcao_orbitals`，将结果加入checks，保留既有electron_count；所有必需检查通过才input_qualified。此标志不等于scientific/production qualified。

## 本轮文件所有权（实现已交回）

| 所有者 | 独占文件 | 责任 |
| --- | --- | --- |
| 主线 | abacus_tasks.py、method_inputs.py、method_tasks.py、cli.py（如仅help需改）、新增tests/test_lcao_task_creation.py | 方法/资源资格、公共任务创建、轨道来源和传输、集成验收 |
| 既有“推进 MLCC H0 闭环实施”窗口 | abacus.py、新增tests/test_abacus_lcao_writer.py | 上述writer/方法接口、NUMERICAL_ORBITAL、basis/solver/输出及映射 |
| 主线 | 本合同、计划/状态/版本记录 | 最终review；实施期间不得交叉编辑上述独占文件 |

双方不是独自工作，不覆盖另一方更改；接口变更先交回主线。本轮已交回源码，主线完成集成；主线另受托Luna独占实现method_inputs.py/method_tasks.py，并复核其变更。此表不授权自动扩展新的实现范围。

## 输入到产物映射

| 产物 | 责任和映射 |
| --- | --- |
| task.json | creator复用task_id/Study/Model/方法绑定；增加basis_type、轨道ID/来源及请求产物，scheduler_job_id初始null |
| Model/Study | 读取现有结构/选择并保留引用，input.extxyz保存实际输入；不派生新相、不修改原Model/Study或创建新的科学结果 |
| INPUT/KPT | writer写方法参数、GPU/cusolver、basis、输出和显式k网格；不自选精度 |
| STRU/STRU.atom-map.json | writer按element_order写UPF及NAO basename；复用source_index/atom_id/ABACUS order与晶胞单位 |
| method.json/qualification | writer记录basis、轨道源路径/文件名、lcao_output；creator补ID、快照来源与配套审阅、method_set及电子数资格；科学/生产false |
| run-abacus.sh | creator与UPF并列生成NAO复制指令，shell引用保持原有规则；basename碰撞明确报错，不能覆盖其他元素文件 |
| job.sbatch | 继续由既有SiteRunner.prepare生成，creator本身不隐式prepare/transfer/submit；DFT time=0、no-requeue和显式资源沿现有runner；实际提交后才绑定原生job ID |
| transfer/collect_paths | 保留INPUT/STRU/KPT/map/method/run脚本及既有OUT收集；NAO按站点远端路径在作业内复制，不把资源库或科学workspace塞进Bundle |

## 冻结验收方案（本轮357已执行）

后续实施获授权后，仅安排一次v100 Slurm非DFT工程验收，调用现有 `create-abacus` 和runner.prepare，在独立目录生成参考269及一个已保存位移的公共输入。读取实际原Model/Study/UPF和NAO快照，核对basis/solver、四项输出、20原子映射、轨道次序/来源/复制指令、电子数、资源/time0/no-requeue、任务未提交状态。只对归一化后的原生参数/结构/映射做域比较，不能比较不同task_id/路径/记录时间要求逐字相等；不重新运行引擎。

同一作业内仅增加变化所需的失败样例：缺轨道、元素或XC不符/配套来源缺失、basename冲突、PW携带LCAO设置、越界solver/stage/charge、请求级覆盖。增加一个既有PW输入写入参照，确认没有NUMERICAL_ORBITAL/输出泄漏；不重跑旧PW测试集。writer与creator新节点在同一任务中验收，不各自扩成重复完整测试。若代码发生定向修复，仅补受影响检查，保留原失败。

269/284–307证明原冻结方法的真实GPU执行；355/356证明保存结果消费，均复用，不把它们冒充尚未存在的公共创建器证据。未来安装如需要验证，只补新安装入口；旧宿主/MCP未改则复用。完整Born分支、Γ响应策略、离子/静态介电及材料资格仍另列未完成。

实际交付：已安装0.31的公共create-abacus生成269参考及284位移对应的新输入，runner.prepare生成脚本，29项新检查通过。新任务scheduler_job_id为null，H/S/r native_output_observed为false；原269/284执行和355/356消费复用，不伪装成新引擎任务。完成的是公共创建/资格/参数透传软件切片，物理Born、Γ响应处理、离子/静态介电和整个MLCC系统仍未完成。
