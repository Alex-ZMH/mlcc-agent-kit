# MLCC 0.4.1 系统合同与续接验收

2026-10-21。目标是交付可复用 mlcc-agent 系统，计算案例用于验证能力。本轮完成 B01/B02 的首个可用切片，不把所有计划工作包标成完成，也不展开温度、缺陷或界面组合。

## 实现与调用

- `mlcc-agent/src/mlcc/studies.py`：显式 Study 读取、摄氏/开尔文计量、压力单位一致性、条件来源和缺口。静态参考与等温 MD 条件分开；后者只是输入合同，尚无 MD 执行器。
- `workflow.py`：只读续接建议、父结果及源文件依赖、task/model/method/result 链快照。未知提交不建议重提，已有原生 job ID 先查询；退出0不替代科学收敛。
- `site_runner.py`：原有提交防重逻辑后、写提交尝试之前核验新任务的 `required_results`；CLI/MCP 共用同一个 runner。历史任务没有此字段的，不追写依赖。
- `results.py`：从已解析 ABACUS 结果交付 Study/Model/Method/Task/Result 来源、能量/力/应力/可用磁矩和适用范围。工程结果不能变成生产标签，无设计规格时是 `not_assessed`。
- `qualification.py`：当前 ABACUS 3.10.1 Ni 同几何 100/120 Ry 截断比较，核对原生 INPUT、模型映射、单位、方法和调度证据。
- `cli.py`：新增 `study-plan`、`resume-plan`、`deliver-result`。七个 MCP 名称保持，`mlcc_list_tasks` 增加科学状态与 `next_action`。

在项目根运行，Python 是 `workspace/.venv/Scripts/python.exe`：

```text
python -m mlcc.cli study-plan --study workspace/configs/cases/cazro3-firing-v002.json
python -m mlcc.cli study-plan --study workspace/configs/cases/batio3-firing-v002.json
python -m mlcc.cli resume-plan --task workspace/tasks/h1-ni-post-relax-v001/task.json --site workspace/configs/site.v100.json
python -m mlcc.cli deliver-result --task workspace/tasks/h1-ni-post-relax-v001/task.json --study workspace/configs/cases/ni-engineering-v001.json --conditions workspace/configs/cases/ni-static-conditions-v001.json
python scripts/system/verify_contracts.py --bundle-root workspace/.zeus/bundles/mlcc-agent/0.4.1 --report-dir workspace/reports/system-v041/installed
```

这些读取/交付命令不会提交计算。输出包含静态参考条件、缺口和原始数值来源；缺口列表不是完整生产验收。

## 实际验证与限制

最终全套 `pytest mlcc-agent/tests -q -p no:cacheprovider`：48 passed，34条 ASE/NumPy 弃用告警保留。原版安装器安装并启用0.4.1，旧0.3.0/0.4.0不原地改写。安装版对两个案例配置和真实 jobs32/33/34执行读取/续接/交付，检查原任务文本未改变；见 [验收报告](../workspace/reports/system-v041/installed/acceptance.json)。具体命令、退出码和标准输出均在该报告中。

新 job35 实际读取 job32的终态、结果和源产物依赖后提交；该次依赖检查在 fixture 入口执行，随后统一移入 runner 并通过单测，避免 MCP/CLI 绕过同一门。没有为验证这次函数移动再提交重复数值任务。已安装0.4.1 MCP实际查询job35，见 [MCP报告](../workspace/reports/system-v041/mcp-installed-job35.json)。

job35 是唯一新增数值任务，Ni、120 Ry、单卡/单rank、8GiB、20分钟上限，实际00:08:54、COMPLETED/0:0、10次电子迭代收敛。生命周期 `create/prepare/transfer/submit/query/collect/parse cutoff120` 均由 `scripts/h1/abacus_fixture.py` 显式调用，退出0。命令、资源、原生job ID和事件见 [任务记录](../workspace/tasks/h1-ni-cutoff120-v001/task.json)。新生成任务仍使用用户最小整数网格规则，Ni为9×9×9。

首次比较命令退出1：[v001报告](../workspace/reports/h1/ni-cutoff100-120-v001.json)因旧method含两个冗余输出开关而判不可比。核对两个真实INPUT均为 `cal_force=1/cal_stress=1` 后，比较器改为同时验证原生INPUT，并要求历史开关若存在必须true；没有改动旧task/method/result。补充回归测试后再次分析相同产物，命令退出0：[v002报告](../workspace/reports/h1/ni-cutoff100-120-v002.json)。这不是重跑计算或修改阈值。

```text
python scripts/h1/compare_cutoff.py --baseline-task workspace/tasks/h1-ni-scf-v001 --comparison-task workspace/tasks/h1-ni-cutoff120-v001 --method workspace/configs/h1-abacus-method-v001.json --report workspace/reports/h1/ni-cutoff100-120-v002.json
```

| 量 | 实测差值 | 预设阈值 |
|---|---:|---:|
| 同方法能量差 eV/atom | 0.00002437959756 | 0.01 |
| 最大力分量差 eV/Å | 0.0006817747 | 0.03 |
| 最大应力分量差 GPa | 0.01530027461 | 0.5 |

仅该Ni截断对照通过。应力符号仍为 `abacus_printed`，有限应变标定未完成；生产赝势/方法、可变胞和性质接口未获资格。不同引擎裸能和标签没有合并。Job35运行时单GPU读数4756MiB，原始记录和最终空队列/无GPU进程在 `workspace/reports/system-v040/`，内存缺失项未补零。

## 案例与系统边界

当前显式CZO配置采用规划交接的400–580°C范围、1atm、无掺杂Pnma起点；BTO采用800–1350°C范围，相、组成和压力保持未选。旧 `workspace/configs/study.json` 的330/400K记录保留，不用于新的科学提交，不给Ni结果贴案例温度。两条高分子分支保留未选。

这次没有实现通用母相/掺杂构建、生产ABACUS参数化、公共电子/弹性、缺陷、四性质、势或MD执行器。没有用Skill数量或规划任务数衡量完成度。当前状态见 [系统进度](project-progress-20261021.md) 和 `plans/system-capabilities.json`。
