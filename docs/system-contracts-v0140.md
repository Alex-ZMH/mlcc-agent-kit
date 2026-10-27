# 0.14.0 P5 工程交付

0.14.0已验收启用冻结，0.13.0保留为回退；源码进入0.15.0。v100安装job140 COMPLETED/0:0，两个新增公共入口通过，原版MatterAI宿主会话通过，93个发布/安装文本文件直接一致。正式registry、MCP和Python均绑定0.14。详见[发布验收](../workspace/reports/system-v0140/acceptance.json)。

## 已实现并通过的路径

新增只读 `berry_results.read_berry_task`，既有写入入口 `parse_berry_task` 调用同一读取函数后保存。新增 `property_delivery.deliver_berry_polarization` 及公共命令：

```text
mlcc deliver-polarization --study STUDY.json --task TASK --output DELIVERY.json [--targets TARGETS.json]
```

复用真实CZO参考SCF job50与CPU兼容Berry job58，交付Study/模型/方法/原子来源绑定的单gdir极化代表值、极化量子、方向、原生任务和调度来源。不会改写历史task/result。结果仍为未解分支、未资格；无设计指标为not_assessed，提供指标但证据未资格时为insufficient_evidence。完整三维极化、自发极化、Born电荷、介电张量均未计算。

v100 CPU后处理job138 COMPLETED/0:0、2秒：4项定向检查及真实公共CLI通过。前次job137 FAILED/1:0暴露来源推导式变量覆盖极化数值，已修正；137失败和138修复后证据同时保留，无自动重试。没有新增DFT/MD，没有重跑CPU Berry。见[验收记录](../workspace/reports/p5-delivery-v014-v001/acceptance.json)。

## 集成与下一步

- 极化分支/差值模块136及来源/分支边界修复139已集成。公共`polarization-path --request PATH.json --output RESULT.json`随安装140通过；现有单点58正确返回unresolved_insufficient_path、ΔP=null，多点响应仍未完成。
- 主线继续基于现有53/61故障证据核对Berry GPU精确构建配方和可实施修复。真实新增响应依赖可用原生生产者；不把sawtooth薄膜电场或溶剂介电参数包装成体相介电张量。
- CZO/BTO掺杂、氧空位、晶界的四层状态以[六场景台账](ceramic-parameter-transfer-gaps-20261022.md)为准。当前输入待选、软件路径、场景证据和科学资格分开记录。
- DeePMD独立工程链已通过，最新专项job135；Ni两帧不能代表陶瓷场景。后续复用现有dataset/training/handoff/inference及TaskRecord/SiteRunner；优先审已有CZO50/121标签，host与vacancy不同原子数分系统，q0/q+2不能无条件混入普通势。
- MACE/CZO应力差继续留档并跳过精调/换势研究，不阻塞上述系统开发。

本版只补变化入口的安装验收，未重复冻结0.13整套验证。安装控制过程曾因本地缺setuptools backend失败，随后显式使用已存在build-tools完成安装；官方installer拒绝重复安装同版，因此按其输出建议更新现有激活登记和MCP路径，再完成真实宿主验收。原始控制日志保留，没有覆盖已验收旧版或重跑计算。

旧0.10删除的自动审批拒绝仍未解除；0.11/0.12旧软件副本待退役，本版没有删除。共享Python和所有科学/原生证据保留，不宣称磁盘只留两版。
