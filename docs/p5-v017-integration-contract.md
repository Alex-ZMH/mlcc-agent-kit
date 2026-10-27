# P5 0.17候选：分支审查、Born汇总和介电贡献

**交付更新21:58**：本合同的软件消费范围已由192/193/194/195及安装197验收，0.17启用冻结、0.16回退、源码0.18。原生Γ的P7/Berry方法来源字段仍未接通，当前Γ验收为software_math_only；真实完整Born和电子来源仍缺。以下保留实施合同及当时所有权，后续修改由root重新分派。

2026-10-22。0.16启用冻结、0.15回退；本候选未验收。主线拥有分支审查/原生来源适配/CLI/集成，既有实施聊天独占dielectric_response.py、test_dielectric_response.py和workspace/reports/dielectric-response-v001。双方不修改对方文件。缺陷VBM/势对齐留后续队列。

| 物理量 | 软件环节 | 当前真实输入缺口 |
| --- | --- | --- |
| Born单列 | 已有berry-response把三gdir的显式分支有限差分转为一原子一位移方向的三分量列；本次补审查建议与显式审查记录绑定 | 188只有atom8/x的两点；缺跨位移分支依据，Born列null |
| 完整Born | 将同父胞/同方法所有atom_id的x/y/z列按Z[kappa,alpha,beta]汇总，列缺失单独列出，禁止补零/隐式对称填充 | CZO20原子需要60列；当前0列可用。工程单点数据不能伪装成完整集合 |
| 电子epsilon_infinity | 同方法/同几何固定离子电子张量的来源消费；本机原生producer需精确版本支持 | 3.10.1 tag未发现PW DFPT/体均匀场/epsilon0_pw路线；slab锯齿场、隐式溶剂和LCAO光谱不能替代 |
| 离子介电增量 | 完整Born和Γ解析部分固定胞E=0 Hessian的矩阵运算；P7现有有限位移力常数需显式Γ映射适配 | 现有原生结果没有完整同模型Born与位移力集合；数学输入可算，材料结果暂缺 |
| 总静态介电 | 同边界epsilon_infinity + ionic_increment；固定应变与自由应力分开 | 缺电子或离子项时总量null；不把固定胞结果称为自由应力/有限温介电 |

## 最小数值合同

Born采用无量纲电子电荷单位：Z[kappa,alpha,beta]=(Ω/e) dP_alpha/du_kappa,beta。alpha为极化笛卡尔方向，beta为位移方向。保留每列的response_id、源文件、±NSCF与SCF任务/job、分支声明及科学资格；使用既有values_e，不重新求Berry有限差分。期望的原子集合来自明确parent Model，不能由“已经有几列”推断完整性。

Γ Hessian按atom-major Cartesian自由度排列，K[(kappa,beta),(lambda,gamma)]，单位eV/angstrom^2；固定胞、宏观E=0，显式nac=not_applied。这里analytic指非长程非解析项，不等于DFPT；有限位移力常数也能生成。新增P7适配只从现有完整force_constants、原plan和Phonopy映射得到Γ矩阵，不重新拟合力常数，不创建位移DFT。

Γ来源JSON为mlcc.gamma-force-constants.v1，含parent{study_id,study_path,model_id,model_version,model_path}、atom_ids、cell_angstrom、volume_A3、unit=eV/angstrom^2、matrix_basis=parent_atom_major_cartesian、matrix_eV_per_A2、method_identity、electrical_boundary=fixed_E_zero、mechanical_boundary=fixed_cell、nac=not_applied、source{harmonic_result,plan_manifest,force_bundle/native_refs}、qualification。primitive与parent胞不一致时首切片直接拒绝，不自动重新编号或把超胞体积当原胞体积。几何、质量、体积和动力学矩阵虚部容差分别显式给出，不能用长度容差的立方冒充体积误差传播。方法/Study必须能追溯原生来源，数学fixture明确标software_math_only，不能伪装ABACUS来源。

离子相对介电增量：Δε_ion=e²/(ε0 Ω_m3) Z K_SI^+ Z^T，Z展平成3×3N；K_SI=K_eV_A2*(1.602176634e-19)/(1e-10)^2。它不需要epsilon_infinity先存在。总固定应变相对介电ε_static=ε_infinity+Δε_ion，不再额外加I，避免重复电子背景。

只显式移除三个均匀平移自由度；在其正交补中检查/求逆。记录K平移残差、对称误差及Born电中性残差。残差容差和最小正光学刚度阈值必须由请求明确提供；不能把负/近零光学模截零后产生有限稳定介电，也不能无声明对Born或K修正ASR。电子张量缺失时只缺总量；力常数/完整Born缺失时离子增量null。输入齐全且物理前提成立时必须真正算出张量，科学资格仍由独立证据决定。

公式与平移子空间处理参考[Wu、Vanderbilt与Hamann 2005，式14及后续伪逆定义](https://arxiv.org/pdf/cond-mat/0501548)；力常数/动力学矩阵单位和NAC含义参考[Phonopy公式](https://phonopy.github.io/phonopy/formulation.html)。本站软件版本与原生支持另见p5-native-response-capability-20261022.md，文献不替代本机能力。

## 分支审查接线

主线berry_branch_review只消费188已有响应结果。k=n_plus−n_minus，候选delta=(P_plus−P_minus)+kQ；最近整数与邻整数只是审查建议。等距/半量子歧义阈值显式保存，Q不一致则拒绝。严禁自动写入绝对分支或从两端点推断绝缘路径。

显式审查记录绑定response_id、parent、target、gdir、±point/task/job、原始P/Q，以及reviewer/reviewed_at/decision_basis/evidence_refs。deferred/rejected保持null；approved必须声明每方向±整数、基准和绝缘路径证据引用。消费成功只表示审查声明已绑定，绝不自动升级branch_continuity_qualified或科学资格。真实188本轮只创建deferred记录并保留原结果。旧berry-response算法及入口不重写。

## 验收与范围

所有数值后处理和算法测试通过v100 Slurm。各独立切片预算1 CPU、2GiB、2分钟；无新DFT/训练/MD。复用188验证真实缺失与来源消费；完整数学输入验证矩阵运算、单位和缺/错身份路径，明确只能证明算法。最终只补改变接口的公共集成，不重复冻结0.16/0.15或已有187/188。当前科学输入缺口不能写成完成，也不能阻止可实现软件环节。
