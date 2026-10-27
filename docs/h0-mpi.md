# H0 MPI 与站点环境验收

2026-10-20（Asia/Shanghai）。使用 v100 LAN 别名；未重装 Slurm、未更改服务/驱动、未使用 sudo。

## 显式启动路线

VASP 使用 NVHPC 24.1 的 HPC-X 2.17.1 / Open MPI 4.1.7a1，
内嵌 PMIx 3.2.5a1。`ompi_info` 实测有 ras/slurm、plm/slurm 和 CUDA buffer 支持。

系统 Slurm 的 pmix_v5 插件缺少运行库；本次未声称修复 direct `srun --mpi=pmix`。
选择 handoff P1.06 允许的 `sbatch allocation → NVHPC mpirun` 路线。
所有数值程序在 Slurm allocation 内执行，没有 SSH 直接启动计算，也没有调度后端回退。
这一启动模式见 [Open MPI 的 Slurm 说明](https://github.com/open-mpi/ompi/blob/main/docs/launching-apps/slurm.rst)；本机能力以以下真实作业为准。

站点环境在 `workspace/configs/vasp-nvhpc-env.sh`，远端同名配置位于
`/home/v100/projects/mlcc/configs/`。显式加入现存 UCC/UCX/OMPI 库目录后，
`ldd /opt/vasp/vasp_std` 没有缺失项；这仅说明动态链接就绪，不等于 VASP 已运行。

## 源码、编译与提交

测试源码：`scripts/h0/mpi_cuda_reduction.cpp`。每个 rank 使用不同 CUDA device，
分别对主机缓冲区和 `cudaMalloc` 设备缓冲区调用 `MPI_Allreduce`，
记录 world size、rank、CPU affinity 和 GPU PCI bus ID，并核对整数和。
没有文件校验和、自动重试或替代计算。

实际编译命令（SSH 中编译，无数值执行）：

```bash
source /home/v100/projects/mlcc/configs/vasp-nvhpc-env.sh
nvc++ -cuda -gpu=cc70 -O2 -Wl,-z,noexecstack \
  -I$HPCX_ROOT/ompi/include /home/v100/projects/mlcc/src/mpi_cuda_reduction.cpp \
  -L$HPCX_ROOT/ompi/lib -lmpi \
  -o /home/v100/projects/mlcc/bin/mpi_cuda_reduction
```

编译退出 0。批脚本为 `scripts/h0/mpi-smoke.sbatch`，命令：

```bash
mpirun --map-by slot --bind-to core --report-bindings \
  /home/v100/projects/mlcc/bin/mpi_cuda_reduction
```

提交分别带 `--ntasks=1` / `--ntasks=4`、对应 task workdir/stdout/stderr，
使用 `sbatch --parsable`。均为每 rank 1 GPU / 1 physical core、4096 MiB RAM、
3 分钟上限、`--no-requeue`，串行提交。

| task | Slurm ID | 终态/退出码 | 实际耗时 | 主机/设备归约 |
|---|---|---|---|---|
| h0-mpi-one-v001 | 12 | COMPLETED / 0:0 | 2 s | 1 / 1 |
| h0-mpi-four-v001 | 13 | COMPLETED / 0:0 | 1 s | 每 rank 10 / 10 |

四卡 PCI bus ID：0000:0C:00.0、0000:0D:00.0、0000:10:00.0、0000:11:00.0。
CPU affinity 分别为 0,8 / 1,9 / 2,10 / 3,11（物理核及其 SMT sibling）。
CR_Core_Memory 的单/四 rank allocation 分别显示 2/8 logical CPUs，与既有拓扑一致。

## 记录与限制

- 远端：`/home/v100/projects/mlcc/tasks/h0-mpi-{one,four}-v001/`。
- 本地原始日志：`workspace/tasks/h0-mpi-{one,four}-v001/`。
- 原生终态与环境：`workspace/reports/h0/mpi-one-terminal.txt`、
  `mpi-four-check.txt`、`remote-preflight.txt`。
- job 12 短暂 PENDING/InvalidAccount 后由 Backfill 启动。历史文档声称该告警已完全修复，
  本次观察说明它仍可能出现；不伪造账号，不因告警重新提交，不隐去该事实。
- controller 日志读取返回 Permission denied，原始错误保留在
  `workspace/reports/h0/slurm-invalidaccount-diagnostic.txt`。
- 本测试证明小型 CUDA-aware 通信正确，不证明跨节点、VASP 四卡性能或生产精度。
- 当前控制器没有 GPU TRES 利用率/显存持久记账；PCI 映射来自实际 CUDA 调用。
- 本地 Python 3.12.10 用于建模/解析；远端独立 `.venv` 为 Python 3.12.3，当前仅 stdlib。
