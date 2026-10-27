# ABACUS → DeePMD → LAMMPS 独立开发与接入执行书

日期：2026-10-22。任务来源：用户要求先单独开发训练接口，再接入 MLCC，并尽量利用多个 GPU。此文是当前专项执行入口，实际状态在文末更新。既有 MLCC 发布版本和其他开发窗口的模块不由本专项改写。

## 1. 交付边界

先交付 `standalone/deepmd_bridge` 中可直接调用的 Python 领域函数和命令行，依次完成原生数据集、训练与冻结、模型交付、同模型 LAMMPS 接口验收。数值作业只在 v100 的 Slurm 中执行；沿用已有任务/调度器，不引入常驻服务、自动重试、缓存或引擎替代。科学文件、权重和日志保存在 workspace，代码和合同才可进入后续 Bundle。

独立工程门通过之后，才把入口接入正在开发的 MLCC 候选版；已启用版与回退版按版本保留规则管理。材料资格独立保留 `not_qualified`，`design_assessment=not_assessed`。少量真实构型训练只证明链路，不证明 CaZrO3、BaTiO3、缺陷、界面或铁电生产精度。

## 2. 工作包与执行顺序

| 工作包 | 具体执行 | 产物与验收 | 依赖 |
| --- | --- | --- | --- |
| DP-00 环境合同 | 读取 v100 GPU/驱动/Slurm/现有包；选固定 DeePMD/PT/CUDA 与匹配 C++/LAMMPS，不改已有引擎环境 | 版本、路径、原生 help/加载日志；GPU 与 runtime 分开实证 | 无 |
| DP-01 数据 | 复用已有原生 ABACUS E/F/stress；核对 INPUT、KPT、方法/赝势、收敛、胞和原子映射；显式 train/validation/test 来源组 | deepmd/npy、type_map、逐帧来源与拒绝记录；回读及原生数值比较 | 已有真实标注 |
| DP-02 训练 | 小型平滑描述符/拟合网络，显式精度、seed、步数、损失权重、局部/全局 batch；Slurm 内 PT DDP | input.json、脚本、job ID、rank/GPU证据、lcurve、checkpoint；失败保留原始错误 | DP-00/01 |
| DP-03 模型交付 | 显式冻结 PT 模型，记录版本、backend、格式、type_map、来源集、训练参数和科学状态 | 冻结模型、模型卡、Python E/F/完整 virial | DP-02 |
| DP-04 LAMMPS | 匹配 runtime/plugin；units metal；固定原子类型顺序；同几何静态 run0，记录真实 device/rank | 原生输入/log/dump；同冻结模型 Python↔LAMMPS E/F/virial 一致；完整应力旋转与单位转换 | DP-03 |
| DP-05 多卡 | 单卡基线、2卡DDP、4卡DDP；同模型设置与显式batch策略；记录启动/训练时间和资源 | 每rank设备、每步耗时/样本吞吐和加速比；峰值内存留待生产规模测量，不能只据卡数声称加速 | DP-02 |
| DP-06 系统接入 | 审查独立门；接入已有任务创建/提交/查询/收集/下游势读取，沿用7个MCP生命周期工具 | 候选版公共入口端到端及失败消费门证据；另走版本验收，不能覆盖冻结版 | DP-01–05 |

DP-00/01 和训练脚本实现并行；已有 DFT 不重跑。未找到同方法、原生收敛、完整标签的足够数据时，记录局部缺口；不混合 k点/赝势/电荷/引擎来凑数。只有确实缺少改变路径的必要数据时才另立最小 DFT 协议，所有实际 DFT `time=0`。

## 3. 数据与模型合同

- 一份数据集绑定一个 ABACUS 方法合同；逐帧列出 native task/job、模型版本、原生文件、电子/离子收敛依据、元素及稳定 atom_id。方法资格未完成不阻塞工程转换，但不能写成生产训练集。
- deepmd/npy 使用 Å、eV、eV/Å、eV virial；type_map 顺序显式给定。ABACUS 压应力为正时 `virial = stress[kbar] × volume[Å³] / 1602.1766208`；若消费既有张应力正 GPa，则 `virial = -stress[GPa] × volume / 160.21766208`。代码须以实际原生定义和回读验证，不能只照文本赋值。
- 按母轨迹/加载路径分组切分，不将同一来源组相邻帧随机分入训练和验证。数据不足时只报工程拟合；不捏造独立测试集。
- 模型卡保存 backend/模型格式、DeePMD/PT/CUDA版本、type_map、训练输入、checkpoint、冻结产物、数据清单、资源和科学资格；文件路径使用可读版本，不使用摘要缓存。
- 普通 E/F/virial 势不默认携带极化、外场、电极屏蔽、介电或电致应变能力。

## 4. 多 GPU 策略和预算

优先单节点 PT DistributedDataParallel，一进程一卡，Slurm分配设备，torchrun启动。初始工程协议为 1→2→4 GPU，固定小型模型与有限步数，显式限制 CPU、内存和训练时长。全局 batch 与每rank batch 的关系写入报告，避免把多卡每步更多样本误称同工作量加速。

4×16 GiB不是一块64 GiB显存，DDP每卡保存模型副本。主机约31 GiB RAM也约束4进程，数据加载worker起步为0，线程按CPU预算分配。2卡通过后才开4卡；若资源/依赖失败，保留原错误与恢复条件，不静默改成单卡成功。小数据通信开销可能使多卡更慢，实际生产卡数按实测吞吐选择。

初始范围：复用已有标签，短训练/冻结与静态run0；不启动材料参数搜索、长MD、主动学习或新DFT采样。科学误差不过线按事实记录，不为了通过工程交付反复调参。

## 5. 接口验收与失败行为

工程验收至少检查：真实Slurm job与终态、GPU rank映射、原生输入/输出、标签单位与符号、完整E/F/virial、同一几何与原子顺序、冻结模型一致性、下游文件绑定。缺标签、混方法、未收敛源、type_map错误、backend不符、训练失败、冻结缺失和LAMMPS失败均须给出真实失败，不能生成成功模型卡或生产可用状态。

跨接口初始数值容差（float64）：总能 1e-6 eV、力最大分量 1e-6 eV/Å、virial最大分量 1e-5 eV。容差针对同一模型的两个实现，不是材料DFT精度门限。报告保留每项实际误差；如原生输出精度不足，应修正输出精度，不能放宽门限掩盖问题。

## 6. 官方实现依据

- [DeePMD 3.2.0 并行训练](https://docs.deepmodeling.com/projects/deepmd/en/v3.2.0/train/parallel-training.html)：PT DDP和torchrun一进程一卡启动。
- [DeePMD 3.2.0 安装](https://docs.deepmodeling.com/projects/deepmd/en/v3.2.0/install/easy-install.html)：训练包、LAMMPS extra和后端依赖；本站实际版本由job118及训练日志复核。
- [DeePMD 3.2.0 LAMMPS接口](https://docs.deepmodeling.com/projects/deepmd/en/v3.2.0/third-party/lammps-command.html)：plugin、pair_style、元素映射和单位。

## 7. 当前执行状态

独立工程链和源码适配的公共训练→LAMMPS链均已通过。代码及复用命令见 [README](../standalone/deepmd_bridge/README.md)，机器可读总证据见 [acceptance.json](../workspace/reports/deepmd-bridge-v001/acceptance.json)。本次未发布/激活 MatterAI Bundle，材料生产资格保持未完成。

| 交付 | 原生作业及实证 | 结论 |
| --- | --- | --- |
| DP-00 | job118；固定 `/home/v100/dpa4/releases/3.2.0`，DeePMD3.2.0、Torch2.11.0+cu126、LAMMPS22Jul2025Update2、MPICH5.0.1 | runtime及插件路径已实证；114缺MPI库失败、115手动取消的历史保留 |
| DP-01 | job122；复用ABACUS job32 SCF、33 relax的两帧同100Ry方法；原生回读/单位/映射检查 | deepmd/npy与逐帧来源完成；无新DFT，无独立validation |
| DP-02/03 | job124单卡、125双卡、129公共四卡，均100步+freeze | `.pth`、checkpoint、loss和模型卡齐全；实际rank/GPU日志保留 |
| DP-04 | job126独立双卡训练模型→单GPU LAMMPS/Python；job132公共四卡训练模型→单GPU LAMMPS，133对照解析 | 同冻结模型E/F/完整virial一致；公共parser返回evaluated_candidate_potential |
| DP-05 | job124/125/129逐步增加GPU，固定每rank batch=1 | 多GPU工程通过；吞吐/启动开销及重复采样限制见下表 |
| DP-06 | create-task→既有prepare/transfer/submit/query/collect→finalize-task登记模型卡→既有LAMMPS任务创建/解析；最终交付检查job135 | 源码适配完成；沿用现有7个MCP生命周期工具，无新调度器或Bundle激活 |

job130 在v100/Slurm完成41项数据/训练/交付/runner检查，原始 [JUnit](../workspace/reports/deepmd-bridge-v001/handoff-tests-130.xml) 与 [stdout](../workspace/reports/deepmd-bridge-v001/handoff-130.out)保留。失败门覆盖未收敛源、方法差异、atom map缺失、混引擎、非有限loss、不足步数、冻结缺失及错误调度状态。真实四卡公共任务见 [task.json](../workspace/tasks/p9-deepmd-public-4gpu-v001/task.json)，下游见 [task.json](../workspace/tasks/p9-deepmd-lammps-public-v001/task.json)。

最终审查补齐作业目录、input/数据split、batch、checkpoint和冻结模型的交付绑定，并新增 `finalize-task`，在原TaskRecord登记model-card和收集路径。job135为1秒CPU软件检查/已有产物后处理，**57项通过**，见[最终JUnit](../workspace/reports/deepmd-bridge-v001/finalize-tests-135.xml)和[日志](../workspace/reports/deepmd-bridge-v001/finalize-135.out)。原始计划以training_plan保留planned状态，模型卡execution_status另存实际completed/freeze，PT/CUDA等版本附原生日志；没有改写原始训练记录。模型卡已由既有SiteRunner完成[收集](../workspace/reports/deepmd-bridge-v001/public-final-collect.json)。前次job134因测试样例漏填planned字段而失败，保留[错误日志](../workspace/reports/deepmd-bridge-v001/finalize-134.out)；修正样例后显式提交135，无自动重试、无重复训练。

### 实测多卡结果

| GPU / job | 每rank / 全局batch | 去掉前10步的秒/步 | 样本暴露量/秒 | 相对单卡吞吐 | Slurm总运行时间 |
| --- | --- | --- | --- | --- | --- |
| 1 / 124 | 1 / 1 | 0.0119 | 84.03 | 1.00× | 12秒 |
| 2 / 125 | 1 / 2 | 0.0149 | 134.23 | 1.60× | 12秒 |
| 4 / 129 | 1 / 4 | 0.0172 | 232.56 | 2.77× | 13秒 |

四卡实际分配8CPU/24GiB主机内存，单卡2CPU/12GiB，双卡4CPU/12GiB；均有限15分钟非DFT预算。四卡日志显示rank0–3、cudaDev0–3，使用NCCL；两帧数据会填充重复采样。以上不是同训练工作量/同精度的加速比，也不是独立材料测试。总时间受启动和冻结影响，没有缩短；峰值显存尚未测量，不为此追加训练。真实生产任务建立足够数据后，再依据实测吞吐和内存选择2/4卡。

### 公共模型同接口误差

job129模型在job132/133中的总能差为0，力最大分量差为1.7404e-17 eV/Å，完整virial最大分量差为1.8985e-8 eV，均在第5节容差内。详见 [interface-acceptance.json](../workspace/tasks/p9-deepmd-lammps-public-v001/interface-acceptance.json)。job133为8秒的后处理/核验作业；未训练新模型、未重新计算ABACUS。

### 后续接入边界

当前交付是独立源码包0.1.0及现有系统的源码适配，不是新启用的软件release。后续发布由主系统按当时的候选版本、MatterAI Bundle合同和保留政策打包验收；不能把本专项的Ni模型当作用户确认材料或生产资格。普通E/F/virial模型没有被赋予铁电极化或外场能力。本轮不继续Ni参数优化、CZO应力归因或新DFT采样。
