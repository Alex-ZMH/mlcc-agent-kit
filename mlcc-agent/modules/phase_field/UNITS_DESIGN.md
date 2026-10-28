# 相场单位映射设计（增量，保留旧契约）

本模块旧steady/evolve、units=dimensionless、lgd_scalar_y_v03及历史结果保持不变。新增steady_si/evolve_si：显式量值/单位→公共唯一单位核心→canonical SI→本模块物理无量纲化→既有内核；不另造单位表、不依赖fem私有包，不把旧结果补贴SI标签。现已消费docs/units-contract.md规定的mlcc/units.py 1.0.0 normalize_fields线协议，规范输出为payload/records/core_version。

## 推导与最小独立尺度

物理电焓密度 f=a P²/2+b P⁴/4+κ|∇P|²/2−ε|∇φ|²/2+P∂yφ，TDGL ∂tP=−M δG/δP；G=∫f dV（2D为单位面外长度积分）。设x=ℓ x*, P=P0 P*, t=T t*, f=f0 f*。

保持P∂yφ的无量纲系数恰为1，须φ0=f0ℓ/P0，E0=f0/P0，D0=P0。因此最小独立集合为正有限ℓ[m]、P0[C/m²]、T[s]、f0[J/m³]，每项有显式来源。不能猜长度/时间/材料尺度。所有派生尺度也必须正有限且可逆，溢出/下溢拒绝。

| 关系 | SI单位 / 意义 |
|---|---|
| a*=a P0²/f0=−1 | a=−f0/P0²，J m/C² |
| b*=b P0⁴/f0=1 | b=f0/P0⁴，J m⁵/C⁴ |
| gamma*=0 | gamma=0，J m⁹/C⁶ |
| M*=M f0 T/P0²=1 | M=P0²/(f0 T)，C²/(J m s) |
| g*=κ P0²/(f0ℓ²) | κ单位J m³/C² |
| epsilon*=ε f0/P0² | ε为绝对介电系数F/m；不是epsilon_r |
| E*=E P0/f0 | E单位V/m |
| φ=φ0 φ*，P=P0 P*，D=P0 D* | V，C/m²，C/m² |
| G2D=f0ℓ² G* | J/m；没有厚度不能输出总J |
| G3D=f0ℓ³ G* | J |

profile固定alpha*=-1、beta*=1、gamma*=0、L*=1，表示由给定尺度限定的一族四阶材料模型，不接受任意SI Landau系数或任意mobility。SI系数由尺度推导并公开，不能称为已标定BaTiO3。epsilon_r目前不作为输入，避免与绝对ε双重定义冲突；如未来支持，须唯一明确ε0来源和互斥规则。

## 接口、边界与产物

SI入口operation为steady_si/evolve_si，units=SI，固定model_profile。reference_scales含length、polarization、time、energy_density，均为{value,unit,source:{kind,reference}}；科学参数g（κ）、epsilon（绝对ε）、applied_E及初态/时间中有量纲值采用相同显式量值结构。网格计数、seed、modes、max_halvings和输出开关仍是数值/离散字段。固定域按ℓ缩放，不新增可配置域。uniform/random幅值和reference按P0、wall/nucleus长度按ℓ、时间按T无量纲化。source记录声明来源，不等于独立核验来源。

分开保存原始输入、逐字段公共转换审计、canonical SI输入、solver无量纲输入、尺度与系数推导、结果映射。原始请求hash/任务身份绑定SI原输入，科学调用另绑定无量纲输入hash；不得把两者混用。拒绝缺尺度、错维度、无单位数、额外/已规范化记录、重复转换标记、冲突单位、非有限与不相容初态。

结果保持原始nd求解与QC证据，SI摘要、历史CSV/JSON、完整SI场NPZ及静态图为独立映射产物，带单位与映射来源。2D电焓J/m、3D J；未给厚度不造2D总能量。原始XDMF/HDF5/NPZ与图仍明确dimensionless，SI文件不能重写原证据。原始Gauss/反力/RT指标及所有数值QC在nd域保留，不用原1e-8容差直接评判SI残差；独立记录映射一致性检查，不升级材料或稳定性QC。

验证包括等价单位→相同SI与nd、量纲错误/缺尺度/重复转换/非有限拒绝、原JSON兼容；合成尺度仅用于映射测试，不是材料默认/标定。必要真实小型2D/3D等价算例和旧nd对照单列证据，无全量研究/在线LLM。
