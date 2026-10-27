# 带电SCF真实任务与0.10候选集成

2026-10-22，提交前声明。用户授权真实带电SCF、GPU优先、按收敛标准验收。机器可读协议：[protocol](../workspace/configs/charged-scf-native-protocol-v001.json)。

复用已选CaZrO3 Pnma源模型，仅删除明确的氧atom_id=8并指定q=+2；19原子Ca4/Zr4/O11。该位点和电荷是本次系统验证实验的显式选择，不表示已确认最低能缺陷、稳定电荷态或生产掺杂。母体来源、原子谱系及未弛豫身份保留。中性价电子154，请求移走2电子，原生目标152。

固定胞/固定离子SCF采用同一套ONCV/PBE资源、非SOC、nspin1、fixed、88带、symmetry=-1、GPU cg、Broyden mixing_beta=0.3。预先设scf_thr=1e-8、scf_nmax=200，达到迭代上限但未收敛不通过。静态SCF不要求离子力为零，也不宣称离子弛豫通过。

三点为100Ry/2×2×2、120Ry/2×2×2、120Ry/3×3×3；顺次运行，每点1GPU、1MPI、1CPU、8GiB，Slurm time=0。不修改历史兼容性方法。两对分别检查截断与k网格加密，要求总能变化不超过1meV/atom，最大逐原子力矢量差不超过0.02eV/Å。阈值仅用于这一固定几何的原始E/F数值分辨率，不作为缺陷形成能、势拟合或全材料精度标准；不测温度矩阵，不重复中性Berry。

执行验收要求原生Slurm终态、实际GPU运行、INPUT回显、SCF收敛标记/最终DRHO、AUTOSET中性电子数、nelec_delta、nelec now、全k点占据积分、有限总能/力/应力和模型/方法身份全部一致。软件结果仍保留raw_charged_scf_unqualified与材料科学/生产资格false；独立实验记录分别报告执行、电子收敛和本实验E/F加密判据。若某项失败，保留失败并只修明确的软件错误，不调整科学参数追求通过。

0.10集成复用既有测试与同一套原生输出，只补真实带电路径及安装副本中新增入口的检查。0.9冻结包保持原样；只有候选安装/宿主入口证据齐备后才能更新实际启用版本。带电形成能、局域势、VBM/介电/FNV、尺寸收敛、Berry GPU及材料势科学资格继续单列。

## 13:48 明确审查后的单点加密

job75/76/77全部原生电子收敛、电子数154→152一致。job78在v100完成真实解析，截断差0.187793meV/atom、0.00262724eV/Å通过；222→333差3.716246meV/atom、0.02627837eV/Å均未满足声明标准，原始失败保留。

依据用户要求完成实际收敛验收，主代理审查后显式声明[protocol v002](../workspace/configs/charged-scf-native-protocol-v002.json)：只增加120Ry/444一个GPU点，与已有333比较，其他参数及1meV/atom、0.02eV/Å阈值完全保留。这是有失败证据支持的新收敛实验，无自动循环、无旧任务重算、无阈值放宽；若仍不满足，记录缺口而不自动追加网格。cutoff证据仍限222上的100→120Ry，不能外推为全部数值误差或材料生产资格。


## 最终结果

job80完成GPU SCF，15步电子收敛、drho=4.48699871134e-9、152电子，Slurm COMPLETED/0:0、UNLIMITED。job86从0.10.0安装副本验收通过：333→444差0.169479378meV/atom和0.003098109685eV/Å，均满足原标准；cutoff/222证据复用，原job78失败保留。MCP与原版MatterAI宿主通过，0.10.0已启用。见[安装原生验收](../workspace/reports/system-v0100/installed-charged-86/acceptance.json)、[总交付](../workspace/reports/system-v0100/acceptance.json)。这是限定raw SCF与局部加密的验收，不能外推为带电形成能、介电/FNV或整个材料体系生产资格。
