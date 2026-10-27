# H0 实际执行台账：Slurm jobs 12–31

> 2026-10-21 范围更正：下文 2026-10-20 的桌面 trust 调查是历史记录，仅适用于 Electron 宿主。将其作为整个 H0 的必需入口是错误的，已撤销“等待用户提供桌面路径”；当前剩余项为非桌面宿主 MCP 接入。见 [运行入口核查](matterai-runtime-scope.md)。原始执行事实不变。

本台账整理已经发生的真实作业，不新增计算。采集来源是本地保存的
`workspace/tasks/**/task.json`、对应 `job.sbatch`、stdout/stderr、Slurm
快照和 `workspace/reports/h0/`。作业均通过 `ssh v100` 进入远端目录后由
`sbatch` 提交，数值命令在 Slurm allocation 内运行；本次整理没有重装
Bundle、没有重新提交作业，也没有更新 `plans/` 或 `PLAN.md`。

## Jobs 12–20

表中的“作业文件”是本地证据路径；远端 Slurm 快照中的同名路径为
`/home/v100/projects/mlcc/tasks/<task>/job.sbatch`。`ExitCode` 保留
Slurm 的原始 `major:minor` 表示。

| Job ID | 作业 / 作业文件 | 提交与执行命令 | 资源与实测状态 | 产物、数值与失败原因 |
|---:|---|---|---|---|
| 12 | `h0-mpi-one-v001` / [`job.sbatch`](../workspace/tasks/h0-mpi-one-v001/job.sbatch) | 远端目录执行 `sbatch --parsable job.sbatch`，保存返回 `12`；脚本执行 `/opt/nvidia/hpc_sdk/Linux_x86_64/24.1/comm_libs/12.3/hpcx/hpcx-2.17.1/ompi/bin/mpirun --map-by slot --bind-to core --report-bindings /home/v100/projects/mlcc/bin/mpi_cuda_reduction` | `gpu`, 1 task / 1 V100，`RunTime=00:00:02`；`COMPLETED`, `0:0` | host/device reduction 均为 `1`，`visible_gpus=1`，PCI `0000:0C:00.0`。证据：[`task.json`](../workspace/tasks/h0-mpi-one-v001/task.json)、[`mpi-one-terminal.txt`](../workspace/reports/h0/mpi-one-terminal.txt)、[`mpi-one-submission.txt`](../workspace/reports/h0/mpi-one-submission.txt)、stdout/stderr。 |
| 13 | `h0-mpi-four-v001` / [`job.sbatch`](../workspace/tasks/h0-mpi-four-v001/job.sbatch) | 远端目录执行 `sbatch --parsable job.sbatch`，保存返回 `13`；执行命令同 Job 12 | `gpu`, 4 tasks / 每 rank 1 V100，`RunTime=00:00:01`；`COMPLETED`, `0:0` | 四个 rank 的 host/device reduction 均为 `10`；PCI 为 `0C:00.0`, `0D:00.0`, `10:00.0`, `11:00.0`，CPU affinity 为 `0,8`, `1,9`, `2,10`, `3,11`。证据：[`task.json`](../workspace/tasks/h0-mpi-four-v001/task.json)、[`mpi-four-check.txt`](../workspace/reports/h0/mpi-four-check.txt)。 |
| 14 | `h0-runner-echo-v001` / [`job.sbatch`](../workspace/tasks/h0-runner-echo-v001/job.sbatch) | `ssh v100 "cd /home/v100/projects/mlcc/tasks/h0-runner-echo-v001 && sbatch --parsable job.sbatch"`；脚本执行 `/usr/bin/python3 -c ...`，将 `SLURM_JOB_ID` 写入 `receipt.json` | `cpu`, 1 task，`RunTime=00:00:00`；`COMPLETED`, `0:0` | [`receipt.json`](../workspace/tasks/h0-runner-echo-v001/receipt.json) 和 stdout 都记录 `job_id=14`、`MLCC LAN Slurm roundtrip`；stderr 为空。 |
| 15 | `h0-runner-failure-v001` / [`job.sbatch`](../workspace/tasks/h0-runner-failure-v001/job.sbatch) | `ssh v100 "cd /home/v100/projects/mlcc/tasks/h0-runner-failure-v001 && sbatch --parsable job.sbatch"`；脚本执行 `/usr/bin/python3 -c "...; sys.exit(7)"` | `cpu`, 1 task，`RunTime=00:00:00`；`FAILED`, `7:0` | 这是有意的 runner 错误夹具；stderr 原文为 `MLCC controlled failure: requested exit 7`。没有科学产物。 |
| 16 | `h0-runner-cancel-v001` / [`job.sbatch`](../workspace/tasks/h0-runner-cancel-v001/job.sbatch) | `ssh v100 "cd /home/v100/projects/mlcc/tasks/h0-runner-cancel-v001 && sbatch --parsable job.sbatch"`；脚本执行 Python `time.sleep(120)`；随后记录的取消命令为 `ssh v100 "scancel 16"` | `cpu`, 1 task，`RunTime=00:01:49`；`CANCELLED`, `0:15` | stdout 为 `MLCC cancellation fixture started`；stderr 为 `JOB 16 ... CANCELLED`。取消和终态查询均在 [`task.json`](../workspace/tasks/h0-runner-cancel-v001/task.json) 的 `events` 中保留。 |
| 17 | `h0-ni-single-v001` / [`job.sbatch`](../workspace/tasks/h0-ni-single-v001/job.sbatch) | `ssh v100 "cd /home/v100/projects/mlcc/tasks/h0-ni-single-v001 && sbatch --parsable job.sbatch"`；脚本执行 `/bin/bash run-vasp.sh` | `gpu`, 1 task / 1 V100，`RunTime=00:00:03`；`FAILED`, `127:0` | **QD 动态链接失败。** VASP 原文为 `/opt/vasp/vasp_std: symbol lookup error: ... undefined symbol: qdmodule_qd_real__td_`，MPI 随后以 `127` 退出。无科学结果。证据：[`task.json`](../workspace/tasks/h0-ni-single-v001/task.json)、[`vasp-single-failure-17.txt`](../workspace/reports/h0/vasp-single-failure-17.txt)、本地 stdout/stderr。 |
| 18 | `h0-ni-single-v002` / [`job.sbatch`](../workspace/tasks/h0-ni-single-v002/job.sbatch) | `ssh v100 "cd /home/v100/projects/mlcc/tasks/h0-ni-single-v002 && sbatch --parsable job.sbatch"`；脚本执行 `/bin/bash run-vasp.sh` | `gpu`, 1 task / 1 V100，`RunTime=00:00:04`；`FAILED`, `1:0` | **CRLF/POSCAR 输入失败。** VASP 6.5.1 已启动并检测到 1 GPU，但原文为 `ERROR: there must be 1 or 3 items on line 2 of POSCAR`；[`vasp-poscar-failure-18.txt`](../workspace/reports/h0/vasp-poscar-failure-18.txt) 保留了含 `\r\n` 的 hexdump。无科学结果。 |
| 19 | `h0-ni-single-v003` / [`job.sbatch`](../workspace/tasks/h0-ni-single-v003/job.sbatch) | 前置 `scp` 在传输 `KPOINTS` 时返回 `255`（`Connection closed by 192.168.110.35 port 22`）；随后仍执行 `ssh v100 "cd /home/v100/projects/mlcc/tasks/h0-ni-single-v003 && sbatch --parsable job.sbatch"`，Slurm 返回 `19` | `gpu`, 1 task / 1 V100，`RunTime=00:00:00`；`FAILED`, `127:0` | **部分传输后误提交。** `task.json` 的 `control_error` 和 `events` 同时记录 `KPOINTS` 未成功传输、`sbatch` 返回 0/Job 19，以及终态 `NonZeroExitCode/127:0`。没有科学结果；[`partial-transfer-job19-cancel.txt`](../workspace/reports/h0/partial-transfer-job19-cancel.txt) 保存终态快照。 |
| 20 | `h0-ni-single-v004` / [`job.sbatch`](../workspace/tasks/h0-ni-single-v004/job.sbatch) | `ssh v100 "cd /home/v100/projects/mlcc/tasks/h0-ni-single-v004 && sbatch --parsable job.sbatch"`；脚本执行 `/bin/bash run-vasp.sh` | `gpu`, 1 task / 1 V100，`RunTime=00:07:29`；**最终 `COMPLETED`, `0:0`** | VASP 6.5.1 GPU offload 启动；电子收敛标记为 `electronic_converged=true`，SCF `e_0_energy=-21.87619034 eV`，`e_fr_energy=-21.87778308 eV`，最大力 `0.2723990400645483 eV/Å`。`ionic_converged=null`，因此这只是 Ni 工程 fixture 的 SCF 收敛，不能当作弛豫收敛或生产材料结果。证据：[`task.json`](../workspace/tasks/h0-ni-single-v004/task.json)、[`result.json`](../workspace/tasks/h0-ni-single-v004/result.json)、[`vasp-single-v004-runtime.txt`](../workspace/reports/h0/vasp-single-v004-runtime.txt)、stdout/stderr、`OUTCAR`/`vasprun.xml`/`CONTCAR`。 |

### 终态汇总

- MPI/CUDA 工程通信：Jobs 12、13 均通过，分别验证单 rank/单卡和四 rank/四卡的 host/device reduction 及 PCI 映射。
- runner 语义夹具：Job 14 通过；Job 15 保留显式退出 7；Job 16 保留 `scancel` 后的 `0:15` 取消语义。
- VASP 接线：Job 17 的 QD 运行库符号错误、Job 18 的 CRLF/POSCAR 错误和 Job 19 的部分传输后误提交均为真实失败；Job 20 是首个完成的 Ni 工程 fixture SCF。Job 20 没有执行离子弛豫，也没有产生生产 DFT/训练标签。
- 这组证据不改变 P4 的引擎迁移要求：生产 DFT 和训练标注仍须显式改用本机实际可用的 ABACUS，并保持引擎原始标签分离。

## Jobs 21–27：Ni 工程 fixture 批次与科学门槛

以下记录来自各任务的 `task.json`、实际 `INCAR`/`method.json`、`job.sbatch`、Slurm 查询快照和 `result.json`。Jobs 21–26 均通过 `ssh v100` 在远端目录执行 `sbatch --parsable job.sbatch`，终态为 Slurm `COMPLETED`、`ExitCode=0:0`，并已收集原始 VASP 产物。它们实际使用 `ni-paw-pbe52-spin-engineering-v002`（400 eV 的并行/弛豫/应变任务，500 eV 的 cutoff 任务）；后续人工复核产生的 `workspace/configs/h0-vasp-method-v003.json` 不应回写为这些历史作业的方法版本。

| Job ID | 作业、实际方法与提交命令 | 资源、Slurm 状态与退出 | 结果和证据 |
|---:|---|---|---|
| 21 | `h0-ni-four-v004`（400 eV，v002，SCF）；`ssh v100 cd /home/v100/projects/mlcc/tasks/h0-ni-four-v004 && sbatch --parsable job.sbatch`，脚本执行 `/bin/bash run-vasp.sh`。证据：[`task.json`](../workspace/tasks/h0-ni-four-v004/task.json)、[`job.sbatch`](../workspace/tasks/h0-ni-four-v004/job.sbatch) | `gpu`，4 tasks/4 V100，`AllocTRES=cpu=8,mem=8G,node=1,billing=8`，`NodeList=v100`，`RunTime=00:01:57`；`COMPLETED`, `0:0` | 电子收敛；`e_0_energy=-21.87619034 eV`，最大力 `0.2723990400647662 eV/Å`，拉伸正应力 trace `3.189772651 GPa`。原始结果：[`result.json`](../workspace/tasks/h0-ni-four-v004/result.json)。 |
| 22 | `h0-ni-relax-v004`（400 eV，v002，fixed-cell ionic relax）；`ssh v100 cd /home/v100/projects/mlcc/tasks/h0-ni-relax-v004 && sbatch --parsable job.sbatch`，脚本执行 `/bin/bash run-vasp.sh`。证据：[`task.json`](../workspace/tasks/h0-ni-relax-v004/task.json)、[`job.sbatch`](../workspace/tasks/h0-ni-relax-v004/job.sbatch) | `gpu`，4 tasks/4 V100，`AllocTRES=cpu=8,mem=8G,node=1,billing=8`，`NodeList=v100`，`RunTime=00:05:31`；`COMPLETED`, `0:0` | 电子与离子均收敛；`e_0_energy=-21.88027912 eV`，最大力 `0.0014218965491553878 eV/Å`，应力 trace `3.340024621 GPa`。`CONTCAR` 是后续任务的结构来源；原始结果：[`result.json`](../workspace/tasks/h0-ni-relax-v004/result.json)。 |
| 23 | `h0-ni-post-relax-v004`（400 eV，v002，relax→SCF）；依赖 Job 22，`ssh v100 cd /home/v100/projects/mlcc/tasks/h0-ni-post-relax-v004 && sbatch --parsable job.sbatch`，脚本执行 `/bin/bash run-vasp.sh`。证据：[`task.json`](../workspace/tasks/h0-ni-post-relax-v004/task.json)、[`job.sbatch`](../workspace/tasks/h0-ni-post-relax-v004/job.sbatch) | `gpu`，4 tasks/4 V100，`AllocTRES=cpu=8,mem=8G,node=1,billing=8`，`NodeList=v100`，`RunTime=00:01:47`；`COMPLETED`, `0:0` | SCF 电子收敛；`e_0_energy=-21.88027883 eV`，最大力 `0.001205599121142679 eV/Å`，应力 trace `3.334093510 GPa`。输入 POSCAR 来自 Job 22 `CONTCAR`；原始结果：[`result.json`](../workspace/tasks/h0-ni-post-relax-v004/result.json)，谱系核对：[`relax-lineage.json`](../workspace/reports/h0/relax-lineage.json)。 |
| 24 | `h0-ni-cutoff500-v004`（500 eV，v002，SCF）；`ssh v100 cd /home/v100/projects/mlcc/tasks/h0-ni-cutoff500-v004 && sbatch --parsable job.sbatch`，脚本执行 `/bin/bash run-vasp.sh`。证据：[`task.json`](../workspace/tasks/h0-ni-cutoff500-v004/task.json)、[`job.sbatch`](../workspace/tasks/h0-ni-cutoff500-v004/job.sbatch) | `gpu`，4 tasks/4 V100，`AllocTRES=cpu=8,mem=8G,node=1,billing=8`，`NodeList=v100`，`RunTime=00:01:57`；`COMPLETED`, `0:0` | 电子收敛；`e_0_energy=-21.87209711 eV`，最大力 `0.27259512000028707 eV/Å`，应力 trace `1.362698599 GPa`。原始结果：[`result.json`](../workspace/tasks/h0-ni-cutoff500-v004/result.json)。 |
| 25 | `h0-ni-strainminus-v004`（400 eV，v002，负应变 SCF）；`ssh v100 cd /home/v100/projects/mlcc/tasks/h0-ni-strainminus-v004 && sbatch --parsable job.sbatch`，脚本执行 `/bin/bash run-vasp.sh`。证据：[`task.json`](../workspace/tasks/h0-ni-strainminus-v004/task.json)、[`job.sbatch`](../workspace/tasks/h0-ni-strainminus-v004/job.sbatch) | `gpu`，4 tasks/4 V100，`AllocTRES=cpu=8,mem=8G,node=1,billing=8`，`NodeList=v100`，`RunTime=00:01:56`；`COMPLETED`, `0:0` | 电子收敛；`e_0_energy=-21.87215190 eV`，最大力 `0.28816947005637583 eV/Å`，应力 trace `-5.916619513 GPa`。原始结果：[`result.json`](../workspace/tasks/h0-ni-strainminus-v004/result.json)。 |
| 26 | `h0-ni-strainplus-v004`（400 eV，v002，正应变 SCF）；`ssh v100 cd /home/v100/projects/mlcc/tasks/h0-ni-strainplus-v004 && sbatch --parsable job.sbatch`，脚本执行 `/bin/bash run-vasp.sh`。证据：[`task.json`](../workspace/tasks/h0-ni-strainplus-v004/task.json)、[`job.sbatch`](../workspace/tasks/h0-ni-strainplus-v004/job.sbatch) | `gpu`，4 tasks/4 V100，`AllocTRES=cpu=8,mem=8G,node=1,billing=8`，`NodeList=v100`，`RunTime=00:01:53`；`COMPLETED`, `0:0` | 电子收敛；`e_0_energy=-21.86835005 eV`，最大力 `0.25703057006191715 eV/Å`，应力 trace `11.562334646 GPa`。原始结果：[`result.json`](../workspace/tasks/h0-ni-strainplus-v004/result.json)。 |
| 27 | `h0-ni-cutoff600-v005`（600 eV，v003，独立 SCF follow-on）；人工复核后执行 `ssh v100 cd /home/v100/projects/mlcc/tasks/h0-ni-cutoff600-v005 && sbatch --parsable job.sbatch`，提交返回 Job ID `27`。证据：[`task.json`](../workspace/tasks/h0-ni-cutoff600-v005/task.json)、[`job.sbatch`](../workspace/tasks/h0-ni-cutoff600-v005/job.sbatch) | 提交时先记录 `SUBMITTED`，随后查询为 `COMPLETED`；`gpu`、4 tasks/4 V100，`AllocTRES=cpu=8,mem=8G,node=1,billing=8`，`NodeList=v100`，`RunTime=00:01:59`；`ExitCode=0:0` | 电子收敛；`e_0_energy=-21.87103076 eV`，最大力 `0.27258201000148746 eV/Å`，拉伸正应力 trace `1.614648571 GPa`。原始结果：[`result.json`](../workspace/tasks/h0-ni-cutoff600-v005/result.json)。这是人工审查后的独立 600 eV 任务，**不是自动 retry、自动 requeue 或失败任务重跑**；方法和预算依据：[`h0-vasp-method-v003.json`](../workspace/configs/h0-vasp-method-v003.json)。 |

### Jobs 20–26 的科学验收结论

[`vasp-comparison.json`](../workspace/reports/h0/vasp-comparison.json) 的 `production_qualification=false`、`all_predeclared_checks_passed=false`，应保留为当前 H0 结论：

- 单卡 Job 20 与四卡 Job 21 的 400 eV 并行一致性通过；relax→SCF 的 Jobs 22→23 也通过，`ionic_converged=true` 且 relax 最大力 `0.0014218965491553878 eV/Å` 小于预声明 `0.02 eV/Å`。
- 400→500 eV（Jobs 20→24）的能量/原子和力差分别为 `0.0010229725000003853 eV/atom`、`0.0001960800000000429 eV/Å`，但应力差为 **`0.6093898790000002 GPa`，超过预声明 `0.5 GPa`**，该 cutoff 检查为 false。
- 400 eV 有限应变（Jobs 25、20、26）的能量导数 trace 为 `1.249635966802805 GPa`，报告的拉伸正应力 trace 为 `3.189772587 GPa`，绝对差为 **`1.9401366201971952 GPa`，超过预声明 `1.0 GPa`**，该应变检查为 false。
- 因而 Jobs 20–26 只能作为 Ni 工程 fixture 的真实接线/数值对照，不能提升为生产 DFT 或训练标注资格。v003 是针对上述两项失败由人工复核后制定的 600 eV 预算和方法；Job 27 虽已以 `0:0` 完成，但它是独立的 600 eV SCF 证据，未回写为 20–26 的比较报告，也不改变已记录的失败阈值，更不是自动重试。

## Jobs 28–31：v003 500 eV 应变与弛豫→SCF最终批次

Jobs 28–31 使用人工复核后的 `ni-paw-pbe52-spin-engineering-v003`（方法与预算：[`h0-vasp-method-v003.json`](../workspace/configs/h0-vasp-method-v003.json)），均为 Ni 工程 fixture 的真实 VASP 作业。四项均经 `ssh v100` 进入各自远端目录后执行 `sbatch --parsable job.sbatch`，并从远端回传了 `OUTCAR`、`vasprun.xml`、`CONTCAR` 和日志；没有直接 SSH 启动数值进程、自动 retry 或自动 requeue。以下原生字段来自各任务的最终 `scontrol show job` 快照，`ExitCode` 保留 Slurm 的 `major:minor` 原文。

共同资源字段为：`Partition=gpu`，`NumNodes=1`，`NumTasks=4`，`CPUs/Task=1`，`NumCPUs=8`，`ReqTRES=cpu=4,mem=8G,node=1,billing=4`，`AllocTRES=cpu=8,mem=8G,node=1,billing=8`，`TresPerTask=cpu:1,gres/gpu:v100:1`，`NodeList=v100`，`Requeue=0`，`Restarts=0`，`JobState=COMPLETED`，`ExitCode=0:0`。Job 28、29、31 的时间上限为 `00:10:00`，Job 30 为 `00:20:00`。

| Job ID | 作业、提交命令与原生时间字段 | 最终结果与收敛 | 本地原始证据 |
|---:|---|---|---|
| 28 | `h0-ni-strainminus-v005`；`ssh v100 cd /home/v100/projects/mlcc/tasks/h0-ni-strainminus-v005 && sbatch --parsable job.sbatch`；远端目录同上；`StartTime=2026-10-20T17:43:55`，`EndTime=2026-10-20T17:45:52`，`RunTime=00:01:57` | `e_0_energy=-21.86806574 eV`，`e_fr_energy=-21.8694815 eV`，最大力 `0.28846859000070046 eV/Å`；拉伸正应力 trace `-7.7699742050000005 GPa`；`electronic_converged=true`，`ionic_converged=null`；`scientific_status=converged_engineering_fixture` | [`task.json`](../workspace/tasks/h0-ni-strainminus-v005/task.json)、[`job.sbatch`](../workspace/tasks/h0-ni-strainminus-v005/job.sbatch)、[`result.json`](../workspace/tasks/h0-ni-strainminus-v005/result.json)、`OUTCAR`/`vasprun.xml`/`CONTCAR` |
| 29 | `h0-ni-strainplus-v005`；`ssh v100 cd /home/v100/projects/mlcc/tasks/h0-ni-strainplus-v005 && sbatch --parsable job.sbatch`；远端目录同上；`StartTime=2026-10-20T17:46:29`，`EndTime=2026-10-20T17:48:26`，`RunTime=00:01:57` | `e_0_energy=-21.86412944 eV`，`e_fr_energy=-21.86594108 eV`，最大力 `0.2573468800007976 eV/Å`；拉伸正应力 trace `9.791172790000001 GPa`；`electronic_converged=true`，`ionic_converged=null`；`scientific_status=converged_engineering_fixture` | [`task.json`](../workspace/tasks/h0-ni-strainplus-v005/task.json)、[`job.sbatch`](../workspace/tasks/h0-ni-strainplus-v005/job.sbatch)、[`result.json`](../workspace/tasks/h0-ni-strainplus-v005/result.json)、`OUTCAR`/`vasprun.xml`/`CONTCAR` |
| 30 | `h0-ni-relax-v005`；`ssh v100 cd /home/v100/projects/mlcc/tasks/h0-ni-relax-v005 && sbatch --parsable job.sbatch`；远端目录同上；`StartTime=2026-10-20T17:50:39`，`EndTime=2026-10-20T17:56:11`，`RunTime=00:05:32` | fixed-cell relax；`e_0_energy=-21.87618815 eV`，`e_fr_energy=-21.8777768 eV`，最大力 **`0.0028895226325467674 eV/Å`**；拉伸正应力 trace `1.5444335020000002 GPa`；`electronic_converged=true`、`ionic_converged=true`；`scientific_status=converged_engineering_fixture` | [`task.json`](../workspace/tasks/h0-ni-relax-v005/task.json)、[`job.sbatch`](../workspace/tasks/h0-ni-relax-v005/job.sbatch)、[`result.json`](../workspace/tasks/h0-ni-relax-v005/result.json)、`OUTCAR`/`vasprun.xml`/`CONTCAR` |
| 31 | `h0-ni-post-relax-v005`；`ssh v100 cd /home/v100/projects/mlcc/tasks/h0-ni-post-relax-v005 && sbatch --parsable job.sbatch`；远端目录同上；`StartTime=2026-10-20T17:57:35`，`EndTime=2026-10-20T17:59:25`，`RunTime=00:01:50` | post-relax SCF（POSCAR 来自 Job 30 的 `CONTCAR`）；`e_0_energy=-21.87618799 eV`，`e_fr_energy=-21.87777674 eV`，最大力 **`0.0031283026377254487 eV/Å`**；拉伸正应力 trace `1.513398473 GPa`；`electronic_converged=true`、`ionic_converged=null`；`scientific_status=converged_engineering_fixture` | [`task.json`](../workspace/tasks/h0-ni-post-relax-v005/task.json)、[`job.sbatch`](../workspace/tasks/h0-ni-post-relax-v005/job.sbatch)、[`result.json`](../workspace/tasks/h0-ni-post-relax-v005/result.json)、`OUTCAR`/`vasprun.xml`/`CONTCAR` |

### v003 工程验收、真实回传与资源释放

- [`vasp-comparison-v003.json`](../workspace/reports/h0/vasp-comparison-v003.json) 的顶层 `passed=true`。它明确保持 `production_qualification=false`：这里的通过是 Ni 工程 fixture 的预声明工程门槛，不是生产 DFT 或训练标注资格。
- `parallel_400eV`（Jobs 20/21）通过的含义仍限于 400 eV 单卡/四卡并行一致性；前一节保留的 400→500 应力差 `0.6093898790000002 GPa` 和 400 eV 有限应变 trace 误差 `1.9401366201971952 GPa` 失败段不被覆盖。v003 是独立的后续 500 eV 工程比较。
- `cutoff_500_vs_600`（Jobs 24/27）通过：能量差 `0.0002666099999997229 eV/atom`、力差 `0.000013110000000038369 eV/Å`、应力差 `0.08399896999999995 GPa`，均低于报告中的 `0.01`、`0.03`、`0.5 GPa` 阈值。
- `stress_sign_finite_strain_500`（Jobs 24/28/29）通过：有限应变导数 trace `1.3005803411156924 GPa` 与报告拉伸正应力 trace `1.362698599 GPa` 的绝对差为 `0.06211825788430758 GPa`，低于 `1.0 GPa` 阈值。
- `relax_to_post_relax_scf_500`（Jobs 30/31）通过：Job 30 最大力 `0.0028895226325467674 eV/Å`，Job 31 最大力 `0.0031283026377254487 eV/Å`，均低于 `0.02 eV/Å`；Job 30 `ionic_converged=true`，Job 31 是其后的 SCF 回传。
- [`real-vasp-regression-v005.json`](../workspace/reports/h0/real-vasp-regression-v005.json) 的 `all_passed=true`；Jobs 24、27、28、29、30、31 的 Slurm 终态、OUTCAR/vasprun.xml 能量、原子/晶格、应力符号与 Voigt、源 atom ID 断言均通过。Job 30→31 的结构来源与几何/对称性核对见 [`relax-lineage-v005.json`](../workspace/reports/h0/relax-lineage-v005.json)。
- 当前已安装 0.2.1 的 MCP→Slurm 查询 Job 29 证据为 [`mcp-installed-v021-query-job29.json`](../workspace/reports/h0/mcp-installed-v021-query-job29.json)；它证明查询路径可用，不清除 MatterAI native trust 的桌面入口待验收状态。
- 最终资源快照 [`final-resource-release.txt`](../workspace/reports/h0/final-resource-release.txt) 的队列表和 GPU 计算进程表均为空，记录时没有排队或运行中的数值作业。该快照只证明记录时的资源释放状态。
- H0 总体仍未完成：[`h0-acceptance.md`](h0-acceptance.md) 和 [`acceptance.json`](../workspace/reports/h0/acceptance.json) 保留 `H0_complete=false`；对于本次 H0 工程门，当前唯一待验收门为 MatterAI native trust 的桌面入口/原生 review。H1 目前只有只读预检 [`h1-abacus-preflight.md`](h1-abacus-preflight.md)，尚未开始 ABACUS 数值任务。

## MatterAI 原生 review UI：只读调查

本节沿用上游源文件静态检查，并补充真实 workspace 的 0.2.0 配置解析和 stdio 握手证据。安装和 probe 不等于 MatterAI 原生 review 已批准：没有启动完整 Electron 应用，没有写 truststore，也没有伪造可信记录；native trust 仍须由桌面入口产生。

### 本地状态

- 真实 workspace 当前存在 [`workspace/.zeus/mcp.json`](../workspace/.zeus/mcp.json)。直接导入上游 `parseZeusMcpConfig` 的证据为 [`mcp-config-v020-parse.json`](../workspace/reports/h0-p0/mcp-config-v020-parse.json)：解析到一个 `stdio` 的 `mlcc` server 和 7 个 `allowedTools`，`zeus://workspace/current` 在该解析函数中保持原样，`expandedWorkspaceRoot=null`；这份证据只覆盖配置解析，没有调用 trust、fingerprint 或 `tools/list`。
- 已安装 0.2.0 的真实 stdio 启动/握手证据为 [`mcp-installed-v020-probe.json`](../workspace/reports/h0/mcp-installed-v020-probe.json)：`initialize` 返回协议 `2025-06-18`、server `mlcc-agent` version `0.2.0`，真实 `tools/list` 返回 7 个工具，随后 `mlcc_list_tasks` 调用成功。该报告不代表 native trust 已批准。
- 只读尝试 `npx --no-install tsx ..\scripts\platform\probe-matterai-mcp.ts`（在 `MatterAI-main/MatterAI-main` 中执行）返回退出码 `1`：上游目录的 `npx` 路径没有解析到隔离 runtime 的 `tsx@4.23.15`，未安装依赖；实际 runtime 的 `workspace/runtime/matterai/node_modules/.bin/tsx.cmd` 后续已单独用于 0.2.0 registry 验收。这不改变当前已存在配置和已完成 stdio 握手的事实，也没有启动完整 Electron 应用或子服务。
- 上一条 npx 记录只说明上游目录的命令解析事实；隔离 runtime 的 tsx 已用于上述 0.2.0 registry/配置解析，不应再写成“本机没有 tsx”。现有 [`scripts/platform/probe-matterai-mcp.ts`](../scripts/platform/probe-matterai-mcp.ts) 的安全路径仍要求读取平台 loader、做精确 trust 查询，并在可信记录存在时才进入真实 `tools/list`；它没有被改成绕过 native trust 的通道。

### 上游实际入口和阻塞点

| 层 | 上游证据 | 实际合同 |
|---|---|---|
| Renderer | `MatterAI-main/MatterAI-main/apps/desktop/src/services/mcp/mcpClient.ts:104-129` | `testMcpServer`/`reviewMcpServers` 先要求 `ActiveWorkspaceAccess`，再通过 Zeus bridge 发送请求；最小 Node runtime 没有该 workspace capability。 |
| IPC | `MatterAI-main/MatterAI-main/apps/desktop/electron/ipc/agent-ipc.ts:223-224,4060-4111,4176-4177` | 正式入口是 `zeus.mcp.test` → IPC `mcp:test`，以及 `zeus.mcp.review` → IPC `mcp:review`；`mcp:test` 先调用 review，未获信任时只返回 `mcp_review_required`，不会执行 `tools/list`。 |
| Native review | `MatterAI-main/MatterAI-main/apps/desktop/electron/ipc/agent-ipc.ts:2586-2612`；`MatterAI-main/MatterAI-main/apps/desktop/electron/ipc/mcp-execution-gate.ts:331-421` | review 调用 `McpExecutionGate.reviewWithNativeDialog`。Electron 原生对话框按钮是 `Continue restricted` / `Trust and enable`；只有用户选择信任、快照仍匹配且安全审查通过时才写入批准。 |
| tools/list | `MatterAI-main/MatterAI-main/apps/desktop/electron/ipc/agent-ipc.ts:3138-3185` | 原生 `testMcpServer` 仍须通过 `gate.requireTrustedServer` 才调用 `listMcpTools`；当前 workspace 配置和独立 stdio 握手已存在，但没有可信记录或可用 Electron gate，因此不能把独立 probe 等同于原生 review 验收。 |
| Trust store | `MatterAI-main/MatterAI-main/apps/desktop/electron/main.ts:412-417`；`MatterAI-main/MatterAI-main/apps/desktop/electron/runtime/mcp-trust-store.ts:28,659+` | 完整应用创建 `McpExecutionGate(new McpTrustStore(userDataRoot), dialog.showMessageBox)`；记录文件名为 `mcp-trust-v1.json`。最小 runtime 不能替代 native dialog，也不能手工写该记录绕过批准。 |

因此当前 review UI 的正式阻塞链是：**已有 `.zeus/mcp.json` 和真实 stdio server，但没有活动 Electron workspace capability/BrowserWindow，也没有用户通过原生 review 产生的 trusted record**。独立 stdio probe 已经验证服务握手和 `tools/list`，后续仍须由完整 MatterAI UI 触发正式 review，才能验收原生入口的信任路径；本台账不把独立 probe 误报成 native trust。

## 证据索引与边界

- Jobs 12–13：`workspace/tasks/h0-mpi-{one,four}-v001/`、`workspace/reports/h0/mpi-{one,four}-*`、`docs/h0-mpi.md`。
- Jobs 14–16：`workspace/tasks/h0-runner-{echo,failure,cancel}-v001/` 内的 `task.json`、`job.sbatch` 和 stdout/stderr。
- Jobs 17–20：`workspace/tasks/h0-ni-single-v00{1,2,3,4}/`、`workspace/reports/h0/vasp-*`、`workspace/reports/h0/partial-transfer-job19-cancel.txt`。
- Jobs 21–27：`workspace/tasks/h0-ni-{four,relax,post-relax,cutoff500,strainminus,strainplus}-v004/`、`workspace/tasks/h0-ni-cutoff600-v005/`、`workspace/reports/h0/vasp-comparison.json`、`workspace/reports/h0/relax-lineage.json`、`workspace/configs/h0-vasp-method-v003.json`。
- Jobs 28–31：`workspace/tasks/h0-ni-{strainminus,strainplus,relax,post-relax}-v005/`、`workspace/reports/h0/vasp-comparison-v003.json`、`workspace/reports/h0/real-vasp-regression-v005.json`、`workspace/reports/h0/relax-lineage-v005.json`、`workspace/reports/h0/final-resource-release.txt`、`workspace/reports/h0/mcp-installed-v021-query-job29.json`。
- 当前 MCP 配置/握手：`workspace/.zeus/mcp.json`、`workspace/reports/h0-p0/mcp-config-v020-parse.json`、`workspace/reports/h0/mcp-installed-v020-probe.json`；这些证据不等于 MatterAI native trust。
- 运行时和 UI 调查是只读证据；没有把本表写入 `plans/stages.json`，也没有宣称 H0 的生产材料或 ABACUS 阶段已完成。
