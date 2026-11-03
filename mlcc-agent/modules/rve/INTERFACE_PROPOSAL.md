# 公共能力建议

2026-11-03 / 0.1.5：进一步移除 2D h≥0.003 / 3D h≥0.025 的人为细化下界，公共 schema 允许非负数，模块 geometry 和真实建网入口共同强制有限正 h；原薄层分辨率、材料、质量和回读继续检查。规划数量估计使用精确分数，避免极小 h 的浮点上溢/下溢把软估计变回拒收。四个操作与原生接口保持兼容，当前验收与来源改由 MESH_COUNT_* 增量文件记录，不改写 0.1.4 验收。

2026-11-03 / 0.1.4：二维多晶支持 GB 宽度 0..0.08，零值不创建 3000 相；不改变材料或壳/孔定义。现有 deployment 的 `max_cells_2d` / `max_cells_3d` 及内部 science 请求的 `max_cells` 只作推荐，保留名称兼容宿主，去除数量上界和数量拒收。Adapter 继续使用 interface_version=1.0；专业输入与结果 schema 不变。规划估计写入预检 checks，超推荐写入 warnings，实测计数和推荐写入已有 diagnostics.mesh。无需修改公共创建器、调度或主 Bundle。旧已暂存任务的 payload 不会自动获得本次改动，部署和原任务处理另行明确。

当前四项固定宏观基载荷操作无阻塞公共缺口。沿用 mlcc.module.v1 / interface_version=1.0、当前受限 schema 和唯一 UNIT 核心，不要求公共代码修改。

后续如确需任意温度梯度，应独立定义 temperature_gradient / K/m 及增量单位/语义；如确需任意带单位取向，应定义 angle，并区分几何旋转和晶体本构旋转。本轮固定基载荷、固定几何角度，不自建 K/mm 或 deg/rad 表，不将这些量塞进其他 kind。

非阻塞宿主增强：queued 快照未来可冻结独立 deployment 内容/哈希，避免环境变量在 submit 与 worker 间漂移；外部 WSL 进程需有可证明终止的取消/核对协议。当前模块 launch 保存实际配置/argv/PID/哈希，超时状态明确 unknown，无自动重提交。旧结果读取不需改变。

公共原始输入采用带 region_tag 的严格材料条目数组，满足 AgentHost 的 bounded strict 输出编译器；相同标签重复或缺失由确定性 Adapter 拒绝。规范 SI 与有效材料文件内部仍以区域标签映射表达，effective schema 的 additionalProperties 使用公共已支持子集。无需修改宿主或扩展 oneOf/$ref/$defs。
