# 给main的公共增强建议

当前无阻塞接入的公共接口缺口。自动发现、schema子集、queued/worker、质量和原生产物、既有AgentHost均可使用，不需修改公共包或中央Bundle。

1. queued快照未冻结宿主部署JSON/环境变量。当前执行保存deployment_sha256和实际argv，提交到worker期间须固定宿主配置。建议main增加部署快照与漂移检查扩展点，兼容旧任务，不让科学输入携带机器路径。
2. 超时仅停止Windows客户端/Adapter，不能确认WSL科学进程已停止。当前SCIENTIFIC_STATE_UNKNOWN、不自动重提交。未来取消/协调需原生进程身份与确认终止证据，不能凭退出码推断。
3. Windows深层公共AgentHost测试副本可能在原子临时文件触发MAX_PATH。用长路径前缀传入绝对tests路径已复核56项（1跳过）；建议main评估统一长路径支持，本模块不改Store/Agent。

旧任务/产物引用不变；这些增强未实现，不作为当前科学QC。

## 单位系统增量（2026-10-22）

新增SI入口steady_si/evolve_si已实施，保留原dimensionless操作。模块消费公共唯一标准库单位核心1.0.0的normalize_fields线协议（量值、单位、来源、维度校验、canonical SI审计），不复制FEM私有转换器。正式契约为docs/units-contract.md，无需扩展公共结果外壳；原输入/SI/无量纲/尺度/映射分别放专业结果与产物。

已按正式kind使用length、time、polarization、energy_density、electric_field、absolute_permittivity、gradient_coefficient。固定profile系数不开放任意Landau材料；推导见UNITS_DESIGN.md，不把nd阈值直接用于SI检查。旧操作不调用单位核心，缺公共核心只阻止新增SI入口。当前单位接入无待main实现的公共缺口；没有改Agent、Runtime、授权或其他模块。
