# v100 Slurm 安装与调度验收

执行日期：2026-10-20，Asia/Shanghai。通过现有 LAN SSH 别名 v100，目标 v100@192.168.110.35:22。用户在可见 SSH 终端输入 sudo 密码，密码未进入项目文件或聊天。

## 已安装与配置

Ubuntu 24.04.4 LTS。安装前只有 slurm-client/basic-plugins 23.11.4 和已运行的 MUNGE；/etc/slurm 存在但没有配置，slurmctld/slurmd 未安装。

本次从现有 Ubuntu 源增加 slurmctld、slurmd，版本 23.11.4-1.2ubuntu5；没有执行系统升级、autoremove、显卡驱动更新或重启，也没有重建 MUNGE 密钥。

| 项目 | 当前配置 |
| --- | --- |
| 集群/节点 | mlcc-v100 / v100 |
| 主机 | v100-System-Product-Name，192.168.110.35 |
| 分区 | cpu（默认）、gpu；同一物理节点，资源统一分配 |
| CPU | Ryzen 7 5700X：1 socket、8 核、每核 2 线程，16 个逻辑 CPU |
| 内存 | Slurm 配置 27800 MiB，物理检测约 31977 MiB，保留系统余量 |
| GPU | gpu:v100:4，显式 /dev/nvidia0–3 |
| 资源选择 | select/cons_tres，CR_Core_Memory |
| 约束 | cgroup v2；核、内存及设备访问限制 |
| 优先级 | priority/basic，适用于本次无数据库基础配置 |
| 自动重排 | JobRequeue=0；后续 MLCC 模板另显式 --no-requeue |
| 服务 | munge、slurmctld、slurmd 均 active、enabled |
| 完成记录 | 控制器近期状态保留 86400 秒，并写 jobcomp/filetxt |

配置文件在 /etc/slurm/slurm.conf、gres.conf、cgroup.conf；控制器状态在 /var/lib/slurm/slurmctld，节点 spool 在 /var/lib/slurm/slurmd。管理日志在 /var/log/slurm。

原配置备份：/var/backups/mlcc-slurm/20261020-152850/slurm。优先级修正前配置另存 /var/backups/mlcc-slurm/slurm.conf.before-priority-fix。目录和配置已实际存在，不是待执行占位路径。

GPU 采用手工 GRES，因为当前 Ubuntu basic-plugins 不带 NVML GPU 自动发现插件；这不妨碍本次设备分配和隔离，但不意味着具备 GPU 利用率/显存 TRES 自动记账。[GRES 说明](https://slurm.schedmd.com/gres.html)

## 真实验收

以下作业均已用 scontrol 核实 COMPLETED、ExitCode=0:0，不只是成功提交或看到了 nvidia-smi。

| 作业 | 验收内容 | 证据 |
| --- | --- | --- |
| 2 | 两个 CPU task 执行确定性计算 | affinity 分别 [0,8] 与 [1,9]，均得到 333332833333500000 |
| 3_0–3_3 | 四个并发单 GPU 作业 | 四个作业分别执行 CUDA kernel 并核对 1048576 个返回值，每个只见一张卡 |
| 9 | 一个 allocation 中四 task、每 task 一 GPU | 四个 task 各自 CUDA 计算通过，PCI bus ID 各不相同 |
| 10 | 四卡作业运行期间提交的额外单卡任务 | 15:33:33 提交、15:34:20 启动，正常结束；未捕获明确 Resources 原因，不将短暂 PENDING(None) 说成完整资源竞争证明 |
| 11 | 设备 cgroup 隔离 | 申请一张卡，删除 CUDA_VISIBLE_DEVICES 后仍只见一张 GPU，CUDA 计算通过 |

实际覆盖的 PCI bus ID：0000:0C:00.0、0000:0D:00.0、0000:10:00.0、0000:11:00.0。实时 nvidia-smi 进程/UUID 映射核实四个 CUDA 进程各在不同物理卡上。最后队列为空、节点 IDLE，未残留测试 GPU 进程。

CPU 核分配使用 --hint=nomultithread，避免两个 task 被放在同一物理核的两个 SMT 线程上。CR_Core_Memory 下申请一个物理核可显示占用两个逻辑 CPU，这是当前拓扑和资源策略，不是超额执行。

隔离验收使用实际 CUDA 运行，不以环境变量或 nvidia-smi 是否列出其他卡作为唯一结论。[cgroup v2 设备机制](https://slurm.schedmd.com/cgroup_v2.html)

## 过程中修正的实际问题

1. 未设置配置时客户端错误使用 DNS 查询控制器；现在明确 SlurmctldHost/NodeAddr，客户端查询正常。
2. 无数据库模式下默认 priority/multifactor 产生 InvalidAccount 调度告警；改为 priority/basic 后复测通过，没有伪造账号或凭据。
3. 四卡初测作业 7 因 srun 参数冲突失败：批作业导出了 CPU 的 SLURM_TRES_PER_TASK，再在 srun 中重复设置 --gpus-per-task 触发 23.11 的互斥检查。现在在 sbatch 定义 --gpus-per-task=v100:1，srun 只做 GPU binding；复测作业 9 成功。原失败记录保留，没有自动重试。
4. 调试阶段的额外排队作业 8 被明确 scancel；未取消其他用户作业。
5. CUDA 12.3 nvcc 不支持系统默认 GCC 的较新版本；使用现有 NVHPC nvc++ 编译测试，不强行绕过编译器版本检查、不另装工具链。采用 noexecstack 链接设置。

## 源码、日志与复现

服务器验收根：/home/v100/mlcc-slurm-setup。

- install.log：安装过程。
- install-complete.txt、priority-fix-complete.txt：阶段完成时间。
- cpu-2.out、gpu-3_0.out 至 gpu-3_3.out、four-gpu-9.out、cgroup-11.out：实际测试结果。
- validation-snapshot.txt：最终控制器、作业、节点与服务快照；本地副本在 docs/slurm-evidence/。

本地脚本在 scripts/admin/。安装与修正脚本用于这次已核实环境的部署，不是通用、自动恢复或可对活动集群盲目重复运行的安装器。不要在有生产作业时重新执行。

CUDA 测试编译命令：

~~~bash
cd /home/v100/mlcc-slurm-setup
/opt/nvidia/hpc_sdk/Linux_x86_64/24.1/compilers/bin/nvc++ -cuda -gpu=cc70 -O2 -Wl,-z,noexecstack slurm-gpu-smoke.cu -o slurm-gpu-smoke
~~~

常用检查：

~~~bash
ssh v100
scontrol ping
sinfo -N -l
squeue -u v100
scontrol show job <真实作业号>
~~~

新测试使用本地最新版 sbatch 模板。首次 CPU/GPU 测试是在全局禁用 requeue 前提交，历史 job 记录的 Requeue=1、Restarts=0 如实保留；目前新作业默认 Requeue=0。

## 尚未完成，不能误报

- 未安装 SlurmDBD/MariaDB 持久作业数据库，sacct 不可作为现有完成态查询链。近期状态由 scontrol 查询，项目执行器需要落盘终态；完整使用 ACS worker 前须解决其 sacct 依赖。
- 未验证 MPI 作业。启动日志显示 PMIx 插件找不到所需库；当前 CPU/CUDA 测试均显式 --mpi=none，不能据此声称 NVHPC MPI/PMIx 可用。
- 尚未运行 VASP、ABACUS 或 LAMMPS 科学任务；本次 GPU kernel 测试不等于 VASP 四卡计算通过。
- MLCC Slurm 提交/查询/取消/收集适配器、MatterAI MCP 装载、授权 POTCAR 路径仍是后续任务。
- 无 NVML GPU 利用率/显存自动记账，不把当前未记录指标填成零。

后续优先级：已装 Slurm → 验证/修复 PMIx 与 VASP 所用 NVHPC MPI → 明确授权 POTCAR 与小 fixture → sbatch 单卡 VASP SCF/弛豫 → 四卡同几何对照 → MLCC 调度适配器与结果交接 → ABACUS 迁移。

本次未添加文件摘要校验、自动引擎回退、自动作业重提或防御性兼容框架；MUNGE 与系统包本身的安全认证保持不变。
