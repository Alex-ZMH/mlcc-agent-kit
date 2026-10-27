# H0 工程验收与交接

日期：2026-10-20。主入口为 [机器可读验收](../workspace/reports/h0/acceptance.json)。

## 已完成

- 原版 MatterAI 安装器/registry 真实装载 `mlcc-agent@0.2.1`：1 Agent、4 Skill、7 个真实 stdio MCP 工具。
  [P0 证据](h0-p0-bundle.md)。已安装 MCP→Slurm 查询 job 29 成功；本地 `mlcc.exe` CLI 已实际安装并查询 job 30。
- 项目 Python 3.12.10；13 个局部测试通过，保留 11 条 ASE/NumPy 上游弃用告警。
  [单测](../workspace/reports/h0/unit-tests-v021.txt)、
  [包安装](../workspace/reports/h0/local-package-install-v021.txt)。
- 复用 Slurm，NVHPC `mpirun` 在 sbatch allocation 内通过单/四 rank 的 CPU/CUDA buffer reduction。
  runner 正常、显式失败、取消、查询和 scp 回传均实测。[MPI](h0-mpi.md)、[完整台账](h0-execution-ledger.md)。
- Ni 4 原子工程模型、稳定 atom ID、原始/派生结构、VASP 输入与真实解析成立。
  400 eV 单/四卡一致性通过；500 eV 固定晶胞弛豫→指定 CONTCAR→SCF→回传闭环通过。
- k 网格按用户规则各向取 `ceil(30/length)`，长度 Å；当前 Ni 为 9×9×9。
  未做独立 k 网格收敛扫描，不将此规则宣称为生产精度证明。

## 数值验收

| 检查 | 实测 | 预定阈值 | 结果 |
|---|---:|---:|---|
| 400 eV 单/四卡最大力分量差 | 1e-8 eV/Å | 1e-4 eV/Å | 通过 |
| 500→600 eV 能量差 | 0.00026661 eV/atom | 0.01 eV/atom | 通过 |
| 500→600 eV 最大力分量差 | 1.311e-05 eV/Å | 0.03 eV/Å | 通过 |
| 500→600 eV 最大应力分量差 | 0.08399897 GPa | 0.5 GPa | 通过 |
| 500 eV 应变能导数与应力迹差 | 0.062118258 GPa | 1.0 GPa | 通过 |
| 500 eV 弛豫最大力 | 0.0028895226 eV/Å | 0.02 eV/Å | 通过 |
| 500 eV 后续 SCF 最大力 | 0.0031283026 eV/Å | 0.02 eV/Å | 通过 |

证据：[v003 对照](../workspace/reports/h0/vasp-comparison-v003.json)、
[真实输出解析回归](../workspace/reports/h0/real-vasp-regression-v005.json)、
[500 eV 结构谱系](../workspace/reports/h0/relax-lineage-v005.json)。
这里验证的是 Ni 工程阈值；不构成 CaZrO3 性能、生产 DFT 方法或势标签资格。
500 eV 改变的是 cutoff；单/四卡数值等价实验发生在 400 eV，范围单独保留。
派生 Ni 结构在 symprec=1e-05 Å 下检测为
P4mm；这是工程力收敛公差下的残余畸变记录，
不解释为发现了 Ni 新相，也没有把坐标强制对称化。

400 eV 的应力 cutoff 检查和应变导数检查**失败并保留**：
[原验收](../workspace/reports/h0/vasp-comparison.json)、[诊断](h0-stress-diagnosis.md)。
随后人工审查并预先记录 v003 方法/五任务预算，未降低阈值。
Job 17 QD ABI、18 CRLF、19 部分传输误提交失败均保留原日志。
原始 VASP stderr 的浮点告警未隐藏；输出有限性、OUTCAR/XML 一致性和物理对照均另行核对。

## 原生作业与资源

| Job | Task | 原生状态 | ExitCode | 完整事件/命令 |
|---:|---|---|---|---|
| 12 | h0-mpi-one-v001 | COMPLETED | 0:0 | [h0-mpi-one-v001](../workspace/tasks/h0-mpi-one-v001/task.json) |
| 13 | h0-mpi-four-v001 | COMPLETED | 0:0 | [h0-mpi-four-v001](../workspace/tasks/h0-mpi-four-v001/task.json) |
| 14 | h0-runner-echo-v001 | COMPLETED | 0:0 | [h0-runner-echo-v001](../workspace/tasks/h0-runner-echo-v001/task.json) |
| 15 | h0-runner-failure-v001 | FAILED | 7:0 | [h0-runner-failure-v001](../workspace/tasks/h0-runner-failure-v001/task.json) |
| 16 | h0-runner-cancel-v001 | CANCELLED | 0:15 | [h0-runner-cancel-v001](../workspace/tasks/h0-runner-cancel-v001/task.json) |
| 17 | h0-ni-single-v001 | FAILED | 127:0 | [h0-ni-single-v001](../workspace/tasks/h0-ni-single-v001/task.json) |
| 18 | h0-ni-single-v002 | FAILED | 1:0 | [h0-ni-single-v002](../workspace/tasks/h0-ni-single-v002/task.json) |
| 19 | h0-ni-single-v003 | FAILED | 127:0 | [h0-ni-single-v003](../workspace/tasks/h0-ni-single-v003/task.json) |
| 20 | h0-ni-single-v004 | COMPLETED | 0:0 | [h0-ni-single-v004](../workspace/tasks/h0-ni-single-v004/task.json) |
| 21 | h0-ni-four-v004 | COMPLETED | 0:0 | [h0-ni-four-v004](../workspace/tasks/h0-ni-four-v004/task.json) |
| 22 | h0-ni-relax-v004 | COMPLETED | 0:0 | [h0-ni-relax-v004](../workspace/tasks/h0-ni-relax-v004/task.json) |
| 23 | h0-ni-post-relax-v004 | COMPLETED | 0:0 | [h0-ni-post-relax-v004](../workspace/tasks/h0-ni-post-relax-v004/task.json) |
| 24 | h0-ni-cutoff500-v004 | COMPLETED | 0:0 | [h0-ni-cutoff500-v004](../workspace/tasks/h0-ni-cutoff500-v004/task.json) |
| 25 | h0-ni-strainminus-v004 | COMPLETED | 0:0 | [h0-ni-strainminus-v004](../workspace/tasks/h0-ni-strainminus-v004/task.json) |
| 26 | h0-ni-strainplus-v004 | COMPLETED | 0:0 | [h0-ni-strainplus-v004](../workspace/tasks/h0-ni-strainplus-v004/task.json) |
| 27 | h0-ni-cutoff600-v005 | COMPLETED | 0:0 | [h0-ni-cutoff600-v005](../workspace/tasks/h0-ni-cutoff600-v005/task.json) |
| 28 | h0-ni-strainminus-v005 | COMPLETED | 0:0 | [h0-ni-strainminus-v005](../workspace/tasks/h0-ni-strainminus-v005/task.json) |
| 29 | h0-ni-strainplus-v005 | COMPLETED | 0:0 | [h0-ni-strainplus-v005](../workspace/tasks/h0-ni-strainplus-v005/task.json) |
| 30 | h0-ni-relax-v005 | COMPLETED | 0:0 | [h0-ni-relax-v005](../workspace/tasks/h0-ni-relax-v005/task.json) |
| 31 | h0-ni-post-relax-v005 | COMPLETED | 0:0 | [h0-ni-post-relax-v005](../workspace/tasks/h0-ni-post-relax-v005/task.json) |

数值任务均经 Slurm、最大并发 1；VASP 用原生 RunTime 与请求卡数统计约
2.011 GPU·h（含失败尝试，不是 GPU 利用率积分）。
四卡进程的不同物理 GPU UUID 实证在
[运行快照](../workspace/reports/h0/vasp-relax-v004-runtime.txt)。
CPU 1/4 rank 请求在本机分别分配 2/8 个 SMT 逻辑线程；VASP RAM 请求 8192 MiB。
本机没有 sacct 持久记账，原生 scontrol 终态已落盘。
收尾时本用户队列和 GPU 计算进程均为空，见
[资源释放快照](../workspace/reports/h0/final-resource-release.txt)。

可重放的当前入口为：

```powershell
workspace/.venv/Scripts/python.exe scripts/h0/vasp_fixture.py <action> <case> --task-version v005 --method workspace/configs/h0-vasp-method-v003.json
workspace/.venv/Scripts/python.exe scripts/h0/compare_vasp_v003.py --scope all
workspace/.venv/Scripts/mlcc.exe status --site workspace/configs/site.v100.json --task <task.json>
```

已有 task 不重新提交；上例说明入口参数，实际 sbatch/scp 命令与原始输出在各 task.json/events。

## 未完成与下一最小任务

**H0 工程闭环已完成（2026-10-21）**：原版 MatterAI registry/Agent profile → 原版 CodexCliRuntime → 已安装 MLCC MCP 的真实模型调用通过。
实际 provider session 调用了且仅调用了 `mlcc_list_tasks`，返回 23 条任务，CLI 退出 0。
[真实宿主证据](../workspace/reports/h0/matterai-headless-provider-session-v021-list-tasks-v003.json) 保留完整 JSONL。
原版 runtime 将这版 MCP 事件交付为 `provider.raw`；验收使用真实 `item.completed/mcp_tool_call` 及返回内容，不依赖助手自述。
无桌面要求，不写 truststore；仅使用已授权项目工具，`--ignore-user-config` 隔离全局配置。
首个配置错误和原规范事件断言失败记录保留；v003 重新解析同一次成功会话，没有重跑模型来补证据。
[入口核查](matterai-runtime-scope.md) 中 2026-10-21 的待办状态由本次实测更新。
Slurm direct srun/PMIx 插件仍缺系统库；本项目明确使用已实测的 allocation 内 NVHPC mpirun。
曾短暂 PENDING/InvalidAccount 后由 Backfill 启动的现象仍保留，没有重装或修系统服务。

生产请求已确认为 **无掺杂 CaZrO3／正交 Pnma，按指定温度研究**。
生产温度为 330 K、400 K，外压 1 atm（101325 Pa）；结构来源仍待核验。
保留层与临时粘结剂两条高分子分支均保留、材料/工艺未选。

后续进展（2026-10-21）：ABACUS 3.10.1独立MPICH环境的Ni jobs32/33/34已通过SCF→独立弛豫→末结构SCF→回传工程小闭环；当前Bundle为0.3.0，原版宿主真实MCP调用再次通过。下一最小任务是100→120 Ry截断对照，见[本轮台账](h1-execution-ledger.md)与[整体进度](project-progress-20261021.md)。
[H1 只读预检](h1-abacus-preflight.md) 已有本机版本与 Ni UPF/ORB 头部证据；
ABACUS Ni 候选 18 价电子与 VASP Ni 10 价电子不同，不能比较裸总能。
ORB 配对尚未确认，候选文件未被自动认定为合格基组。
P4 迁移与生产引擎切换、P5–P12 的性质/势/MD 均未完成，没有生成生产标注。

两个参考树保持只读；本轮没有 Git 提交/建分支、Slurm 重装、服务器重启或驱动升级。
