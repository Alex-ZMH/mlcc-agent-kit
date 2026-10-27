# 0.20 静电势输出与原生来源合同

2026-10-23。0.19保持冻结，0.20候选。以既有 `workspace/reports/abacus-potential-source-audit-v001/report.md` 的3.10.1源码/安装配方审查为依据，不重做审计。

## 所有权及入口

主线负责合同、abacus.py/abacus_tasks.py、共享CLI、集成与发布；Luna在明确所有权内实现writer和定向测试。既有实施聊天独占新增electrostatic_potential.py、test_electrostatic_potential.py及workspace/reports/abacus-electrostatic-potential-v001/。主线证据单独放workspace/reports/electrostatic-source-integration-v001/。不建立新runner、任务框架或缓存。

方法配置的顶层 `output_control: {"out_pot": 2}` 是唯一请求位置；未给该项则不改变既有输入。不是AbacusParameters收敛参数。误放到parameters的out_pot必须报错，顶层out_pot或request的out_pot/output_control亦明确拒绝，不能静默丢弃。只支持整数2，不接受bool、1、3或其他值。prepare_abacus接同名可选mapping并下传_input_text。

本切片限定ABACUS3.10.1、PW、NC、SCF固定胞、非SOC共线nspin1/2，无场/偶极/栅极/溶剂；writer显式写 `out_pot 2`、`out_interval 1`、`efield_flag 0`、`dip_cor_flag 0`、`gate_flag 0`、`imp_sol 0`、`use_paw 0`、`vl_in_h 1`、`vion_in_h 1`、`vh_in_h 1`。不得将误放在parameters的这些输出/物理控制静默投影掉。请求势输出必须有现成NC输入资格，沿用既有赝势header证据，不增加PP探测任务。弛豫/NSCF/施加应变的输出请求本轮拒绝。

method.json保存同名output_control；method和TaskRecord均增加requested_artifacts.electrostatic_potential，字段固定为schema=mlcc.abacus-electrostatic-output.v1、relative_path=OUT.<suffix>/ElecStaticPot.cube、kind=local_ionic_plus_hartree、value_unit=Ry、geometry_unit=Bohr、native_output_observed=false、native_GPU_accepted=false。它是预期产物，实际状态由来源reader另存结果，不回写历史输入。已有OUT目录收集包含此精确产物，不另行重复传输目录内文件。

## Reader API与结果

实施模块提供 `read_abacus_electrostatic_cube(path)`，仅解析固定版本cube布局，不声称原生来源；以及 `read_abacus_electrostatic_task(task_path)`，消费真实TaskRecord/result/method/INPUT/OUT.INPUT/KPT/STRU/atom-map/model与精确cube。主线加薄CLI `electrostatic-potential --task <task.json或目录> --output <JSON>`，不在reader中提交、重跑或读取其他job代替。

cube合同：两行注释、正原子数、Bohr原点和三组正网格数/完整step向量、元素序原子行（原子序数与UPF价电子数）、恰好nx*ny*nz有限标量；z最快、y次之、x最慢。保留原始shape/origin/三step向量及atom-map映射，允许非正交胞。原子/晶胞核对按原生6位小数头的量化容差，不能用k点网格猜空间网格。若提供单位换算，显式记录3.10.1的Ry_to_eV=13.605698和现有Bohr换算常数，不能混成Hartree或伏特。

原生来源adapter要求自身任务真实Slurm COMPLETED/0:0及result和原生日志电子收敛，实际INPUT/OUT.INPUT确为out_pot2及上述限定flags。核对任务模型、Study、方法、模型原子/atom-map/晶胞与cube以及原生日志版本。读取本任务输出，不允许SPIN*_POT、CHG、费米差或总能差替代。来源已验的native_output_observed=true；native_GPU_accepted只在真实device=gpu且来源检查通过时true，CPU和数学样例不能设为true。科学/生产资格始终false。

kind=local_ionic_plus_hartree，符号为电子势能；Hartree G=0为零，离子局域赝势G=0项保留，总场未减均值/EF/真空值。明确不含XC与非局域赝势。一个宿主势不建立公共势零点、FNV/eFNV、对齐或带电形成能，这些字段null。

纯cube解析的数学例与原生适配器工程fixture只能验证算法/软件，不替代原生输出/GPU。新势及若同时需要的电子参考必须来自产生该势的同一个新TaskRecord，不能借旧50的job或电子结果充数。

## 验收顺序与最小原生协议

先审阅reader与writer，再v100 Slurm做修改路径定向检查（1 CPU、2 GiB、2分钟、no-requeue），不重跑冻结0.19。真实输出缺失复用已有六任务inventory，当前native_output_observed/native_GPU_accepted均false。

若缺少真实源而需要原生接口验收，执行前单独登记一项：已选CZO Pnma中性20原子、固定胞，复用job50物理与数值配置（PBE/原NC赝势/100Ry/2x2x2/88bands/scf_thr1e-4/scf_nmax100/mixing0.3/fixed/nspin1），仅新增输出控制；不研究精度。最多一个任务，1V100、1MPI、至多4CPU、8GiB、time=0、no-requeue。保留迭代上限和原生失败，不自动调参/重试；未收敛诚实记录，不宣称势科学有效。不得扩宿主/缺陷矩阵或以此开放带电形成能。
