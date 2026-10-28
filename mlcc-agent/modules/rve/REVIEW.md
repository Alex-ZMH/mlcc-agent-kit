# RVE 迁移审阅（2026-10-23）

依据当前 docs/rve-development-prompt.md、公共架构/协议/开发/首版/单位/AgentHost 文件及两个实验源码；不使用其他 chat 历史。当前模块仅有 0.0.0 未接入登记。工作区无可用 Git 仓库，采用文件 SHA256 记录来源与交付。

保留两个维度的 MicrostructureBuilder → RVEMesh → PhysicsAdapter → Homogenization → 独立 VTU/HDF5 回读分层。周期场使用 P1 等价类消元与常数规范，不以 Gmsh setPeriodic 代替。三维六面/棱/角类保持原算法。静电相对介电率到绝对介电率是原物理 EPS0 映射；导热孔的 full-cell 平均不变。

实验 cases.py / run_case.py 只读参考，不迁入正式调用链。所有材料张量在示例中展开，正式输入只接受精确区域标签映射，不使用角色默认覆盖或按 grain ID 派生材料。取向仅元数据，不宣称晶体旋转。规范几何参数明确无量纲；物理长度经唯一共享核心处理。宏观基载荷固定 eye(d)，热参考 300 K，未开放梯度或角度单位。

Windows 标准库承担 strict schema、显式字段映射、shared normalize_fields、SPD、预算及部署；WSL 只接收 canonical 数据并求解。已只读核实 Ubuntu-24.04 / 指定 Conda Python 3.11.15、DOLFINx 0.11.0、Gmsh 4.15.2、NumPy 2.4.6、PETSc 3.25.5 real float64 / rank=1。未安装或升级。

历史接受清单只作来源证据，新任务逐个重新求解与回读。数值 PASS 不代表统计代表性、材料标定、器件适用性或每任务网格收敛。薄层分辨率及单元护栏保留；3D 复杂 GB/shell 多晶先拒绝，避免有限历史验收成为默认承诺。
