# 显式自训练势用户路线接入 v001

日期：2026-10-24。范围：在已有陶瓷训练/模型卡/LAMMPS公共创建器之上，接通Agent与MD Skill的用户显式选择。主系统0.33冻结、0.34候选；本专项不启用Bundle。

## 文件所有权与集成边界

- 本聊天：`mlcc-agent/agents/mlcc/AGENT.md`、`mlcc-agent/skills/run-mlcc-md/SKILL.md`中的自训练路由段；新增 `src/mlcc/ceramic_potential_route.py`、`tests/test_ceramic_potential_route.py`；本专项脚本、配置、报告和本文。
- 主线/实施窗口：`cli.py`、`dielectric_response.py`、`property_delivery.py`、Gamma、原生method/NAO/KPT读取和0.34整体发布。此专项不覆盖上述文件。
- 复用：`ceramic_training`的bind/create/finalize、`ceramic_md`的单system创建/解析、standalone bridge以及原七MCP/Slurm runner。无新训练框架、runner、来源框架或多system MD fan-out。

## 最薄运行入口

`python -m mlcc.ceramic_potential_route --request REQUEST_JSON`。

请求沿用既有 `create-ceramic-training` / `create-ceramic-lammps` JSON，仅增加 `potential_route="abacus_deepmd"` 和 `operation="create_training"|"create_lammps"`。入口记录显式选择及请求路径，调用原创建器，不提交。MACE/已有势继续原 `create-lammps --potential`；缺包、缺文件或领域错误保留原错误，不换路线。

创建后按现有生命周期执行；新训练真的完成才调用 `finalize-ceramic-training`，已有模型卡直接复用。LAMMPS完成后继续 `parse-ceramic-lammps`。本轮验收仅创建未提交任务，不执行这些后续数值步骤。

## 依赖核对

当前源码0.34已有 `ceramic = ["mlcc-deepmd-bridge==0.1.0"]`；本地已启用0.33环境已安装bridge，不按历史未安装文档判断缺包。v100 analysis环境可以通过明确PYTHONPATH加载候选mlcc与bridge；发行版metadata可能仍为共享环境旧版本，验收分别记录源码与环境身份。固定DeePMD3.2.0/PT2.11.0+cu126/LAMMPS插件证据复用，无安装或模型加载。

## 预先声明的验收预算

只申请一个CPU分区Slurm软件/输入生成作业：1节点、1 task、1CPU（hint=nomultithread）、4GiB、5分钟、0GPU、no-requeue。测试仅新路由选择、参数传递和原错误传播；真实验收复用ABACUS50/121、collection141、训练模型146以及公共166/安装175的既有证据，创建一个训练TaskRecord和一个host20 LAMMPS TaskRecord。两任务均必须无新scheduler_job_id，不提交、不训练、不DFT/PYATB、不执行LAMMPS、不重解析旧MD，不做完整宿主回归。

输入写入独立 `self-trained-potential-route-v001` workspace。主线继续SCF/极化和读取修复，本专项不触碰其作业与候选安装目录。计划和实际验收证据将一起交回主线，整体Bundle发布归主线。

## 当前状态

**独立接入已实现并通过最小验收，交主线单独评审集成。** Slurm job423 `COMPLETED/0:0`，运行2秒。请求1CPU/4GiB/5分钟/0GPU，本站SMT调度记录实际分配2 logical CPUs；Requeue=0、Restarts=0。起初PENDING曾显示InvalidAccount，随后backfill正常运行，没有取消或重新提交。

新增4项控制路由检查通过，包含缺失/未知路线与operation、训练和单system LAMMPS的参数传递、原错误传播、创建器状态保留和显式选择事件。真实入口另外生成两份未提交任务：

| 操作 | 新task_id | 状态 / job | 真实绑定 |
| --- | --- | --- | --- |
| create_training | route-training-unsubmitted-v001 | created / null | 原input和collection不变，source jobs50/121，4GPU资源和DDP world_size=4已写入；未训练 |
| create_lammps | route-host20-unsubmitted-v001 | defined / null | 训练job146模型卡、host20、原Study与20个atom_id；Ca/Zr/O、metal/atomic、原protocol及model.data保持一致；未运行LAMMPS |

证据：[总验收](../workspace/reports/self-trained-potential-route-v001/acceptance.json)、[调度终态](../workspace/reports/self-trained-potential-route-v001/scheduler-423.txt)、[新路由测试](../workspace/reports/self-trained-potential-route-v001/route-tests.txt)、[训练请求](../workspace/reports/self-trained-potential-route-v001/training-route-request.json)、[LAMMPS请求](../workspace/reports/self-trained-potential-route-v001/lammps-route-request.json)。复制到本地的未提交任务位于报告的 `created-tasks`；原生路径与旧job仅作为来源，未改写旧任务。

主代理审查修正了初版适配器对status/scientific_status的多余覆盖；最终入口只附加potential_route及event，继续由原创建器拥有执行与科学状态。复核补全了Skill中的可执行CLI前缀，明确资源填入由调用方遵循已有配置合同、源码绑定与发行版安装分开；没有因此扩大测试或重复提交423。

## 主线接收清单

集成仅涉及文首四个源码/能力定义路径，打包于 [route-integration-files-v001.tar.gz](../workspace/reports/self-trained-potential-route-v001/route-integration-files-v001.tar.gz)，机器交接见[handoff.json](../workspace/reports/self-trained-potential-route-v001/handoff.json)。其中Agent/Skill按本专项新增路由段评审；不要用验收用 `source-snapshot.tar.gz` 整体覆盖主线0.34候选。主线的公共CLI、介电/Γ/结果交付、版本、registry和安装目录未被本专项修改。

本次以显式PYTHONPATH验收隔离源码，未激活或重装发行版，也未做完整宿主验收。新增模块已被当前setuptools包发现规则覆盖，不需新增console script、MCP或主CLI分支。主线发布时保留现有ceramic extra及实际bridge绑定即可；是否并入哪一接受版由主线决定。

验收复用旧PW工程来源50/121和模型146，不混入当前SCF11/Born/Γ标签，不接管其作业。本次没有新DFT/PYATB、训练、推理或MD。四GPU只验证新请求的参数传递，不新增多卡性能结论。普通E/F/virial势和当前模型仍无极化/介电或材料生产资格。
