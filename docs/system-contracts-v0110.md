# 0.11.0：MACE 公共任务闭环与 MD 序列入口（2026-10-22）

0.11.0已验收、启用并冻结，见[发布验收](../workspace/reports/system-v0110/acceptance.json)。本次范围是MACE公共静态任务生命周期及MD-00完整序列公共入口；0.10原目录保留，源候选已进入0.12.0。下方104为历史创建器切片，106/107/108补齐其公共执行缺口。

## 公共路径与安装交付

job106在v100/Slurm内调用公共`create-lammps`生成真实任务；本地仅通过已有SSH/scp控制，公共`prepare→transfer→submit→status→collect`得到job107的原生终态。job107为单V100、20原子、静态run0，`COMPLETED/0:0`、2秒。它只覆盖尚未验证的公共任务路径，不是重复引擎精度或材料筛查。

job108为`COMPLETED/0:0`、5秒，从安装副本调用`parse-lammps`，得到完整E/F/stress、单位、原子映射与原生来源。既有势比较读取端消费这份真实TaskRecord，`resume-plan`判工程任务已完成；结果仍是`evaluated_candidate_potential`、生产资格false。完整多结构相对能筛查不属于本次验收。

新增公共命令`mlcc md-collection --task <已完成MD目录> --output <新collection.json>`，直接接入MD-00模块。job108通过2项新增CLI检查和真实job45入口，输出11帧和11条thermo，原始task/result未改；job105的13项模块检查复用。缺少image flags、速度、unwrap和平衡/生产窗口仍明确记录，无MSD/扩散/采样资格。MD-01独立条件模块未纳入0.11发布，不阻塞本切片。

完整账本与范围见[公共路径执行记录](../workspace/reports/mace-public-v011-v001/execution-ledger.md)及[安装验收108](../workspace/reports/mace-public-v011-v001/installed-108/acceptance.json)。本次没有新增DFT、MD、候选筛选或参数加密。

发布前审查发现历史生成的`src/mlcc_agent.egg-info`仍为0.9.0。已使用独立构建工具setuptools 80.9.0，在0.11发行目录依据`pyproject.toml`运行`egg_info`重生成，再同步本地/远端安装副本；两端`importlib.metadata.version`均为0.11.0，SOURCES包含MD-00及新CLI测试，不含MD-01。后续发行快照复制后必须重生成元数据，不能直接沿用源码中的旧egg-info。数值源码没有因此改变，不重复107/108。历史修复前归档保留，当前归档为`installed-v002-metadata-corrected.tar.gz`。

MatterAI直接MCP连接显示0.11.0、七工具且调用成功。原版宿主实际会话最终`turn.completed`、`run.completed`、进程0、一次`mlcc_list_tasks`成功；旧harness将中间连接超时映射为整场失败，现已按原生最终终态与退出码修正，8项非数值连接逻辑检查通过。只对同一v002记录离线重判，不启动新会话；原超时、原failed报告和注册路径不匹配错误全部保留。[宿主复核](../workspace/reports/system-v0110/matterai-headless-session-v0110-v003-reanalysis.json)。

## 实现与验收

复用`create-lammps`和既有Slurm runner，接通已安装独立MACE引擎所需的显式输入：`mace no_domain_decomposition`、Kokkos half邻居、atom map、关闭原子排序及newton on。站点新增可选`lammps.launch_arguments`；MACE路径要求明确的单节点、单rank、单GPU及`-k on g 1 -sf kk`，势文件与LAMMPS原子类型的元素顺序必须对应。旧Ni站点省略参数时保持原行为。

路径限定为真实科学模型的静态候选势资格任务：`purpose=potential_qualification`、`kind=run0`、`static_tensor=true`。不开放MACE生产MD、多GPU或隐式CPU路径。MACE作为公开候选/对照，ABACUS→DeePMD-kit→LAMMPS仍为专用势路线。

Luna完成限定源码和测试，主代理审查后补充了不支持的MACE写法拒绝、错误消息修正，并校正元素映射说明。源码以独立0.11目录传到v100；未修改冻结release/installed。

**v100 Slurm job104：COMPLETED/0:0，3秒。** 1物理核请求（Slurm分配2逻辑CPU）、4GiB、5分钟非DFT预算；8项针对性检查通过，66项未选取。实际CLI使用既有CZO模型及转换模型生成任务，再用`prepare`生成GPU Slurm脚本；与job98原始输入的同几何、元素、ID、晶胞、质量检查通过，周期坐标残差1.7763568394002505e-15Å，小于预声明1e-10Å。

生成任务保持`prepared / not_calculated`、无scheduler job ID、无原生结果，调用原生任务读取入口按现有COMPLETED/0:0门拒绝。没有把job98的失败批任务改为成功，也没有把旧输出附到新任务。

- [预声明协议](../workspace/reports/mace-creator-v011-v001/protocol.json)
- [实际CLI及同几何验收](../workspace/reports/mace-creator-v011-v001/check-104/acceptance.json)
- [原生Slurm终态](../workspace/reports/mace-creator-v011-v001/scheduler-104.txt)
- [检查输出](../workspace/reports/mace-creator-v011-v001/check-104.out)
- [站点配置](../workspace/configs/site.v100-mace-v001.json)

## 复用证据与保留缺口

独立MACE引擎的安装97及原生98/后处理101已证明同模型单V100接口，相关精度证据继续复用。98的独立文件命名、thermo格式和FAILED批状态没有导入为成功的新任务。公共创建器的原生执行/解析缺口已由声明的一次工程任务107及安装验收108补齐，不再等待材料研究需求。

另一窗口的100/102/103完成中性CZO单构型参考增量诊断，均COMPLETED/0:0、GPU、UNLIMITED。333→444的能量/力/应力增量为0.1423675meV/atom、0.00182635eV/Å、0.00839227GPa，落入本轮1meV/atom、0.015eV/Å、0.05GPa预算；这些是已测单变量局部证据，不是全材料方法资格。MACE应力差仍约2.70826GPa，材料势筛查未通过；不扩大温度、应变或模型矩阵。详见[参考诊断报告](../workspace/reports/czo-neutral-reference-convergence-v001/report.md)。

下一候选继续晶体缺陷host/defect/reference数据合同、铁电/介电响应与MD-01条件/采样窗口接入，按实际依赖补系统路径；不以MACE材料精度作为前置。不能用任意μ补齐形成能，也不能混合方法。带电修正、Berry GPU、专用势训练和材料资格仍未完成。

发布收尾核对：MD-01执行聊天最新一轮因`Selected model is at capacity`中断，草稿保留、尚未验收；责任仍归既有聊天，待服务容量恢复续接，不自动换模型。该局部服务问题不影响已冻结0.11或独立缺陷/铁电开发，详见滚动记录的`MD01_local_blocker`。

## 历史版本清理依赖交接（2026-10-22）

清理由监督聊天独占执行；本窗口只读核对并提供依赖，不同时删除或发布。保留最新发布0.11.0、回退发布0.10.0及0.12候选源码。核对时v100队列为空，不代表以下共享环境和原生数据可以删除。

| 必须保留的路径 | 当前用途与证据 |
| --- | --- |
| `/home/v100/projects/mlcc/development/0.9.0/venv` | 仍是共享科学Python环境。活动`workspace/configs/site.v100.json:python.remote_executable`及Berry/charged站点、108安装检查脚本、当前MD-01的`workspace/reports/md-conditions-v011-v001/verify.sbatch`均指向它；并非仅供0.9软件。仅做安装检查确认解释器存在，`sys.prefix`为此目录，默认`find_spec('mlcc')`为None，项目代码由各作业显式PYTHONPATH选取。清理0.9软件副本时不能连同该venv删除。 |
| `/home/v100/projects/mlcc/development/0.10.0/project/workspace/models/cazro3-pnma-pristine/v001` | 107公共任务的原始模型和后续原生读取依赖；属于科学数据，不是旧软件副本。 |
| `/home/v100/projects/mlcc/development/0.10.0/lammps-md/project/workspace/tasks/p10-ni-lammps-nve100-v001` | job45完整原生轨迹、thermo及task/result；105/108和MD-01复用的数据来源，不能删除。 |
| `D:/project/mlcc/workspace/.venv` | 当前MatterAI MCP共用本地Python环境；不按其中旧editable元数据文件名判断可删除。0.11 MCP launcher显式优先加载安装包的src。 |
| `/home/v100/projects/mlcc/.venv-mace-0.3.10-torch2.5.1`、`/home/v100/projects/mlcc/software/lammps-mace-20250910-v001`、`/home/v100/miniforge3/envs/abacus_env` | 独立MACE引擎当前环境脚本引用的Torch/CUDA、LAMMPS及动态库环境，均不是MLCC历史Bundle副本。 |

当前本地激活注册及MCP入口均指向`workspace/.zeus/bundles/mlcc-agent/0.11.0`；安装验收选取远端`development/0.11.0/installed/0.11.0`。没有发现当前执行入口要求保留0.9及更早的**installed软件代码**；历史验收脚本仍含旧installed路径，属于历史记录，不是当前活动部署。所有版本目录里的`workspace`模型/任务、原生输出、报告和诊断证据仍按用户要求保留，不能据目录版本号整删development。若将共享venv另行迁出，应先显式更新活动站点与新作业脚本，再做安装/导入检查；不需要重跑科学计算。
