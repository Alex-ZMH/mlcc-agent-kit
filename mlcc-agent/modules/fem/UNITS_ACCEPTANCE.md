# FEM 多单位接入与验收（2026-10-22）

模块版本0.2.0。旧 `electrostatics_2d` 保持原SI输入/输出契约；新增 `electrostatics_2d_quantities`，使用唯一共享核心 `mlcc/units.py` 1.0.0。只改modules/fem，不修改公共层或来源项目，不调用LLM、不安装/升级环境、不增加物理场。

## 已实现路径

```text
原始量值输入（公共input快照保留）
 → Windows Adapter严格schema及字段kind/source校验
 → [Windows Python, -I, <Bundle>/mlcc/units.py] JSON线协议
 → canonical SI + 逐字段审计
 → 既有SI科学validator
 → 既有WSL Conda/DOLFINx纯电内核
 → 原SI结果 + 单位审计产物及provenance引用
```

公共契约与交接：docs/units-contract.md、docs/units-handoff.md。core固定路径从受信模块位置推导，不来自input/LLM/cwd；shell=False，无sys.path注入，不复制换算表、不fallback到本地换算。

新schema：schemas/electrostatics.quantities.input.schema.json，ID=fem.electrostatics-quantities-input.v1，units=explicit_quantities。只接纳数值量值容器 `{value,unit,source:{kind,reference}}`，有量纲字段去掉原 `_m`/`_V` 后缀。所有对象严格additionalProperties=false。计数与epsilon_r保持裸整数/数值和既有约束。多单位入口拒绝缺单位、缺/空/unspecified来源、非有限、错维度、未知单位、多余字段及伪装规范化记录。

直接Adapter和公共CLI使用同一规范化准入。预检不写任务产物/不求解。输出仍为m、V、V/m、C、F、J及对应每米深度量；C为库仑。不存在把摄氏度C拷贝成电荷规则的实现。WSL只收到原SI schema，不重复缩放。

## 一次新的真实等价计算

- 输入：[quantities-mm.json](examples/quantities-mm.json)，长度mm，电势kV；与原normal.json对应同一合成小模型。
- 新公共任务：`task-c42ee64234f44c249bbb35960bd8f2be`。
- 执行命令：Windows `python -B -m modules.fem.harness.verify_units --run-real`。实际经公共preflight→run(defer)→worker→result/status，不直接运行科学脚本替代。
- 本模块工作记录：[summary.json](work/units-e2e-54cef8d78d3345d482ee9c0840a6aa0f/summary.json)。各命令argv、退出码、stdout/stderr同目录保存。
- baseline采用已保存SI任务 `task-84d89822509e4c77b991e4aa1edad38f`，未重新求解baseline，不做扫描。
- native证据：`outputs/tasks/task-c42ee64234f44c249bbb35960bd8f2be/artifacts/native/{request,response,launch}.json`及日志；环境仍Ubuntu-24.04、fenicsx-env、DOLFINx0.11.0。

结果：总电容 **1.2893122250166755e-8 F**（12.8931222502 nF），能量 **6.446561125083377e-7 J**，7392三角形/5354自由度。新结果与SI基线results逐字段完全相等；没有用科学容差掩盖换算差异。

11项真实链断言全部通过：原始公共输入、原始输入产物、canonical SI、规范化报告、原生只接收SI、与SI基线结果完全相等、QC状态不变、只读查询不改记录、产物引用无重复、单位审计产物已登记、原生产物hash全部相符。

产物包含并登记：

| 产物 | 内容 |
| --- | --- |
| artifacts/input.original.json | 原始用户量值/单位/source，不覆盖 |
| artifacts/input.canonical-si.json | 实际交给SI validator及WSL的输入 |
| artifacts/unit_normalization.json | 每个字段的原表示/值/单位/来源、规范化值/单位、factor/offset/rule/core_version |
| artifacts/input.normalized.json | 科学入口保存的实际SI输入 |
| artifacts/fields/fields.vtu、mesh/mesh.msh | 真实场与网格 |
| artifacts/metrics.json、diagnostics.json、quality.json | 原科学结果、诊断、质量检查 |

计数/epsilon_r未另提供来源容器时公共记录source=unspecified，不伪造证据；它们的原值在公共input与原始产物中，材料source_reference也完整保留。单位报告是声明与换算审计，不是来源真实性认证。

## 离线、接口与兼容验证

- **41项模块测试通过**，包含原23项全部通过及新增18项。记录：[tests.log](work/units-e2e-54cef8d78d3345d482ee9c0840a6aa0f/tests.log)。
- 显式SI、mm/kV、混合um/μm/µm与SI样例canonical payload完全相等；调用者原输入不变。
- 共享quantity记录重复处理保持原记录，canonical SI重复validator不二次缩放；新外部schema拒绝直接传规范化记录来绕过审计。
- 未知/错维度/缺单位/缺来源/非有限/嵌入冲突文本/多余字段/计数附单位均拒绝；无效单位在Deployment.load前被拦截。部分无效表示首先被严格schema拒绝，未进入核心，不误称测试了该核心分支。
- 缺核心、坏JSON、错误版本、非零退出、超时，以及被篡改的返回单位/原始表示/kind均拒绝，无本地fallback。这些故障注入是mock/接口测试，不是真实科学失败实验。
- 无PYTHONPATH的直接Adapter实际子进程可消费唯一核心；缺部署时正确到达DEPLOYMENT_NOT_CONFIGURED。公共CLI严格schema错误预检不创建task。
- 旧SI操作测试确认不调用单位核心；历史五份真实SI结果再次用当前schema/规范化器校验。未更改旧任务、旧schema或旧结果。
- 公共Bundle结构检查valid=true（8模块）。Windows启动包装器保留旧默认Operation，也可显式选择新Operation。
- 交付检查覆盖Python语法、schema、原始/单位输入、来源导入与本地链接。首次在本文件尚未写入时检查提示缺少UNITS_ACCEPTANCE.md链接，补齐文档后复查；未修改公共设计。

复核命令：

```powershell
python -B -m unittest discover -s modules/fem/tests -v
python -B -m modules.fem.harness.check_delivery
python -B -m mlcc check
# 若需要额外真实任务再显式执行；不会由离线测试自动触发
python -B -m modules.fem.harness.verify_units --run-real
```

## 未检查与后续

单位/表示与真实运行闭环完成，不升级原科学QC。残差/形状/电荷平衡/电容一致性的验收阈值、本任务网格收敛及解析对照、模型适用性、材料工况有效性和实测独立器件对照继续not_checked。未新增科学阈值、未做新LLM调用、相场尺度映射、多物理或COMSOL。

共享核心只支持契约白名单；本新schema更严格，只接受数值容器，不接任意单位表达式/自由文本。升级核心版本需显式适配与测试，版本不符即拒绝。排队部署快照与外部进程回收依旧是已有公共增强事项，不阻断此次单位接入。相场由其模块消费同一核心并负责自己的无量纲映射，本FEM不实现或声称完成该映射。
