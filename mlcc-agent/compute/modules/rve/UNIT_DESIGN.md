# UNIT 设计与验收边界

唯一转换器为 Bundle/mlcc/units.py，通过 Windows `[sys.executable,'-I',absolute_core]`、shell=False 调用 catalog/normalize_fields，core=1.0.0，记录实际 catalog_version，不锁死词表 1.1.0。RVE 没有倍率表、别名解释器、pint 或本地 fallback；核心缺失、超时、坏 JSON、错误、版本/维度/语义不兼容均结构化拒绝。

physical_lengths 每分量固定 length→m；材料 scalar 或 tensor 每分量固定 relative_permittivity→1 / thermal_conductivity→W/(m K)。不能让用户选择 kind，F/m 或相场 reduced epsilon 不接受在 relative 输入位置。来源要求非空 kind/reference。源内核 ε=ε0εr 的 EPS0 保留为物理关系，不是单位换算。允许 SPD 的负非对角项；只按矩阵正定判断，非逐元素正值。

normalized_h / normalized_fraction/radius/axes/center/GB/shell、jitter、pore_fraction 为原构建器无量纲参数，保持原数值，不乘 length。grain_count/seed 是整数/count/seed，拒绝 bool、unit 容器。2D 正方形长度，3D 三轴独立长度；physical 映射 `x_i[m]=normalized_x_i*physical_lengths_i[m]`，不开放第二套厚度/半径定义，避免冲突。

保存 input.original.json（用户原文数据）、input.canonical-si.json（量值变数值，材料列表按唯一 region_tag 映射为内核所需字典）、unit_normalization.json（逐字段原表示/来源/单位/core/catalog/转换审计及 material_rows 列表索引到区域标签映射），再独立 input.kernel-normalized.json 与 coordinates.json。先验证 shared normalize_fields 完全不改未声明字段，再做区域身份映射；这不参与任何单位计算。Runtime 输入不预改，WSL 只读 SI，不按 raw unit 第二次缩放。每量审计可用同核心 normalize 重放。

本轮固定 eye(d) 基载荷，E=1 V/m 或 −gradT=1 K/m，温度场参考 300 K；没有可配任意梯度、角度、温度/温差输入。temperature 与 temperature_delta 不能互混，C 不能解释为摄氏。新增 temperature_gradient/angle 公共 kind 须先提案，本轮不自建转换或扩展模型。

归一化 MSH 坐标不等于米；原生 VTU/XDMF/HDF5/NPZ 为米。2D 面积平均的 ε/k 单位仍 F/m、W/(m K)，未引入 1 m 深度，未算 z 不输出。微宏观功为密度，原生静电半能量密度与热梯度功语义保留。

二维原生VTK/XDMF文件沿用来源的三坐标嵌入及向量格式零填充；第三列是文件格式嵌入，不是z向载荷或物理响应。专业JSON、有效材料张量和独立载荷始终只有x/y，回读只使用实际两个物理分量。

轻量测试覆盖 μm/µm/um/nm/mm/m、W/(cm K)、张量逐分量、原输入不变与审计 replay、错误与核心失败；真实 harness 比较四组 2D/3D 单位等价 canonical/tensor/全部原生场，结果写 UNIT_ACCEPTANCE.md。离线测试不能替代真实 FEM 回读。
