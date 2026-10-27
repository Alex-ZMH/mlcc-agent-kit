# CZO 氧空位迁移最小工程链

2026-10-26，用户在“叮嘱”原始 turn `01a17655-40f5-7742-a9c0-69b38651d997` 授权下一核心功能。M4 已由540/541完成并冻结0.51；本范围属于源码0.52，不修改该冻结版本。

## 所有权

- 原实施窗口：`vacancy_migration.py`、专属新测试、唯一 CLI/property_delivery/Skill 接线。
- 第三窗口：`lammps_neb.py`、按需 `neb_tasks.py`、专属新测试；复用 TaskRecord/SiteRunner，不重造调度器。
- root：路径/端点选择与数据合同、现场能力、共享 `lammps.py` 的 purpose 单点、Slurm预算、集成审收。当前 runner 原有资源与任意 command 已足够，不预先改造。

## 复用来源

host20：`/home/v100/projects/mlcc/development/0.10.0/project/workspace/models/cazro3-pnma-pristine/v001`，Ca4Zr4O12。vacancy19：`/home/v100/projects/mlcc/development/0.13.0/project/workspace/models/cazro3-pnma-vo8-q0/v001`，仅删除母体原子ID8，保留ID0–7、9–19。两者同胞与未掺杂原选择不变。

势：`/home/v100/projects/mlcc/development/ceramic-training-v001/project/workspace/tasks/czo-neutral-joint-training-v001/frozen_model.pth`，模型卡同目录 `model-card.json`；身份 `deepmd-czo-neutral-joint-training-v001/146`，Ca/Zr/O映射。原两训练帧、100步、无独立验证和 `not_qualified/production_qualification=false` 原样保留，不重训、不比较另一势或新DFT。

保存MD：同 `ceramic-training-v001/project/workspace/tasks/czo-deepmd-vacancy19-md-v001` 的job155，step0–5六帧，dt0.0001ps，原dump只有id/type/x/y/z/fx/fy/fz。复用其atom-map/method/md-conditions与原调度终态；不重跑155。

## 一条工程路径

只选择一个保留的近邻氧移动到母体空位8。路径准备在v100 Slurm执行：枚举保留氧与目标位点的相邻周期像，按最短距离、源ID、整数像排序选一个；保存所有距离并列候选及明确选中记录。这是本轮工程路径选择，不声称支配迁移通道或材料势垒。

初/终端点保留同19原子、元素、源稳定ID、晶胞和冻结势。最终仅显式移动一个氧到目标位点像；不能删去另一个原子或重排ID冒充迁移。保存源/目标母位点ID、迁移源atom ID、目标母体整数像、每原子final_image_shifts，以及Prism旋转/原点。母体目标像与最终模型展开像分别记录。

协议采用 `mlcc.lammps-neb-protocol.v1`，`kind=neb/purpose=vacancy_migration`；输入显式包含 images/ranks_per_image/min_style/timestep_ps/etol/ftol_eV_per_angstrom/max_iterations/climb_iterations/output_every/spring_eV_per_angstrom2/neb_atom_ids/endpoint_policy/final_image_shifts/path_provenance。`neb_atom_ids`为稳定源ID，全部19原子参与。路径 `path_provenance` 至少包含path_id、host_model、vacancy_parent_atom_id、migrating_atom_id、source_parent_site_id、target_parent_site_id、target_parent_image和端点准备来源。

必要端点最小化纳入新路径，原停止原因单独保留。优先同一次原生多partition运行：各image显式输入、仅首末image预最小化，然后固定端点并 `neb ... none`。不得用后续 `neb ... final` 覆盖已经弛豫的终点。若实际实现必须独立端点任务，先在execution记录调整预算和依赖，不重复已执行端点。

## 已声明资源与数值协议

- 准备、新增软件检查、保存155消费：CPU1/GPU0/4GiB/10分钟/no-requeue，仅新路径。
- 唯一原生NEB：1节点、4 MPI ranks、每image1rank，共4images；4V100，每rank仅暴露对应的1张已分配GPU；CPU4、内存24GiB、20分钟、no-requeue。首次32GiB请求被Slurm拒绝且没有job ID；root查到节点RealMemory=27800MiB后显式修正为24576MiB，原请求与错误保留，未发生引擎计算，数值协议不变。
- 端点CG：etol=0、ftol=0.05 eV/Å、最多200迭代/1000次力评估；固定胞。
- NEB：quickmin、dt=0.001ps、etol=0、ftol=0.05 eV/Å、regular最多200步、climbing最多200步、每10步原生输出；弹簧1 eV/Å²、`parallel neigh`；端点固定。

这些是单个工程实验的显式预算，不是材料收敛资格。达到迭代上限原样输出未收敛，不重排、不调参、不扩路径或温度矩阵。`1e-11`只用于新增ABACUS SCF，与NEB/MD阈值无关。本轮无DFT。

## 站点与GPU映射

已定向读取既有 `/home/v100/dpa4/releases/3.2.0/bin/lmp -h`：LAMMPS22Jul2025Update2，REPLICA/PLUGIN、neb、quickmin/fire存在；MPI为MPICH5.0.1。当前PATH不含mpirun，但同安装 `bin/mpiexec` 已确认HYDRA5.0.1；source既有deepmd-lammps-env-v001.sh后libmpi.so.12正确来自该安装。无需新编译或换引擎。

按既有环境和插件运行，显式同安装MPI启动器。root提供rank wrapper，使用PMI_RANK在Slurm CUDA_VISIBLE_DEVICES清单选择对应GPU并保存启动证据；每rank只有一个可见GPU。缺映射或数量不符直接报原错误，不CPU回退。

## 保存轨迹的空位跳跃分析

固定母体氧子晶格ID8–19，使用原dump及原子映射。逐帧按PBC最小镜像计算原子到位点的距离；本次显式capture_radius=1.0Å、ambiguity_gap=1e-6Å、至少2连续帧确认占位变化。冲突/多占据/过远/并列按未决记录，不用强制一一匹配掩盖问题。

wrapped坐标足以进行固定胞逐帧占位观察；缺unwrap限制连续净位移、扩散系数及采样间隐藏跳跃，不阻塞可判定的占位。保存无跳跃结果不等于材料不能迁移。NEB图像是反应坐标，不能计为时间序列事件/扩散率。未声明生产采样窗口和统计资格保持原状态。

NEB几何占据消费显式 `confirmation_frames=1`，只比较相邻图像；MD使用2帧持续确认。547初次消费复制了MD的2帧设置，该原产品保留；最终只用已安装副本重新消费保存NEB结果的这一更正输入，不重跑原生NEB、端点或MD。

## 验收与输出

新增检查与真实公共路径合并执行，旧M4/146/151/155及既有软件检查不重跑。输出包括每image E/RD、原生力/所有迭代与停止原因、regular和climbing分阶段状态、端点状态、正反向候选势垒、climbing image与最终最高能image分别记录、同Study交付。

`native_converged`按climbing阶段原生力/能量停止判定，regular是否达到上限独立保留；端点未收敛、势未经材料资格不能被该字段覆盖。Slurm完成不等于物理收敛，工程路径通过也不升级材料资格。

官方依据：[neb](https://docs.lammps.org/neb.html)、[fix neb](https://docs.lammps.org/fix_neb.html)。实际语法/输出需与站点2025版本对应，不能把当前网页新增特性默认带入旧引擎。
