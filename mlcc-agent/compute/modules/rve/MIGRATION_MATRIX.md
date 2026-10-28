# 迁移矩阵

|来源能力|处理|本模块范围|
|---|---|---|
|2D homogeneous/layers/rotated_layers|算法原样，接口适配|明确 fraction/axis；旋转层法向固定原实验 45 度|
|2D circle/ellipse/core_shell|算法原样，接口适配|normalized radius/aspect/shell，ellipse 固定 angle_rad=0；任意角度待公共契约|
|2D periodic polycrystal|算法原样，接口适配|4/9/16/25/36，显式 seed/jitter/GB/shell，全区域显式材料|
|3D homogeneous/layers/sphere/ellipsoid/core_shell|算法原样，接口适配|normalized center/axes/radius/shell；固定无旋转|
|3D 无 GB/shell polycrystal|算法原样，接口适配|8/12/16/20/27，逐区域显式材料|
|3D 实体 GB/shell polycrystal|拒绝公开入口|历史仅 N8 单网格 PARTIAL；保留来源代码，不宣称普遍验收|
|3D extrusion|不迁移公开入口|实验跨维 fixture，不引入任意多面体/跨模块参数注入|
|显式低导热孔 / 静电孔|保留|孔相正 SPD，材料与覆盖显式|
|热绝热 cavity|保留|排除孔单元，完整单胞面积/体积平均；孔材料仅几何身份，不参与求解|
|periodic / affine_dirichlet|保留|后者独立参考，不声称 PBC|
|cases.py 默认材料与规模|不迁移|仅示例生成时展开已公布 synthetic 值|
|图像/报告/历史缓存|不迁移|原生场足以审阅；无新 viewer|

单任务 mesh convergence、统计代表性、实测标定、BaTiO3/器件适用性统一 not_checked。支持入口与本轮实际验证范围分别记录 ACCEPTANCE.md，不把未运行组合写 passed。
