# 公共能力建议

当前四项固定宏观基载荷操作无阻塞公共缺口。沿用 mlcc.module.v1 / interface_version=1.0、当前受限 schema 和唯一 UNIT 核心，不要求公共代码修改。

后续如确需任意温度梯度，应独立定义 temperature_gradient / K/m 及增量单位/语义；如确需任意带单位取向，应定义 angle，并区分几何旋转和晶体本构旋转。本轮固定基载荷、固定几何角度，不自建 K/mm 或 deg/rad 表，不将这些量塞进其他 kind。

非阻塞宿主增强：queued 快照未来可冻结独立 deployment 内容/哈希，避免环境变量在 submit 与 worker 间漂移；外部 WSL 进程需有可证明终止的取消/核对协议。当前模块 launch 保存实际配置/argv/PID/哈希，超时状态明确 unknown，无自动重提交。旧结果读取不需改变。

公共原始输入采用带 region_tag 的严格材料条目数组，满足 AgentHost 的 bounded strict 输出编译器；相同标签重复或缺失由确定性 Adapter 拒绝。规范 SI 与有效材料文件内部仍以区域标签映射表达，effective schema 的 additionalProperties 使用公共已支持子集。无需修改宿主或扩展 oneOf/$ref/$defs。
