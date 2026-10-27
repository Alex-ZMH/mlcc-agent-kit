# 聚合物/有机结构流程移植清单（MLCC）

日期：2026-10-22。状态：只读审查后的移植设计清单，不表示任何移植项已经完成。

本清单覆盖“聚合物结构准备 → 初始装箱 → 参数化交接 → 热化/平衡/生产 → LAMMPS 任务谱系”以及两个参考树中的有机结构输入辅助。通用 MD 轨迹后处理、统计估计和聚合物链段统计由 [MD 后处理、统计与聚合清单](md-postprocessing-statistics-porting-list.md) 维护，这里只定义与其交接的输入和谱系，不重复实现。两个上游目录仍是只读参考，科学计算、真实后处理和验收只允许在 v100 上通过 Slurm 执行。

为避免同名目录造成歧义，本文中 Photoresist 路径均相对于 `Photoresist-agent-kit-main/Photoresist-agent-kit-main/bundles/arf-car-computation/`，ACS 路径均相对于 `Autonomous_Computational_Scientist-main/Autonomous_Computational_Scientist-main/`。

## 先判断能否移植

Photoresist 的实际聚合物路线是：显式的重复单元/端基/保护状态和链统计 → `polymer_chain_ensemble.v1` 符号记录 → RadonPy 0.2.11 原子链 → PACKMOL 初始几何 → GAFF2/Gasteiger 参数化与 LAMMPS data 回读 → 固定拓扑 MD。它明确把装箱定义为“未平衡初始几何”，把 MMFF 只用于碰撞修复，把参数覆盖与势资格分开，也把失败的链和副本留在证据中。

ACS 的 `organic-modeling` 只有有限分子/有机片段入口：SMILES 的 ETKDGv3 加 MMFF/UFF、X-ray 短 X–H 键修正，以及将非周期 XYZ 装入真空盒。它没有聚合物链统计、拓扑参数化或合格势证明，不能作为陶瓷、金属或铁电势的来源。

当前 MLCC 的 LAMMPS 适配器仍是周期晶体 `atomic`/`metal` 合同：`export_lammps_data` 写入元素类型和 `atom-map.json`，`_validate_potential` 当前只接受 `fixture=true`，在资格报告通过前拒绝 `production_qualification=true`，`validate_lammps_protocol` 只开放 `run0`、NVE/NVT 与 `units metal`（见 `mlcc-agent/src/mlcc/lammps.py:97-188,324-414`）。这是当前状态门，不是永久禁止；选定模型的资格报告通过后，才按其适用域开放明确的生产合同。因此不能把 RadonPy/GAFF2 的有机 data 文件直接当作 MLCC 合格势，也不能把当前 Ni 工程 job45/47 当作聚合物资格证据。现阶段没有 MLCC 聚合物模型、参数包、界面势或生产 MD 证据。

## 逐项移植清单

表中“验收证据”先列参考树已有的可核对测试，再列 MLCC 当前状态；参考树测试不能计作 MLCC 验收。“一次性生产协议产物”是未来某个用户明确选定的聚合物/界面案例只跑一次的最小产物，不应预先开展温度矩阵或重复验证。

| ID / 优先级 | 上游真实函数（相对路径与行号）及能力 | MLCC 最小修改与目标文件 | 现有证据及缺口 | 一次性真实生产协议与交付物 | 依赖/边界 |
| --- | --- | --- | --- | --- | --- |
| **POL-01 输入与有限链统计（P1）** | Photoresist `mcp-servers/arf_core.py:1474-1651` `sample_polymer_statistics`；`skills/polymer-structure-preparation/scripts/prepare_polymer_ensemble.py:194-272` `_prepare_statistical_ensemble`、`:275-511` `prepare_polymer_ensemble`。校验 Schulz–Zimm 有界 MWD、重复单元分数、保护状态、端基、tacticity 标签和独立随机流，先保存符号链再调用构造器。 | 新增窄接口 `mlcc-agent/src/mlcc/polymer_tasks.py`（或等价领域模块），复用 `tasks.TaskRecord` 保存 `study_id/case_id/polymer_id/repeat_unit/end_group/DP/MWD/seed`；不把 MWD 写成实验分布，不将 tacticity 标签升级为原子级事实。科学数据放 `workspace/`，Bundle 只放入口。 | 参考测试：`tests/test_polymer_statistical_skill.py:28-110,130-183` 和 `test_md_workflow_lifecycle.py:169-187,262-273`。MLCC 没有聚合物统计函数或生产证据。 | 用户先给出一种明确的中性聚合物和有限链协议；v100 Slurm 生成一次符号链。交付 `polymer_chain_ensemble.json`、`sampling_record.json`、`task.json`、失败时的 `construction_failure.json`，并逐项复算 `DP/Mn/Mw/分散度/组成`。 | 必须先确定化学结构、端基和状态；不得由模型猜聚合物、保护比例或相。若只是晶体/金属案例，本项保持未启用。 |
| **POL-02 原子链构造与原子映射（P1）** | `mcp-servers/arf_modeling_v2.py:1017-1103` `build_atomistic_polymer_ensemble`；`RadonPy0211Backend.build_linear_chain` `mcp-servers/arf_modeling_v2.py:1350-1496`。每条链一次调用、固定 seed、重复单元/端基/位点/原子注释和键图回读，不重采样。 | 在 `polymer_tasks.py` 保存 `source_symbolic_ref`、稳定 `atom_id`、`repeat_unit_id/site_index/end_group_id` 和图边；若要进入界面，扩展 `mlcc-agent/src/mlcc/modeling.py` 的模型来源记录，但不要把非周期链强行塞进当前 `ModelArtifacts` 晶体合同。 | 参考测试：`test_real_polymer_structure.py:18-28`、`test_polymer_geometry_guard.py:47-117`、`test_polymer_geometry_relaxation.py:40-171`。MLCC 只有周期晶体 `ModelArtifacts`，无链图和端基回读证据。 | 在 v100 用同一声明的有限链构造一次；交付原子/键图、原子映射、构造器版本、seed、输入符号记录和成功/失败链列表。报告必须证明序列、端基和原子顺序未变，不能报告“全局最低能量”。 | RadonPy 只负责有机链的候选几何；不提供陶瓷/金属/界面势，不证明 tacticity/CIP。支持 GPU 的后端优先 GPU；RDKit/RadonPy 预处理若后端本身不支持 GPU，可在 v100 通过 Slurm 使用明确、合理的 CPU 预算正式执行，不把它降级为本地兼容性测试。Berry 的 CPU 兼容性例外另行管理。 |
| **POL-03 初始几何粗 QC（P1）** | `mcp-servers/arf_modeling_v2.py:1111-1201` `_prepare_initial_geometry`、`:1203-1252` `_require_valid_geometry`。检查有限坐标、重叠和几何异常；上游在碰撞时的一次 MMFF94 自动修复是其内部行为，`iteration_limit` 不是收敛，也不改变图和注释。 | 将“检查”改写为 MLCC 的输入资格门，放入 `polymer_tasks.py` 或 `lammps_tasks.py` 的准备阶段；上游 MMFF94 自动修复不直接沿用，若需要修复，必须由请求显式开启一个独立、可审计的几何准备步骤，并输出 `geometry_qc` 与原始/修复后坐标。禁止把它当 DFT 弛豫或 MD 平衡。 | 参考测试：`test_polymer_geometry_relaxation.py:65-129`、`test_polymer_geometry_guard.py:53-117`。MLCC 当前只检查晶体/势输入，未有链几何 QC。 | 一次构造协议额外提交粗 QC 报告：坐标有限、零重叠、最短键/重原子距离、图与注释保持；若显式请求 MMFF 准备，则只执行该声明的一次准备阶段；失败保留原始记录，不自动换构象、重试或重跑。 | 仅是进入装箱的必要门；不产生势资格、密度、平衡或介电结论。 |
| **POL-04 初始装箱与链谱系（P1）** | `skills/resist-mixture-packing/scripts/pack_resist_initial_ensemble.py:145-178` `_resolve_skill_wrapper`、`:206-226` `_component_lineages`、`:275-630` `pack_resist_initial_ensemble`。解析注册结构、保留选中链、展开 component/copy、验证电荷闭合、为每个 seed 生成 PACKMOL 几何，并把 `component_lineage` 传给下游；明确输出是未平衡初始几何。 | 新增 `polymer_tasks.py` 的可选 Packmol 适配，或在 `lammps_tasks.py:create_lammps_task` 前增加窄的 `initial_geometry_ref`；保存晶体/金属/聚合物各自来源、链/原子映射、盒、seed、copy 数。不得把 PACKMOL 结果直接当陶瓷致密度、界面结合或平衡膜。 | 参考测试：`test_packing_import.py:21-122`、`test_packing_skill_wrapper.py:34-131`、`test_packing_chemical_state.py:11-96`。MLCC 当前没有 PACKMOL 或多组分链装箱证据。 | 只有当用户明确选择界面/复合体系时执行一次；交付每个副本的输入、Packmol 原生输出、组件/链谱系、原子数/最短距离 QC 和失败副本索引。副本数由目标 observable 的协议决定，不机械搬用“三 seed”默认值。 | 需要 POL-01~03 和明确的晶体相/界面组成；不允许丢弃聚合物、反离子或界面组分来让装箱成功。 |
| **POL-05 有机参数化与引擎布局回读（P0 资格门）** | `mcp-servers/arf_radonpy_runtime.py:472-555` `bind_and_verify_engine_layout`；`:827-922` `parameterize_explicit_neutral_radonpy_pilot`；`:952-1065` `_expanded_formulation`；`:1068-1181` `parameterize_packed_ensemble`。显式中性原子/键图 → RadonPy 0.2.11 GAFF2/Gasteiger → LAMMPS data，再按字段读取并绑定 packed 坐标/实体 ID。 | 仅实现“适配器和资格合同”，不直接把 GAFF2 标成 MLCC 生产势。若选定的有机模型需要进入 LAMMPS，扩展 `mlcc-agent/src/mlcc/lammps.py` 的拓扑、电荷和 `atom_style` 合同，以及 `lammps_tasks.py` 的参数包引用；实际使用 `molecular`、`full`（含 `q`）或其他样式必须由该 data 文件和资格报告明确验证，不能假定 GAFF2 拓扑必然是不含电荷的 `molecular`。保留现有 `fixture=true` 拒绝门，新增 `potential_qualification` 记录；资格报告通过后才按选定域开放生产。跨陶瓷/金属的交互项必须由 P9 DFT 锚点和材料势工作包提供。 | 参考测试：`test_arf_radonpy_runtime.py:364-460,514-707`、`test_arf_parameterization_v2.py:14-60`。MLCC `_validate_potential`（`lammps.py:324-370`）当前明确拒绝生产资格，尚无聚合物参数包或交互势证据。 | 用户选定一种中性链和一种明确的 CZO/BTO 或金属界面后，只做一次参数化资格任务：交付原子/键/角/二面角语义、每副本 data、参数覆盖、实际 `atom_style`/电荷字段回读、布局坐标回读、方法/版本/许可证、失败原因。生产通过还必须有同一构型上的 DFT–势能/力对照和界面锚点；缺任一项则 `production_qualification=false`。 | GAFF2/Gasteiger 只描述有机候选，不能填补陶瓷势、铁电场自由度或界面交互项。禁止把 neutral-only 路由扩展成带电周期缺陷路线。 |
| **POL-06 任务阶段、停止点与失败保留（P1）** | `mcp-servers/arf_md_tasks.py:256-350` `MDTasks._validate_request/create`；`:416-479` `_verify_completed_preparation/_reuse_source`；`:958-1104` `advance`；`:1107-1114` `_analysis_context`。阶段为 validate→structures→packing→parameterization→simulation→analysis，可在阶段停止、复用已提交任务、保留中断/失败证据。 | 复用 `mlcc-agent/src/mlcc/tasks.py:21-91` 的 TaskRecord/event 和 `mlcc-agent/src/mlcc/workflow.py:145-232,587-653` 的来源检查；新增 polymer 阶段只允许显式 `depends_on`、真实 Slurm job ID 和终态，禁止自动重试、换引擎、改 seed 或把历史结果改成新条件。 | 参考测试：`test_md_workflow_lifecycle.py:37-69,151-229`、`test_md_tasks.py` 与 `test_parameterization_failure_handoff.py`。MLCC 已有普通任务/Slurm 续接，但没有 polymer stage 或失败交接证据。 | 一次性真实协议须留下 `task.json`、每阶段事件、`scheduler_job_id`、原生终态、输入/输出引用、失败或完成报告；重复查询只读，不重新提交。 | 该项是所有后续聚合物任务的公共门，不能因“已有 LAMMPS job”跳过。 |
| **POL-07 结构来源与有机输入辅助（P2，按需）** | ACS `src/vasp_agent/skills/organic-modeling/scripts/build_from_smiles.py:21-91` `main`（ETKDGv3 + MMFF/UFF + XYZ/POSCAR/CIF）；`normalize_hydrogens.py:28-54` `_normalize`（只调整 X–H）；`src/vasp_agent/main.py:2017-2040` `_load_structure_boxing_molecules`（XYZ 真空盒）。 | 仅作为 `polymer_tasks.py` 的有机端基/小分子输入预处理；必须显式记录 SMILES、seed、力场、真空层和修改前后坐标。不得对 CZO/BTO 晶体重建重原子、猜相或替换 ABACUS/VASP 方法；真空盒不是周期陶瓷胞。 | 参考测试：ACS `tests/test_organic_modeling.py:29-89`、`tests/test_molecule_boxing.py:10-30`。MLCC 没有该辅助入口，也没有有机输入生产证据。 | 若用户确实提供聚合物端基/有机粘结剂结构，交付一次输入审查报告和可消费结构文件；报告列出 X–H 修正、最短重原子距离及周期/非周期状态。RDKit 预处理若不支持 GPU，可在 v100 上通过 Slurm 以明确 CPU 预算正式执行；支持 GPU 的后续数值后端仍优先使用 GPU。 | 低优先级；不能阻塞 CZO/BTO 晶体缺陷、铁电介电或材料势资格。ACS 的 MMFF/UFF 不是 MLCC 势。 |
| **POL-08 明确拒绝与资格报告（P0）** | Photoresist `mcp-servers/arf_radonpy_runtime.py:133-182` `_validate_expected_semantics`、`:185-215` `_validate_request` 对字段、GAFF2 风格、`units real`、中性和显式拓扑做硬门；`mcp-servers/arf_modeling_v2.py:1017-1103` `build_atomistic_polymer_ensemble`（其中 `:1023-1027` 的合同明确禁止重采样/替换后端）。 | 在 `mlcc-agent/src/mlcc/lammps.py`、`lammps_tasks.py`、`workflow.py` 中把“结构可生成、参数覆盖、势适用域、生产资格”分成四个状态；对未知元素、带电体系、缺交互项、拓扑不完整或未做 DFT 对照直接返回可读拒绝。当前 `fixture=true` 拒绝是资格报告通过前的状态；报告通过后，只对报告声明的元素/拓扑/相/温度/加载域开放生产，不保留无条件的永久拒绝。 | 参考测试覆盖版本不符、带电/错序、readback 漂移；MLCC 当前 fixture 资格拒绝门已有，但没有聚合物具体 reason code。 | 每次一次性协议必须同时交付 `capability.json`/资格报告，列出 `qualified=false/true`、适用元素/相/温度/加载范围、原生 job ID 和未满足条件；不得以源代码单测代替。 | 该项保证主要投入继续放在晶体缺陷、铁电介电和材料势资格；聚合物没有真实资格时保持“不可消费”，不拖慢主线。 |
| **POL-09 热化→平衡→生产阶段（P0，固定拓扑）** | Photoresist `mcp-servers/arf_md_conditions.py:30-75` `normalize_settings`、`:78-98` `compile_settings`（显式阶段条件与步数编译，但含场景默认值）；`mcp-servers/arf_backends_v2.py:668-699` `_force_field_commands`（`units real`、`atom_style full`、周期盒、GAFF2 1–4 与长程库仑命令）、`:702-723` `_equilibration_gate_lines`（NPT 样本和阶段标记）、`:776-939` `render_fixed_topology_ensemble`（最小化、NVT warm-up、NVT/NPT 平衡、独立生产段和原生输出）；`:1260-1324` `validate_equilibration_gate`、`:1151-1259` `validate_diffusion_protocol_evidence`、`:1386-1429` `_scan_preparation_diagnostics` 只做阶段完整性/数值诊断。`_apply_fixed_topology_stability_profile` `:726-775` 会自动插入 NVT 和修改 NPT 阻尼，`arf_lammps_ensemble_driver.py:156-225` `build_numerical_recovery_input` 与 `:269-421` `run_ensemble` 会自动恢复/重试；后两类行为不可直接移植。 | 新增 MLCC 的显式 `md_conditions`/阶段编译合同，接入 `mlcc-agent/src/mlcc/lammps.py` 与 `lammps_tasks.py`：由请求明确给出最小化、热化、平衡（NVT 或 NPT）、生产系综、温度、压力、时间步、阻尼、采样/轨迹间隔和固定拓扑/电荷语义；输入生成器只渲染声明的阶段，不从场景或力场自动补默认值，不自动插入额外 NVT、改变阻尼、换构象或重试。阶段诊断仅发布原生样本与 `equilibration_gate`，通过后才允许生产结果进入 MD-00/01 collection；该固定拓扑有机力场路线不支持断键/化学反应，也未取得铁电翻转、缺陷电荷转变的模型资格；不将这些能力从阶段模板外推。 | 参考测试：`tests/test_md_run_settings.py:15-75`、`tests/test_md_stage_diagnostics.py:30-123`、`tests/test_arf_backends_v2.py:475-522`。MLCC 当前仅有基本 `run0`/NVE/NVT 合同和工程 job45/47；没有热化/平衡/生产阶段脚本、完整阶段证据或资格结果。 | 用户先声明目标 observable 和阶段规模；同一协议生成一次可复现的阶段输入和 Slurm job。交付每阶段原生输入、日志/轨迹、`ARF` 等价的明确阶段标记或 MLCC 标记、平衡样本诊断、生产 collection、native job ID/终态。平衡门失败时只保留诊断和失败阶段，不启动或发布生产；不自动恢复、重试或扩大窗口。链数、平衡/生产时长和样本数由目标与有限尺寸/独立性要求确定，不能用参考树默认的 20/100/500 ps 或三副本替代用户协议。 | 依赖 POL-01~08、MD-00/01 以及已通过的有机/界面势资格；仅适用于固定拓扑有机/界面模型。需要 GAFF2 电荷时按 POL-05 的实际 `atom_style full`/电荷字段合同；不把该阶段模板用于 CZO/BTO 铁电、晶体缺陷或相变动力学。 |

## 一次性生产协议的最低验收定义

当且仅当用户明确提供聚合物化学身份、端基/电荷、目标 MLCC 界面和需要的 observable，才开一个 bounded study。生产协议的链数、盒尺寸、界面胞大小、独立副本数、平衡/生产长度和采样间隔必须由目标 observable、有限尺寸误差与独立性要求共同确定；一条小链或一个小胞不能自动被视为生产协议。POL-01～POL-09 应尽量共用同一份已声明协议、原始输出和资格证据，避免为每个移植项重复提交或重复验收。计算和数值验收在 v100 Slurm 执行，支持 GPU 的数值后端优先 GPU；RDKit/RadonPy 等本身不支持 GPU 的预处理可在 v100 通过 Slurm 按合理、明确的 CPU 预算正式执行。Berry GPU 故障所需的小规模 CPU 兼容性预算是单独例外，不能套用为本流程的总规则。

验收目录至少包含：

1. `task.json`、请求/方法/站点配置、每阶段事件、原生 Slurm job ID 和实际终态；
2. 符号链、原子/键图、`atom-map.json`、装箱输入与原生输出（若启用）；
3. 参数覆盖、引擎语义/坐标回读、适用域和 DFT–势对照（若申请生产资格）；
4. 一份资格报告，分别写明 `execution_status`、`geometry_qc`、`parameterization_status`、`potential_qualification` 和 `design_assessment`。没有用户规格时，设计结论必须是 `not_assessed`；正常性能通过也不要求先制造劣化情形。

该协议通过后，才能把 `parameterized_replica_id` 交给 MLCC 的 MD 任务；通过前只可交付诊断或准备结果。任何失败、副本缺失、方法不兼容或物理资格缺口都保留原始证据，不通过反复重跑来凑生产结论。

## 不移植的内容

- 不移植 Photoresist 的光化学、PEB、酸/碱、PAG、扩散/显影和工艺模型。
- 不把 RadonPy、GAFF2、Gasteiger、MMFF/UFF 或 PACKMOL 当作 CZO/BTO 晶体、铁电极化、介电张量或陶瓷/金属合格势。
- 不把其固定拓扑 MD 当作断键、极化翻转、缺陷电荷转变或连续介质/相场求解器。
- 不复制其 dispatcher/常驻 worker、自动重试/修复或内容缓存策略；MLCC 继续使用现有 TaskRecord、SiteRunner 和 Slurm 合同。
- 不在本清单中重复通用 MD 后处理、轨迹统计、聚合物链段 MSD/RDF/Tg 等清单；这些能力由 [MD 后处理、统计与聚合清单](md-postprocessing-statistics-porting-list.md) 维护，并须在已通过势资格和采样协议后另行接入。

## 与当前主线的关系

聚合物流程是 P9–P11 界面/粘结剂分支的条件能力，排在晶体缺陷形成能/化学势/费米能级/带电超胞修正、P5 铁电/介电和 P9 材料势资格之后。CZO 与 BTO 仍是晶体验证案例；本清单不选择 BTO 相、不推导烧制温度矩阵，也不因聚合物路径尚未实现而降低主线验收标准。


