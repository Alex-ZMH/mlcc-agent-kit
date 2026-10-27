# 中性晶体缺陷任务连接切片

本切片只连接用户已经选定的宿主模型、显式派生的中性缺陷模型和两个 ABACUS 固定胞 SCF 输入。它不选缺陷位点、不选相或掺杂、不替换方法、不提交 Slurm 任务，也不把任务定义解释为科学资格。

## 真实 API 缺口

现有 `mlcc.abacus_tasks.create_abacus_task()` 一次只绑定一个 `study.model` 和一个模型目录；现有 `mlcc.defect_thermodynamics.neutral_formation_from_tasks()` 只读取已经完成且有原生证据的 host/defect 任务。二者之间没有一个连接层来同时检查派生谱系、同胞、两个请求和化学势来源，再产生一对可交接的任务路径。

`mlcc.defect_tasks.create_neutral_defect_task_pair()` 补上这个窄接口。由于现有创建器强制一个 study 只能选择一个模型，调用者必须提供显式的 `host_study_path` 和 `defect_study_path`；接口不把一个 study 自动重写成两个模型绑定。

后处理阶段允许暂时没有化学势点。`neutral-formation` 的 `--chemical-point` 是可选参数；省略它不会跳过 host/defect 的原生任务检查，而是在两个任务通过完整的 ABACUS、同方法、同能量定义、同胞、谱系和组成差分检查后，只交付原生能量差和可追溯来源。形成能需要化学势，不能从缺失输入中推导。

## 输入合同和最小修改

函数要求：

- `host_model_path` 是已存在的模型目录；`defect_model_path` 是 `derive_defect_model()` 产生的显式谱系目录。
- 两个 study 都必须显式选择相应的模型身份。非 engineering fixture 还必须保留 material 和 phase_requested；模型若已经记录 `study_binding`，它必须与 study_id 相同。
- `method_path` 和 `site_path` 是两任务共用的同一份配置。两个 request 必须是不同 task_id、`calculation=scf`、`input_transformation=null`，并含有明确资源请求。
- `chemical_reference_path` 必须是 `neutral_formation_from_tasks()` 使用的明确 chemical-point JSON，包含 `mu_eV_per_atom`、`engine`、`engine_version`、`method_set`、`energy_definition` 和 `source_reference`；μ 必须覆盖缺陷的每个组成变化元素。该文件只作为后处理来源，不在创建阶段推导化学势点。

这条要求属于 `create-neutral-defect-pair` 的任务输入合同。已经完成的任务进入 `neutral-formation` 后，可选择不传 chemical point：

```text
mlcc neutral-formation --host-task <host-task> --defect-task <defect-task> \
  --descriptor <defect-model.json> --output <report.json>
```

省略 `--chemical-point` 时，`neutral_formation_from_tasks()` 仍先读取两个真实且完成的原生任务，并执行同方法、能量定义、输入/结果同胞、模型谱系、元素/赝势集合和 `deltaN` 校验。通过后返回 `status=raw_neutral_energy_only`、`scientific_status=raw_neutral_energy_unqualified`，其中 `Ehost_eV`、`Edefect_eV`、`raw_energy_difference_eV=Edefect_eV-Ehost_eV`、`deltaN`、`source_tasks` 和 `source_jobs`（host/defect 的原生 Slurm job ID）可用；`raw_formation_energy_eV`、`corrected_formation_energy_eV` 为 `null`，`production_qualification` 和 `size_convergence_qualified` 为 `false`。原生运行日志、调度终态、退出码和共同校验状态保存在 `evidence` 中。

空 JSON 对象 `{}` 仍表示一个不完整的 chemical point，会在完整 host/defect 校验之后因缺少 `mu_eV_per_atom` 被拒绝；它不等同于省略参数。非零 `charge_state` 仍在读取任务前返回 `blocked_current_charge_adapter`，不会被缺失 chemical point 路径放行。传入完整 chemical point 时，原有形成能计算和未资格状态保持不变。

创建前检查：

1. 读取两个模型，验证周期性、cell/PBC 相同；验证 defect 的 `explicit_defect_sequence`、`charge_state=0`、`production_qualified=false`、parent 模型身份和绝对路径、父/子计量以及 `composition_delta`。
2. 读取两个 study 和两个 request，验证模型绑定、SCF 阶段、任务 ID、资源对象和已有目标目录。上述共同前置错误在调用创建器前抛出；各资源字段的详细检查仍由既有创建器负责。
3. 读取 method/site/chemical point，复用 `check_method_configuration()`（若 method 声明 input qualification）核对两套模型；检查μ为有限值、方法身份及占据对应的能量定义一致，并保存来源路径。

所有前置检查通过后，函数直接调用现有 `create_abacus_task()` 两次，写入最终 `tasks/<task_id>` 目录。若第二次出现意外的文件或方法错误，保留第一项原始任务和原始异常，不增加事务清理或自动重试。该操作只写输入，不自动 transfer、submit 或 collect。

返回对象的 `schema` 为 `mlcc.neutral-defect-task-pair.v1`，状态为 `tasks_defined_not_submitted`，并包含：

- `host_task`、`defect_task`：两个 `task.json` 的绝对路径；
- `descriptor_path`：派生 descriptor 来源；
- `source_method`、`source_site`、`chemical_reference`：重现任务所需的配置来源；
- `lineage`：父子计量、`composition_delta`、同胞和中性声明；
- `postprocessing.adapter`：`mlcc.defect_thermodynamics.neutral_formation_from_tasks`；
- `postprocessing.formation_energy_written=false`：两个任务完成并通过原生解析前不写形成能数值。

可选 `output_path` 会把同一份 pair manifest 写入一个新文件；不覆盖已有文件。

CLI：`mlcc create-neutral-defect-pair --host-model ... --defect-model ... --host-study ... --defect-study ... --method ... --site ... --host-request ... --defect-request ... --chemical-reference ... --output ...`。该命令也属于数值输入生成，只在v100 Slurm作业内执行。

## 已有函数的复用边界

| 目标 | 复用函数 | 本切片新增内容 |
| --- | --- | --- |
| 读取并校验模型 | `modeling.read_model_artifacts` | 检查父模型、同胞、计量和 charge_state |
| 生成 ABACUS 输入 | `abacus_tasks.create_abacus_task` | 先对 host/defect 两个 request 做共同预检，并为两次调用提供相同 method/site |
| 形成能后处理 | `defect_thermodynamics.neutral_formation_from_tasks` | 只保存其调用所需的 task/descriptor/chemical-reference 路径，不复制其原生结果校验 |
| 派生模型 | `model_derivatives.derive_defect_model` | 不自动调用；由用户或上游任务显式提供 defect 模型 |

## 证据和未完成事项

`mlcc-agent/tests/test_defect_tasks.py` 的正向用例调用真实 `create_abacus_task()`，只检查 `INPUT`/`STRU` 等输入文件和未提交状态；负例只检查领域前置错误。测试不制造能量、不会替代 v100 数值验收。真正的验收仍需在 v100 通过 Slurm：使用选定材料的真实 host/defect 任务，保留 native job ID/终态，运行现有 ABACUS parser 后，再调用 `neutral_formation_from_tasks()`。在没有 chemical point 的参数传递验收中，只能接受 `raw_neutral_energy_only` 及其原生来源；传入 chemical point 后，形成能结果仍保持 `raw_neutral_formation_unqualified`，尚不包含尺寸收敛、弛豫、带电超胞、VBM/势对齐或 FNV/eFNV 修正资格。

2026-10-22 v100 Slurm **job64 COMPLETED/0:0**，1秒/5分钟预算、2CPU/4GiB，4项测试通过。正例经实际CLI生成输入，另检查非SCF、非零电荷及化学势能量定义冲突；保留生成输入和原生终态于 [job64](../workspace/reports/neutral-defect-pair-v001/job-64/tests.txt)。该输入正例没有提交DFT，测试μ不是材料参考值。真实缺陷计算与形成能验收仍未完成。

本文件和本切片不改变启用版本，不构成 0.13.0 发布或生产材料势资格。
