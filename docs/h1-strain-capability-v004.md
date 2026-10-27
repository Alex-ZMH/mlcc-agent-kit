# B03 Ni粗参数应变链路验收（2026-10-21）

能力链路已通过真实三点任务验证；科学应力符号标定未通过。无重试、提精度或阈值调整。H1与生产引擎切换保持false。旧job36没有进入比较。

## 计算前固定的规则

参考job37，parent method `ni-oncv-pbe18-pw-capability-v003`；子method `ni-oncv-pbe18-pw-strain-capability-v004`，固定2×2×2、scf_thr=1e-4、100Ry及原占据/自旋/赝势。固定分数坐标、atom_id、四Ni计量，F=(1±0.005)I。只新增两个顺序单GPU SCF，每个1rank、8GiB、20分钟上限。任务在Slurm内运行，LAN ssh/scp负责控制和传输。

使用有限展宽自由能energy_eV，忽略sigma→0能量；D=(Eplus−Eminus)/(2hV0)×160.21766208 GPa。比较原生应力迹及其负值，绝对误差≤1GPa且恰有一个候选满足才通过。预声明见 `workspace/reports/h1/strain-quick-v004/predeclared-protocol.json`，在提交前写入。

## 原生结果

| 位置 | job | 终态 | 时间 | SCF步 | 最终DRHO | 自由能eV |
|---|---|---|---|---|---|---|
| −0.5% | 38 | COMPLETED/0:0 | 8秒 | 6 | 6.6734e-5 | −16778.907223990107 |
| 0 | 37（既有） | COMPLETED/0:0 | 10秒 | 7 | 1.3831e-5 | −16778.90745945708 |
| +0.5% | 39 | COMPLETED/0:0 | 9秒 | 7 | 4.2961e-5 | −16778.89525270776 |

参考体积43.61420799999998 Å³；D=+4.397674422399571GPa，job37原生应力迹−10.753156322490002GPa。与打印迹的误差15.150830744889571GPa，与负打印迹误差6.355481900090431GPa，两者均超过1GPa，比较器正确退出1并保留报告。参数/几何/原生日志可比性检查全部通过，但这一粗参数数据不足以完成预设应力标定。不能凭符号方向猜测合格，也不以程序结束代替物理验收。没有拟合Cij或验证完整应力张量/剪切。

两个新作业共17秒；job38结束后才提交job39。原生EndTime/StartTime、Requeue=0、Restarts=0及单GPU请求保存在 `sequential-resource-evidence.json`。最后队列与GPU计算进程为空。

## 代码与验证

仅本切片新增修改 `mlcc-agent/src/mlcc/strain.py`、`mlcc-agent/tests/test_strain.py`：直接读取当前四行Gamma KPT，核对三个任务的网格/偏移相同且与method和配置一致；复用已有原生来源谓词，缺失原生日志不能计算资格。新测试覆盖2³/v003→v004、KPT偏移不符与日志缺失。已审查原子映射、相同原生INPUT（只允许suffix不同）、原生最终能量与解析值一致。

`workspace/.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider mlcc-agent/tests`：85 passed，114条ASE/NumPy弃用告警保留。原0.5.0安装目录未覆盖；新比较器本次从源码执行，尚未重新发布Bundle，供主窗口合并复审后发布。未改modeling.py或B04导入功能。

全部创建/准备/传输/提交/查询/收集/解析命令及退出码分别保存在 `create-commands.json`、`minus-commands.json`、`minus-completion.json`、`plus-commands.json`、`plus-completion.json`。比较命令为：

```text
workspace/.venv/Scripts/python.exe scripts/h1/compare_strain.py --minus-task workspace/tasks/h1-ni-strainminus-v004 --reference-task workspace/tasks/h1-ni-scf-v003 --plus-task workspace/tasks/h1-ni-strainplus-v004 --method workspace/configs/h1-abacus-method-v004.json --report workspace/reports/h1/strain-quick-v004/comparison.json
```

除显式任务路径外，本节证据均在 `workspace/reports/h1/strain-quick-v004/`。其中 `comparison-command.json` 保留退出1，`comparison.json` 含全部检查、导数和候选，`acceptance.json` 区分能力通过与科学未通过。配置为 `workspace/configs/h1-abacus-method-v004.json`，请求为 `workspace/configs/requests/ni-strainminus-v004.json` 和 `ni-strainplus-v004.json`。

下一步由主窗口推进不依赖该科学资格的B04最小模型导入软件切片；本窗口不抢占实现所有权，不自动再提交应变计算。H1生产资格及后续科学链仍按依赖保留。
