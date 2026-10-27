# P5 保存 Born／Γ 模态的离子介电贡献

2026-10-26。承接P5.05/P5.06/P5.10与P12.08的响应来源交付。现有系统给总离子张量和Γ本征模，但没有逐模Born耦合与离子响应贡献。此次只开发这一输入已就绪的功能，沿现有CLI/Study交付，不新增来源框架。0.48安装副本已封存，源码改动进入下一0.49候选。

## 输入与科学合同

显式请求绑定同一Study的保存Born、显式处理Gamma以及保存ionic产品。CZO复用424的born-reviewed.json、gamma-processed.json、ionic.json；BTO复用524的born.json、gamma.json、ionic.json。只消费JSON，不重读DFT、拟合力常数、执行Gamma对角化、重算现有ionic解或改变分支。保存源及job编号、方法、结构、原子顺序、质量、体积和机械/电边界必须相符。

读取Gamma `explicit_processing.spectra.optical` 的完整3N−3个保存质量加权本征向量e_s及特征值λ_s，保留原顺序、符号、负模和已有本征基。设原始Born矩阵Z为3×3N，M为逐坐标重复的原子质量（amu），T为保存的三个欧氏归一化刚性平移，P=I−TTᵀ。先u_s=M^(-1/2)e_s；显式采用u_s^0=P u_s作为与既有欧氏光学空间响应一致的位移规范。输出原u_s、u_s^0及投影改变量。不得改写或中和Born张量；同时保留Z u_s和Z u_s^0及Born和规则残差，明确两者区别。

对完整稳定光学空间，λ_s必须为保存字段`eigenvalue_eV_per_A2_per_amu`，单位eV/(Å²·amu)，不能用频率或频率平方冒充。定义z_s=Z u_s^0（e/sqrt(amu)）、S_s=z_s z_sᵀ（e²/amu），模式无量纲介电增量为 `(elementary_charge * 1e10 / (epsilon_0 * volume_A3)) * S_s / λ_s`。只计算新模式分解，并将总和与已保存ionic.delta_epsilon_ionic比较，保留差值及最大绝对差；工程闭合采用atol=1e-8、rtol=1e-8，不将其当材料收敛门。该规范对应已采用三平移投影的伪逆响应；参考[Wu/Vanderbilt/Hamann式14与三平移零空间说明](https://arxiv.org/html/cond-mat/0501548v2)。原始几何未弛豫的限制不改变。

逐项语义明确为“保存的质量加权Γ本征基，经欧氏平移位移规范处理后的响应分解项”，不是重新求出的受约束独立本征模。Pu_s一般不是Kc的本征向量，不重新归一化或旋转它。非中性Born时，raw耦合是平移规范敏感的诊断量，不能称物理静态介电；规范后总和对应既有欧氏光学伪逆。单位与这一定义必须进入产品，不仅写在文档。

若任一光学λ≤0，保留全部频率、向量、耦合与振子强度，所有模式介电增量及总和为null，注明光学空间不稳定或不可逆；不删除软模、取绝对频率或只求正模之和冒充静态响应。保存ionic为null的其它原因也保留，不以该功能绕过源状态。不能从Γ模态推出有限q DOS、Cv、热导或耗散；不引入阻尼/频率扫描。简并空间中单模贡献依赖保存本征基，只有完整简并子空间和有不变含义，不自动旋转或重排序本征向量。

## 最薄实现与所有权

原实施窗口独占新`dielectric_modes.py`及其新测试、CLI `dielectric-modes --request --output`、`deliver-properties --dielectric-modes`和必要保存交付分支。不得修改现有gamma_processing/dielectric_response领域算法或旧产品。直接复用已有方法/几何/Study绑定helper，必要的数据一致性检查不能变成新框架。root负责合同、源证据、静态审阅、Slurm预算和验收。第三窗口仅进行已封存0.48安装，不共享修改源码。

建议单一请求schema `mlcc.dielectric-modes-request.v1`，显式study/born/gamma/ionic路径及`displacement_gauge=euclidean_translation_free`；产品schema `mlcc.dielectric-mode-response.v1`。完整输入错误直接报原始错误，源未决保留unresolved/null。保存交付只复制结果，不再次计算。新测试聚焦质量/方向单位、非中性Born的位移规范、简并基不变性、负模保留、源绑定和保存交付；数学样例不是材料来源。

新增验收预算：v100 Slurm CPU1、0GPU、4GiB、5分钟、no-requeue，一个job合并新检查、CZO和BTO保存源的首次新模式分析及公共同Study交付。只读既有原生证据，不重跑365–424、464–524、531–533或旧检查，无DFT/MD/训练/温度或精度矩阵。一次验收后记录真实终态，缺项不标完整P5或材料资格。
