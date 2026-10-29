# AgentHost 准备状态

真实在线 LLM：**not_run**。本轮不外发模型输入、不调用在线 provider，不用离线路由/Schema通过冒充真实模型闭环。后续只使用现有 provider/AgentHost/Runtime/会话导出，不重建聊天系统。

0.1.1 的原始材料表示已改为严格 `{region_tag,...}` 条目数组，跨字段验证拒绝重复/缺失/多余标签。四个 input schema 均能经过当前 `mlcc.agent.decision_schema` 和 `mlcc.codex_host.structured_schema` 编译；宿主可离线加载公共Agent、routing Skill和本模块方法Skill。output有效材料中的区域字典不用于provider action schema。

离线准备和真实既有任务事实卡（只读、不创建任务、不运行WSL/模型）：

```powershell
$RvePython = 'C:\Users\Xiang\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
& $RvePython -m modules.rve.harness.agent_acceptance --task-id task-9f711feb94b8404db2d3cc8d90514198
```

最小完整显式合成输入为 examples/thermal-3d-anisotropic.json；取自三维已接受旋转张量材料，含合法负非对角项；所有量值/来源展开。执行后 verified-facts.json 必须来自实际 Runtime，区分 execution、numerical/scientific、real_computation、单位、来源和适用性。

用户另行明确授权这次在线数据外发与一次新求解后，main可在本机用下面命令进行真实“一次计算＋同会话只读追问”验收：

```powershell
& $RvePython -m modules.rve.harness.agent_acceptance --authorize-online-and-one-solve --host-config config/local-codex.json
```

脚本调用现有 AgentHost 两轮，检查一次 task_created、一次 host_worker_requested、原任务ID相同、第二轮 computed_this_turn=false、任务全文件哈希不变。实际 conversation.md/json 由宿主导出。若初轮未完成/中断/需要确认，保留真实会话并停止，不自动重试或重新计算；需要的确认沿用公共宿主流程。

外发范围仅本轮明确授权的消息/合成输入、公共/选中模块Skill/schema/manifest与结果；不包含源码、部署文件、其他chat、凭据或全量实验报告。科学适用性仍 not_checked，模型说明不能升级QC。
