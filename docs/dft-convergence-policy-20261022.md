# DFT收敛与无墙钟时限规则

用户2026-10-22明确：具体DFT计算不设置时间限制，必须达到收敛标准。本规则覆盖以后实际调用ABACUS/VASP的生产、兼容和诊断任务，优先于旧计划中的分钟预算。

- 新DFT请求显式使用`resource_request.time=0`；候选runner默认写入0，拒绝有限时间请求，提交时显式`sbatch --time=0`。不得通过删除字段而继承有限分区默认值。
- CPU/GPU数、内存、模型规模和观测量仍明确。GPU支持时优先GPU。已有CPU Berry不重算，不能以本规则批准范围外计算。
- 电子SCF必须达到声明的原生收敛标准；弛豫还必须达到相应离子/力/应力条件。截断、k点、超胞、位移/应变幅度等目标量收敛须有适用域证据。`scf_nmax`/`relax_nmax`仍是显式迭代控制，耗尽而未收敛属于未完成，不自动调参/重跑。
- 正常退出、Slurm COMPLETED或运行足够长均不能替代科学收敛。崩溃、资源失败和未收敛分别保留原始原因。
- 用户已于2026-10-22解除24小时开发限制，原2026-10-23 09:20到时汇总/暂停规则撤销。按进度和验收里程碑持续推进；局部阻塞记录证据与恢复条件并推进独立工作，不能截断正常DFT或绕过科学验收。非DFT软件测试、输入生成和科学后处理仍可设置合理墙钟预算。
- 历史任务记录、冻结0.9.0和已完成验收不改写；旧有限时长DFT脚本不得用作新实验模板。

## 用户补充的ABACUS配置提示

2026-10-23用户确认后续新计算按[ABACUS使用提示](abacus-practical-tips.md)设置：`conda activate abacuscopilot`及相关PBE资源/轨道工具线索；新任务截断能取对应库描述值的约1.2倍，SCF电子迭代上限显式设为1000～2000范围内的明确值。记录库基准、单位和实际输入；具体工具命令/转换对象使用前核对。仅影响后续范围内的新ABACUS计算，不触发旧任务重跑，不以较大迭代上限代替原生收敛判据；两个窗口继续铁电/介电分工，有实质进展再汇报。

## 服务器生效边界

候选runner的修改已由v100 Slurm **job68 COMPLETED/0:0** 验证：12项相关软件测试通过，包含ABACUS/VASP默认持久化、有限时间拒绝、提交显式0以及非DFT回归。没有运行DFT、改科学参数或重做冻结验收。该修改仍在未安装的0.10候选；冻结启用0.9不变，后续若使用旧入口则必须显式传入time=0。

初次读取v100发现CPU/GPU两分区均为`MaxTime=1-00:00:00`，`sudo -n -l`需要密码。2026-10-22 13:06用户在独立交互终端完成sudo认证后，重新读取两分区及`/etc/slurm/slurm.conf`，均为**MaxTime=UNLIMITED**，配置已经生效。普通任务的DefaultTime保留1天，DFT显式time=0不继承该缺省值。

已准备窄范围管理员脚本`scripts/admin/allow-unlimited-dft-v100.sh`：备份现行配置，只将cpu/gpu的MaxTime改为UNLIMITED，保留未指定time的普通任务默认1天，然后reconfigure并打印分区。不重启服务、不提交DFT、不改其他资源。上传路径：`/home/v100/projects/mlcc/configs/allow-unlimited-dft-v100.sh`。管理员在v100执行：

```bash
sudo bash /home/v100/projects/mlcc/configs/allow-unlimited-dft-v100.sh
```

已完成CPU/GPU各一次`sbatch --test-only --time=0`，均返回可调度预估。输出中的69/70是test-only预估标识，不是已提交计算或原生终态证据。此后不重复站点检查，也不为证明配置另跑DFT。证据见`workspace/reports/dft-time-policy-v001/site-after.txt`及两个`*-unlimited-test-only.txt`。

官方依据：[sbatch的time=0及分区限制](https://slurm.schedmd.com/sbatch.html#OPT_time)、[slurm.conf的DefaultTime/MaxTime](https://slurm.schedmd.com/slurm.conf.html#OPT_MaxTime)。
