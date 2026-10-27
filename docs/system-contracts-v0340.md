# MLCC 0.34：真实原生 Born/Γ/介电链

2026-10-24，0.34.0启用冻结，0.33.0回退，源码0.35.0。本版交付显式Γ处理，以及公共原生方法/NAO/KPT和P4/P5 SCF来源绑定的兼容修复。接受用户采用的[初步标准](born-gamma-provisional-standard-v001.md)，不改变原生方法文件或以数学夹具代替真实材料源。

真实25项SCF使用scf_thr=1e-11，在v100通过Slurm、time=0、最多三张V100独立并行执行；365–389全部COMPLETED/0:0且由391确认原生收敛。对应PYATB394–418全部完成，419原始Γ、420 Born仿射族、421新旧SCF对照完成。原生6位极化输出内一致不代表1e-13物理精度。

新增Γ处理保留raw、(K+Kᵀ)/2及仅去除三维几何平移的矩阵。保留所有光学模，保存互易/左右平移残差、修正max/Frobenius、质量加权谱与光学空间响应敏感性；软模/不可逆的未决状态不得被任意截断抹去。分支整数来自主代理显式审查，不自动由中性残差或最近量子选择。

安装验收job424 COMPLETED/0:0，9秒，实际使用development/0.34.0/installed/0.34.0，六条公共命令electronic-dielectric、born-affine、gamma-process、ionic-dielectric、dielectric、deliver-properties均通过。复用390的13项新增算法检查及4条原源消费命令，不重跑旧测试或原生计算。失败363、393、422保留，修复针对各自真实错误。

| CZO局部响应（无量纲） | xx | yy | zz |
| --- | ---: | ---: | ---: |
| 电子ε∞ | 4.742272 | 4.729405 | 4.646226 |
| 离子Δε | 29.414520 | 28.128300 | 55.948901 |
| 总ε | 34.156792 | 32.857705 | 60.595127 |

完整20原子Born与非对角介电分量、来源job、单位、原子映射和同Study绑定均在[实际交付](../workspace/reports/czo-born-gamma-literature-v001/gamma-consumer/scf11-run-424/delivery.json)。Born全胞最大残差0.0032137543 e；raw声学最大绝对频率0.0038861312 cm⁻¹；57光学模84.944092–771.245037 cm⁻¹。raw与处理后光学响应最大差6.75012e-6，无量纲。

适用范围为指定未弛豫CZO几何、固定晶胞、零宏观电场、无NAC的局部响应；参考最大力0.1179016229 eV/Å。位移/k网格/基组、平衡材料、未采样连续性和烧制温区资格未完成。科学/生产资格和完整系统完成均false；不能表述为平衡陶瓷或高温介电。

registry、MCP和本地Python均绑定0.34。安装时系统临时目录权限失败已保留，改用工作区内临时目录完成离线绑定；没有本地数值工作。第三窗口显式自训练势入口已通过job423源验收并获主线审查，单列0.35候选，不混入本次快照；下一项仅补实际安装路径与依赖绑定，复用旧训练/MD。

[发布判定](../workspace/reports/czo-born-gamma-literature-v001/release-acceptance.json) · [安装运行证据](../workspace/reports/czo-born-gamma-literature-v001/gamma-consumer/scf11-run-424/acceptance.json) · [版本保留](version-retention-policy.md)
