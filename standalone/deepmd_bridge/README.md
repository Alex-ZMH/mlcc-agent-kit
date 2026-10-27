# ABACUS → DeePMD → LAMMPS 独立接口 0.1.0

2026-10-22 已完成独立工程验收，并通过源码适配接入既有 MLCC TaskRecord / SiteRunner / LAMMPS 创建与解析流程。四卡公共训练 job129、下游 LAMMPS job132、同模型核验 job133 均为 `COMPLETED/0:0`。本次未激活或替换已发布的 MatterAI Bundle。

完整计划和执行记录见[专项执行书](../../docs/abacus-deepmd-lammps-execution-20261022.md)，机器可读证据见[acceptance.json](../../workspace/reports/deepmd-bridge-v001/acceptance.json)。本组件依赖现有 `mlcc-agent/src` 的原生解析和任务合同；独立交付源码、实验目录及验收，复用已有引擎解析器与调度器。

## 已实现的接口

| 模块 | 输入 → 输出 | 必要边界 |
| --- | --- | --- |
| `dataset.convert_to_deepmd` | 显式 ABACUS 来源 → deepmd/npy、dataset_manifest.json | 重读原生输出；核对方法、收敛、标签、胞和原子映射 |
| `training.DeepMDTrainingConfig` / `write_sbatch_script` | 训练与资源配置 → torchrun/DDP Slurm 脚本、清单 | 单节点 1/2/4 GPU；保存局部/全局 batch 与重复采样情况 |
| `handoff.collect_training` | 指定产物、数据清单、真实调度终态 → model-card.json | 训练/冻结完成、loss 有限、步数足够、`.pth` 存在 |
| `inference` | 同一冻结模型和几何 → Python/LAMMPS E/F/virial 比较 | 复用 LAMMPS 解析、原子映射及应力旋转 |
| `integration.create_training_task` | 独立接口验收、训练请求 → MLCC TaskRecord | 复用 prepare/transfer/submit/query/collect；数据已在声明的远端位置 |

数据坐标/胞用 Å、能量用 eV、力用 eV/Å、virial 用 eV。ABACUS 原生压应力为正，对应 `virial = stress_GPa × volume_A3 / 160.21766208`；已有 LAMMPS parser 返回张应力正，反算 virial 时取负号。一个数据清单要求同一原子布局和方法合同，train/validation 按来源组分离；不同组成或原子数须另建数据系统，当前入口拒绝混入同一清单。

## 运行与复用

Python 3.12；控制/转换环境需 numpy、ase 和 MLCC 源码；训练及模型推理需匹配的 DeePMD/PT/CUDA 与 LAMMPS plugin。本站已实证使用 `/home/v100/dpa4/releases/3.2.0`，没有修改共享环境。站点路径和资源在 [deepmd-runtime-v001.json](../../workspace/configs/deepmd-runtime-v001.json) 与 [site.v100-deepmd-v001.json](../../workspace/configs/site.v100-deepmd-v001.json) 中。

数据转换、模型计算、科学后处理和验收测试均在 v100 的 Slurm 中执行。本机只生成请求、传输、提交、查询和查看证据。`scripts/deepmd-runtime` 是本次工程实验的运行记录，含固定实验路径/job ID；复用时显式新建版本和配置，不覆盖已有证据。

1. 显式列出 ABACUS 来源及 source_group/split。本次实际[来源清单](../../workspace/reports/deepmd-bridge-v001/engineering-v001/source-manifest.json)使用 job32/33 的两帧同方法数据。Slurm 内执行 `python -m mlcc_deepmd dataset MANIFEST OUTPUT`，参考 [prepare-engineering.sbatch](../../scripts/deepmd-runtime/prepare-engineering.sbatch)。[静态示例](examples/abacus_ni_engineering_sources.json)仅列其中单帧。
2. 声明 native input.json 和 DeepMDTrainingConfig；`python -m mlcc_deepmd training-plan CONFIG` 生成脚本，实际通过 sbatch 提交。当前验收 PT se_e2_a、float64、100步、每rank batch=1。使用 `torchrun --standalone --nnodes 1 --nproc-per-node N --no-python dp --pt train input.json`，随后冻结为 frozen_model.pth。
3. 读取真实 scontrol 终态，在 Slurm 内调用 `collect_training(workdir, dataset_manifest, scheduler_record)`，scheduler_record 包含 job_id/state/exit_code/workdir。参考 [collect_engineering.py](../../scripts/deepmd-runtime/collect_engineering.py)。模型卡绑定来源、参数、资源、训练job和冻结文件；科学状态仍为 not_qualified。
4. 在 GPU Slurm 内执行 interface-prepare、LAMMPS run0、interface-evaluate、interface-compare，见 [interface-engineering.sbatch](../../scripts/deepmd-runtime/interface-engineering.sbatch)。同模型容差：能量1e-6 eV、力1e-6 eV/Å、virial 1e-5 eV。
5. 独立门通过后使用 `python -m mlcc_deepmd create-task REQUEST`。新任务须修改 task_id、remote workdir、输入/数据路径；现有验收任务不可重建覆盖。[实际四卡请求](../../workspace/configs/deepmd-public-4gpu-request-v001.json)可供检查。NPY已在同站点，适配器传输元数据与脚本，不隐式同步外部数据集。

下面只查询和收集已完成任务，不会再启动训练：

```powershell
$env:PYTHONPATH = 'D:/project/mlcc/standalone/deepmd_bridge/src;D:/project/mlcc/mlcc-agent/src'
$dpPython = 'D:/project/mlcc/workspace/.venv/Scripts/python.exe'
$dpTask = 'D:/project/mlcc/workspace/tasks/p9-deepmd-public-4gpu-v001/task.json'
$dpSite = 'D:/project/mlcc/workspace/configs/site.v100-deepmd-v001.json'
& $dpPython -m mlcc.cli query --task $dpTask --site $dpSite
& $dpPython -m mlcc.cli collect --task $dpTask --site $dpSite
```

新任务生命周期顺序为 `create-task → mlcc.cli prepare → transfer → submit → query → collect`。公共模型交付随后在Slurm内调用 `python -m mlcc_deepmd finalize-task TASK_JSON SCHEDULER_RECORD_JSON`，把模型卡登记回原TaskRecord并加入collect_paths；同步更新的task.json后再用既有collect获取模型卡。参考 [finalize_public_training.py](../../scripts/deepmd-runtime/finalize_public_training.py)。原training-manifest保存提交计划，模型卡另存实际执行状态与原生版本日志。下游复用已有 mlcc.lammps_tasks.create_lammps_task，参考 [prepare_public_lammps.py](../../scripts/deepmd-runtime/prepare_public_lammps.py)。本轮核心仅增加 SiteRunner 对显式 Slurm account 的传递。

## 验收结论与限制

- 最终57项数据/训练/交付/runner检查在 Slurm job135 通过，新增错绑拒绝与TaskRecord模型卡登记检查；job124/125/129 分别完成单/双/四GPU训练与冻结。
- 公共四卡模型的 Python↔LAMMPS 比较：能量差0，力最大差1.74e-17 eV/Å，virial最大差1.90e-8 eV。
- 单/双/四卡每秒样本暴露量84.03 / 134.23 / 232.56，四卡约2.77倍；总作业耗时12 / 12 / 13秒。两帧数据在四卡有填充重复，不能推断生产训练同等加速。未测峰值显存；生产资源须按选定数据和模型测量。
- 本轮只有两帧Ni工程数据，无独立验证集，无新DFT、长MD或材料参数搜索。冻结模型未取得目标材料生产资格；该状态不阻塞已完成的系统接口交付。
