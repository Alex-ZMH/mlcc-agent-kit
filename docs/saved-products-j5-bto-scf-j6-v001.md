# J5保存产品出口与J6最小掺杂SCF

2026-10-26。0.55启用/0.54回退，live源码0.56；J4的622–624已完成，只复用。用户在监督聊天原始消息`01a1770f-104c-7541-8cc0-246dfa2f769a`明确授权代理自主决定“掺杂，位点，浓度，补偿和4f方法”；后续`01a1773d-94f0-7aa1-b1e8-3342b485f87d`将本阶段终点定为领域参数JSON，并要求最小demo。root本轮重新读取两条原始人类消息，不沿用2026-10-25旧提案的pending限制。

## 分工与范围

- 原实施独占J5新 `saved_domain_parameters.py`、专属必要检查与CLI/相关Skill公共接线。仅547保存NEB、530保存法向、533保存切向、566保存应力四类，已有出口足够时直接复用，不重新领域计算/解析原生。`domain_parameters.py`归root，generic delivery尽量不改。不做全库盘点、注册框架或字段级发布。
- 第三独占 `workspace/reports/bto-dy-ho-scf-j6-v001/native-producer/` 模型/输入准备脚本；复用现有composition/supercell/method资格/create_abacus_task/runner，不擅自改公共模块或提交。现成路径若缺功能只报root具体缺口。
- root负责J6方法/资源、Slurm提交/调度、已有结果复用判定、J5/J6集成及共同JSON约定。所有人不是独占代码库，不回退他人修改。
- J5预算：CPU1、GPU0、2GiB、10分钟；只新增必要检查与首次保存源消费。J6准备CPU1/GPU0/4GiB/10分钟，DFT前完成。

## J6三个固定胞任务

父模型是job361已选未掺杂P4mm5原子、极轴[001]的 `batio3-p4mm-ferroelectric/v001`，保持原子坐标/胞和Ti/O位移。采用现有模型函数一次生成2×2×2、40原子host，另建两个独立变体：

| 实例 | 组成 | 替位/电荷 |
|---|---|---|
| host | Ba8Ti8O24 | 未掺杂，q0 |
| Dy | Ba7Ti7Dy2O24 | 同一[0,0,0]像的parent Ba0及Ti1分别换Dy，q0 |
| Ho | Ba7Ti7Ho2O24 | 同样两个母体位点分别换Ho，q0 |

保存parent atom_id、repeat image与child atom_id及元素变化。Dy/Ho各自单元素双位点自补偿，不共掺，不加Mg/空位、不搜索占位。不强称掺杂结构仍P4mm。每子晶格12.5%、总原子5%是这个工程胞的组成，不作为实验投料量。

现有464是5原子参考，不把其总能简单乘8冒充40原子原生参考。同方法40原子host若已存在则复用；否则只新增上表三任务，不重跑464/Born/Γ或温度矩阵。

## 方法与原生资源

沿464的共同Ba/Ti/O方法：ABACUS3.10.1、PBE、LCAO、scalar、nspin1、fixed occupations、无SOC/U、symmetry=-1、GPU/cusolver、120 Ry、scf_thr=1e-11、scf_nmax=1000、broyden mixing_beta0.3。40原子采用Gamma中心2×2×2，对应原5原子的4×4×4采样密度。固定胞SCF，不弛豫、不设墙钟截止；迭代耗尽如实标未收敛，不自动调参/重试。

| 元素 | PP文件（现场pseudopotentials目录） | NAO（现场orbitals-efficiency目录） | 预期价电子/原子 |
|---|---|---|---:|
| Ba | Ba_ONCV_PBE-1.0.upf | Ba_gga_9au_100Ry_4s2p2d1f.orb |10|
| Ti | Ti_ONCV_PBE-1.2.upf | Ti_gga_7au_100Ry_4s2p2d1f.orb |12|
| O | O.upf | O_gga_6au_100Ry_2s2p1d.orb |6|
| Dy | Dy3+_f--core-icmod1.PD04.PBE.UPF | Dy_gga_8au_100Ry_4s2p2d1f.orb |11|
| Ho | Ho3+_f--core-icmod1.PD04.PBE.UPF | Ho_gga_8au_100Ry_4s2p2d1f.orb |11|

文件根为 `/home/v100/abacus-work/PPORBs/`。PP/NAO原生头和库pairing_source随方法保存；原生头为实际电子数依据，不能只信文件名。采用f-core的非磁工程模型；不计算价层4f磁性或SOC性质。三例预期均320电子、160占据带；nbands188，额外28带仅为本次电子接口选择，不作未占据态精度声明。

只输出E/F/整体应力和电子记录：`out_bandgap=1`，`out_chg=0`，`out_mat_hs2=0`，`out_mat_r=0`。沿既有原生输出/istate解析；若未产生必要文件，报告实际缺口，不假造。

每个DFT：1V100、1rank、CPU2、8192MiB、time=0、no-requeue。最多3任务并行，共3GPU/6CPU/24GiB，同一节点总资源约束；不把cpu/gpu分区当作独立机器。J5 CPU1/2GiB可在剩余资源内并行。支持GPU的这三例不转CPU。

## 消费与边界

复用现有ABACUS解析与电子解析，每个真实输出只读一次，保存结果后薄接领域JSON及同Study。每例交能量eV、source-order力eV/Å、原生定义整体应力GPa、电子数和采样网格带隙eV及收敛/来源状态。共同位点映射和共同PP/方法设置明确后，差量优先复用已有composition comparison对带隙/应力及可定义的位点力的支持。

不同组成的绝对总能分别保存；不把它们的裸差伪称掺杂形成能、结合能或自由能。没有化学势/反应声明时不新增形成能计算，不让这项独立缺口阻断上述路径。SCF原生收敛与整个材料方法资格分别记录，不追加资格包装或收敛矩阵。

完成首次真实demo即推进，不因数值不理想、短采样或未决而重跑；本阶段仍不开发JSON之后的场/网格/有限元流程。
