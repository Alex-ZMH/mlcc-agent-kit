# 晶界来源进入原生任务：0.16已交付范围

186公共Study、189静态来源、190共享创建器接线及191安装消费均已COMPLETED/0:0。0.16已启用，0.15回退。

- create_abacus_task和create_lammps_task调用同一stage_grain_task_sources，校验已绑定的Study/Model，把两份静态JSON和binding放入任务，加入transfer_paths，不加入collect_paths。
- parse_abacus_task和read_lammps_task调用read_grain_task_sources，将原Study块、输入构建谱系和任务内来源路径传入结果。静态来源读取不打开原控制端路径；原有解析器对Model的正常依赖未被取消。
- ABACUS发生任务应变变换时，静态谱系仍绑定原Model，不冒充最终弛豫结构。
- 190复用174的40原子Ni模型和186 Study创建输入，未提交引擎。原4原子方法nbands=56不能照搬，主代理明确将验收副本设为560，原方法文件不变；这是输入规模适配，不是精度收敛。
- 两份任务迁移后的静态来源已读回；解析器字段转发使用明确software stub，仅证明代码接线，不是原生晶界结果。
- 191只从安装副本消费190已有来源，不重建模型、输入或重跑stub。MatterAI实际0.16宿主和本地Python/MCP绑定通过。

真实晶界DFT/MD、弛豫和材料资格尚未执行。未扩展Berry晶界，未代选生产相/掺杂、自动弛豫或重新训练。证据见workspace/reports/system-v0160/acceptance.json。