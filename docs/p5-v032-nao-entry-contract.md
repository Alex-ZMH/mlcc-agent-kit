# 0.32 公共 NAO 快照与现有来源链合同 v001

用户已授权持续系统开发；0.31启用、0.30回退、源码0.32候选。此合同直接进入实施，不等待定义后再次确认。

## 实际缺口与范围

0.31的 `check_method_configuration` 已消费 `mlcc.nao-header-snapshot.v1`，但快照仅由357验收harness构造，尚无公共产品命令。新增公共 `inspect-nao --method METHOD --site SITE --output NEW_SNAPSHOT`，输出既有schema，不创建第二种快照或来源框架。

现有 `parse-abacus --task 原任务task.json --site SITE`、`electronic --task 原任务目录 --output NEW`、`electronic-dielectric` 及 `deliver-properties` 已存在，344/355/356已有原生消费证据。实施窗口只核对这些现有操作到底缺哪一步；若已可用，只交回命令/产物对应表和复用证据，不新增同义bind/import桥、不重复旧解析或交付。0.31新建但未执行的TaskRecord必须保持未提交，不能把269/284的job ID移到这些新任务上。

## NAO入口冻结接口

```python
# method_tasks.py，主线受托Luna独占
inspect_site_nao_headers(method_path, site_path) -> dict
# CLI由主线独占：inspect-nao，三项路径参数同inspect-upf，输出使用open('x')。
```

这个命令在所选计算站点（v100 Slurm）执行，直接读取site中已明确选择的远端路径。它不自动探测/扫描资源、不改变SSH配置、不增加传输模式或失败回退。保留原 `inspect-upf` 行为；本入口复用其可审计快照和CLI输出模式，无需v100内部再SSH回环。

输入沿0.31的 `numerical_orbital_ids`、`site.abacus.numerical_orbital_files`、`pseudopotential_ids/files`、element_order；新增方法顶层一个明确记录：

```json
"numerical_orbital_library": {
  "name": "所选库名称",
  "version": "所选库版本",
  "functional": "PBE",
  "pairing_source": "已选库的原生配套说明路径",
  "pseudopotential_map": "该库逐元素UPF文件名JSON记录路径"
}
```

库元素映射内容是 `{element: filename}`，来自已选库记录；不得据它自动替换用户的UPF/NAO选择。检查所选UPF basename与该元素记录相符，functional与science显式PBE相符；NAO头的元素必须与所选元素相符。库/版本/说明必须显式提供。输入不符或文件缺失保留原错误，不重试、不换资源。

只截取NAO原文头至 `SUMMARY END`，复用 `parse_nao_header`；不读取庞大径向数据作数值计算。输出既有 `mlcc.nao-header-snapshot.v1`：ssh_alias、method_set、library、library_version、pairing_source、observed_at、native_excerpts[element]。每个原生摘录记录source_path、orbital_id、native_excerpt、functional、source_kind=`declared_library_pairing`、paired_pseudopotential_id/source。另保存原配套说明和逐元素映射的路径及原文内容。PBE是库配套声明，不声称来自不含XC的NAO原生头；快照不授科学或生产资格。后续已有qualify-method继续重读摘录并检查UPF/NAO、电荷和带数。

## 独占分工

| 所有者 | 独占文件与责任 |
| --- | --- |
| 主线受托Luna | method_tasks.py新增上述函数；不动原0.31资格/其他产品文件，不提交检查 |
| 主线 | cli.py公共入口、集成harness、文档/计划、安装发布与唯一Slurm验收 |
| 既有实施窗口 | 新tests/test_nao_snapshot_entry.py；现有保存源→公共解析/响应调用链的短核对及命令交接，报告目录workspace/reports/nao-public-entry-v032-v001/consumer-handoff；不改现有解析/消费产品代码，不提交检查 |

双方不是独自工作，不覆盖别人的变更；接口变更先交主线。无需再修改abacus.py/writer或引入新模块/runner。

## 本轮唯一最小验收

预算v100 Slurm非DFT，1CPU/0GPU/2GiB/10分钟、no-requeue。验收使用实际已装候选的公共inspect-nao，读取原Ca/Zr/O库头和配套记录；其输出直接进入既有qualify-method及一次create-abacus/prepare，证明NAO快照不再依赖harness手工拼装。只生成输入，不运行ABACUS/PYATB；旧269/284执行及355/356消费、357其余writer/creator检查复用，不整套重跑。

新测试只覆盖新增入口/配套说明、元素映射不符、缺资源或缺元数据、源头元素不符、PBE声明不符、输出文件已存在等实际改变的行为。所有负例仅为明确输入失败案例，不伪造科学输出。公共命令原文按case分别保存，避免357共用日志文件的证据边界。

现有来源链若只缺使用说明，复用既有真实证据完成交接；不为了“桥接”新增调用或验收次数。科学Born/Γ/离子/静态介电，以及P4带电修正、P6/P8/P11未完功能继续单列，不阻塞此软件切片。
