# FEM 单位接入设计（2026-10-22）

状态：已接入 main 发布的 `docs/units-contract.md` / `mlcc/units.py` 1.0.0；新增 `electrostatics_2d_quantities` 已完成 Windows→WSL 真实等价计算。下文方案中的待发布事项已由后文实施说明解决，不复制第二套换算表。

## 当前事实

当前 `electrostatics_2d` 只接受 `fea.electrostatics-input.v1`、`units=SI`、`*_m` 与 `*_V` 数值。`device_fem/validation.py:validate_input` 在任何部署加载前执行结构与物理关系检查；`adapter_api.py:handle` 把同一有效SI payload传给Deployment，WSL科学入口再次检查SI。运行层保存原始公共输入；结果明确使用m/V/V/m/C/F/J及每深度量。

来源项目实际单位边界在只读 `src/fem_agent/units/system.py`（UnitNormalizer）和 `interpretation/quantity_boundary.py`。后者耦合CaseSpecPatch/Pydantic及旧evidence/provider流程，不迁入；公共核心由main抽取。来源摄氏度C别名不可覆盖电荷库仑C语义。

## 模块方案

1. 保持旧操作/旧SI schema严格不变；历史任务仍用原快照读取，不重写输入或旧结果。
2. 优先新增显式多单位操作及严格独立输入schema，复用当前Adapter/科学内核；操作名在公共契约到位时确定。避免让`*_m`字段同时表达mm，或在原SI schema中允许额外单位字段。
3. 多单位操作中有量纲字段须带显式量值、单位与可追溯来源；字段预期维度由模块固定映射，不由用户/LLM选择。间隙数保持整数计数，epsilon_r保持物理无量纲数。
4. Windows Adapter调用唯一公共单位核心得到canonical SI和换算报告，再调用现有validate_input；WSL仅接收现有SI schema，不加载LLM、公共任务宿主或第二套单位转换。
5. 执行产物分别保存原始输入、多单位规范化报告、canonical SI及核心版本/规则；公共input快照仍是用户原输入。provenance记录原始/规范化关系；输出科学schema/单位不变。
6. 预检与直接Adapter都走同一确定性路径。预检不写产物、不求解；执行时只在runtime-owned artifacts下登记单位证据。无效单位应在部署/科学调用之前拒绝。
7. 同一输入重复规范化不得再次缩放；把结果canonical SI再次送旧validator保持值不变；不接受用户自称normalized而跳过校验的标记。

## 待公共契约明确

- 唯一导入路径、量值/来源格式、规范化报告字段及核心版本标识；不猜API。
- 公共transport以脚本路径启动Adapter，cwd在模块目录，当前入口只自然导入本模块。需确认公共核心如何在该子进程中被正常导入；不使用sys.path注入或来源路径。若公共层尚无标准bootstrap/安装机制，写INTERFACE_PROPOSAL等待main处理。
- 支持的显式单位/别名与维度，按契约限制；FEM不自行扩充词表或摄氏度解释。

## 验证清单

- 旧23项测试继续通过；公共CLI与直接Adapter均校验新严格schema。
- mm/um/m、V/kV（仅在公共支持时）等价输入得到相同canonical SI及内核参数；原值/单位/来源未被覆盖。
- 拒绝未知、维度冲突、缺单位/缺来源、非有限、bool冒充数值、额外字段及冲突声明。
- 重复规范化、旧SI回流不二次缩放；输出总量/每深度语义及旧任务读取不变。
- 若有必要且授权允许，运行一个小型真实多单位等价任务，与已保存SI基线按实际离散结果比较；不做参数扫描/新LLM调用，不新增科学容差。
- 单位/表示一致性通过不能升级材料适用性、独立器件对照或其他not_checked科学检查。


## 已落地接口与兼容性

- 模块0.2.0保留原 `electrostatics_2d`、原SI输入和输出schema；新增 `electrostatics_2d_quantities`，输入标识 `fem.electrostatics-quantities-input.v1`、units=`explicit_quantities`。
- 新长度字段去掉 `_m`，电势字段去掉 `_V`，采用严格数值容器 `{value,unit,source:{kind,reference}}`；本接口不接受自由字符串或规范化记录作外部量值。计数及epsilon_r保持裸数值，与旧schema相同限制；epsilon_r来源仍由material.source_reference保留。所有对象additionalProperties=false。
- 字段kind由quantity_input.prepare固定；模块只收紧来源要求（非空且非unspecified），不推断来源。公共核心对计数/epsilon_r的未提供source记录为unspecified，不冒充实验来源；原字段及material来源仍在原始输入/规范化SI中完整保存。
- 核心通过固定Bundle位置 `[sys.executable,-I,<project>/mlcc/units.py]` 以JSON线协议调用，shell=False；无sys.path注入、来源运行依赖或本地换算fallback。core_version固定1.0.0；启动、协议、版本、错误、超时、返回记录不一致均拒绝。
- 规范化后的SI重新走validate_input，再交已有Deployment和科学入口。WSL代码/方程未改。原始公共input.payload保持量值输入；登记 `artifacts/input.original.json`、`input.canonical-si.json`、`unit_normalization.json`，报告保留raw值/单位/source、canonical值/单位和factor/offset/rule/version。
- 预检执行同一路径，预检不写产物/不求解。旧SI入口不调用单位核心；旧任务和对话不改写。重复处理由公共quantity记录replay或SI validator完成，禁止拿canonical数值再套旧raw单位。外部规范化记录不被新strict schema接纳。
- 成功原生产物包含三份审计文件并校验hash；失败时仍登记已生成的审计诊断，不虚构结果。provenance关联规范化报告；输出m/V/V/m/C/F/J及每深度量不变，C是库仑。

真实等价任务和检查见 [UNITS_ACCEPTANCE.md](UNITS_ACCEPTANCE.md)。待公共导入机制事项已由main独立线协议解决，不再阻断本模块。

## 2026-10-22 器件三项多单位增量（0.4.0已实现）

用户进一步要求新电热/AC/EM也走统一unit normalization，不能仅限定用户SI。保留三个SI schema/操作与旧任务，新增各自*_quantities入口。命名/字段及验收见 [EXTENDED_UNITS_HANDOFF.md](EXTENDED_UNITS_HANDOFF.md)。调用公共core1.0.0/catalog1.1.0，先核对catalog语义/维度/规范单位，再normalize_fields；审计记录实际catalog版本，不按版本字符串阻止仅追加白名单；引擎版本与词表版本分别记录，不另造倍率、温度偏移或fallback。

所有有量纲量都经normalize_fields后重命名为原SI字段，current.convention=rms和voltage_convention保持物理约定，不参与单位倍率。全部复分量独立带单位/source，eps_r/tan_delta/mu_r/count保留物理无量纲/计数语义。每任务保存原始typed结构与SI输入/标准quantity审计；WSL仍只接旧SI操作，方程/损耗/QC不变。每新入口仅运行一个真实等价任务，比对已保存SI基线，不做参数矩阵或新LLM调用。验收见EXTENDED_UNITS_ACCEPTANCE.md。
