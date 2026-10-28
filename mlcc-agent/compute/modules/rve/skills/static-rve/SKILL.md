---
name: mlcc-static-rve
description: Prepare and interpret independent 2D/3D static electrostatic or thermal RVE homogenization through deterministic queued operations.
---

# 静态 RVE 方法

操作为 homogenize_electrostatics_2d、homogenize_thermal_2d、homogenize_electrostatics_3d、homogenize_thermal_3d。选定维度和物理，2D 实际 x/y 两载荷与 2×2 张量；3D x/y/z 三载荷与 3×3 张量。请求不改变部署、不指定 shell/解释器。

必需输入：physical_lengths 显式量值（2D 正方形，3D 长方体）、normalized_h、geometry kind 及该种几何专属参数、pore_fraction、materials 严格条目数组、boundary_condition 与 pore_model。每个材料条目有 region_tag（如"10"）、representation、applicability 和 scalar 或 tensor；标签不能重复且必须精确覆盖。不要生成以动态标签为键的公开材料字典。量值严格 {value,unit,source:{kind,reference}}，来源不能为空；示例全部 synthetic_test，不能称实测。材料 isotropic/scalar 或 tensor，张量逐元素显式量值。相对介电率固定 relative_permittivity / 1；F/m 不是该输入。导热支持 W/(m K)、W/(cm K) 等公共登记表示。Windows 唯一 UNIT 核心规范化，LLM 不换算/判断 SPD。

normalized_*、jitter、fraction 是无量纲，不能附物理长度单位、不能隐式百分比；grain_count/seed 是非 bool 整数。每种几何只接收确切相关字段，缺材料/尺寸先澄清，不补实验默认值。多晶取向仅元数据，不等于晶体本构旋转。三维 GB/shell 多晶当前拒绝，extrusion 未开放；不能改换组织继续算。

支持均匀、层状、2D 旋转层/圆/椭圆/核壳/周期多晶、3D 球/椭球/核壳/无GB多晶。角度不开放任意单位，椭圆/椭球当前固定零角度；旋转层法向为原实验固定 (1,1)/sqrt(2)。孔隙只单内部圆/球；热 insulating_cavity 排除孔单元/自然绝热，以完整单胞归一化；explicit 是正系数孔相；静电必须 explicit。所有区域仍需材料记录，绝热孔材料记录为身份审计，不参与导热求解。

周期法是 DOF 等价类 P 消元与常数规范，Gmsh setPeriodic 只配对网格。affine_dirichlet 是独立仿射边界参考。每个宏观载荷固定 eye(d)，电场为 1 V/m，热负温度梯度为 1 K/m、参考 300 K；不是任意可配置工况。网格 MSH 坐标归一化，VTU/XDMF/HDF5/NPZ 坐标 m，映射见 coordinates.json。2D 均质材料量仍 F/m 或 W/(m K)，无虚设深度或 z 分量。

先 preflight，只证明输入/环境/预算可执行；run --defer 创建任务，worker 等原生进程结束一次才收集结果。status/result/artifact 与终态 worker 只读，不重算。SCIENTIFIC_STATE_UNKNOWN 或 interrupted 要人工核查 WSL 进程，不重试、不删锁，不把提交或退出码 0 当成功。

解释先 execution，再 evidence_kind、numerical/scientific 各检查与原始误差、来源。有效文件 effective_material.json，独立回读 readback.json、逐载荷场/metrics 与 diagnostics。已保存场重新计算梯度/本构/均通量/功/PBC，而非只读 PASS。原始 DG0 通量跳跃是诊断，弱反力平衡不是 H(div) 强守恒。层状周期接缝可以有真实材料迹跳变。

数值检查通过不代表单任务 mesh convergence、统计代表性、真实材料标定或器件适用性，均按实际 not_checked；历史实验 PASS/PARTIAL/EXPERIMENTAL 不转为当前任务 passed。合成材料真实 FEM 属 real_computation，不能称经标定产品预测。只读追问复用当前会话 task，computed_this_turn=false，不新提交。在线 LLM 验收本轮 not_run，离线 schema 测试不是模型闭环。
