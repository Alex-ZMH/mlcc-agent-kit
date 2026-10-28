# 本轮执行方案

1. 审阅来源、保存 SOURCES.json 路径/版本/SHA256 与迁移说明。
2. 独立包内迁入两维内核；四个 queued 操作各自 strict schema。显式物理长度、normalized geometry、完整材料 scalar/SPD tensor 来源，缺数据拒绝。
3. 单位：Windows 原始 typed → 固定 JSON Pointer → 唯一 units.py → SI 与领域检查 → geometry mapping → WSL；三份输入/审计独立保存。
4. 独立宿主部署与 module bindings；预检只检查输入/单位/依赖/预算，实际求解一次并等待。每任务缓存独立，保留失败，不重试。
5. 轻量测试覆盖 schema/单位/SPD/失败/路径/输出与控制边界；公共回归。显式 harness 运行四操作分层基准、2D 多晶、3D 球、多单位等价，并独立回读原生场及比较接受的历史张量。
6. 同任务 status/result/artifact/终态 worker 前后哈希；离线 AgentHost schema/Skill 消费，准备后续在线闭环输入和脚本。在线 LLM 本轮 not_run。
7. ACCEPTANCE / MAIN_HANDOFF 给出真实 task_id、命令、原始误差与未检查项；只修改 modules/rve，公共 CLI 自有输出除外。

预算按实验硬上限：2D 90000 triangles / 3D 180000 tetrahedra；本机宿主显式限制、单 MPI rank、线程 1，求解超时不证明 WSL 终止。真实 harness 只取少量小网格，不重跑原全批。
