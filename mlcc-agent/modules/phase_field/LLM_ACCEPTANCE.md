# 既有LLM宿主接入

真实外发：`not_checked_no_current_chat_authorization`。不借用此前FEM授权，未新增provider/Web/Agent系统。

已完成离线核查：`python -B -m modules.phase_field.harness.check_host`。证据work/host-compatibility.json。既有AgentHost实际装载相场Skill和schema，steady/evolve均可编译严格决策schema，以provided_input＋input=null绑定原始输入。provider记录synthetic_unit_test；没有task/WSL/网络，这不是在线模型验收。

取得当前chat明确外发授权后，用既有Codex CLI gpt-6.1-sol / low运行一次闭环。以下命令当前未执行：

```powershell
$PhasePython = 'C:/Users/Xiang/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
$env:MLCC_PHASE_FIELD_DEPLOYMENT = (Resolve-Path modules/phase_field/deployment/example.json).Path
$r = & $PhasePython -B -m mlcc agent --host-config config/local-codex.json `
  --module phase_field --operation evolve `
  --message '引用这份无量纲三维核输入，执行一次相场演化并解释P/phi、电焓、原始及RT守恒证据；保留全部未检查项。' `
  --input modules/phase_field/examples/evolve_3d_nucleus.json --authorize-execution | ConvertFrom-Json
$follow = & $PhasePython -B -m mlcc agent --host-config config/local-codex.json `
  --module phase_field --operation evolve --session $r.session_id `
  --message '只读解释刚才结果：RT0是否证明CG1局部强守恒？到达终止时间是否证明稳态？不要重新计算。' | ConvertFrom-Json
& $PhasePython -B -m mlcc agent-read $r.session_id
& $PhasePython -B -m mlcc agent-export $r.session_id
```

核查恰好一次task_created/host_worker_requested、输入逐字段一致、解释来自实际task且不能改写QC；追问computed_this_turn=false、task_id相同，record与原生产物hash不变。完整实际记录为outputs/agent/<session>/conversation.md/json及route/explain文件，不伪造发生轮次。非法输入examples/invalid.json由确定性schema/预检拒绝，不依赖模型决定科学接受。

只发送本轮用户消息、明确授权输入、公共/选中模块Skill/schema/manifest、解释所需公共结果；不默认发送源码、部署、其他会话、凭据或实验报告。大数组在产物中。
