# Windows 与科学环境的边界

Windows Adapter只用标准库，正式入口adapter.py。公共Runtime、任务记录/worker和只读查询始终在Windows。专业包不在公共包或Windows Adapter顶层导入。

科学入口science_entry.py及device_fem/fenicsx.py在已有Ubuntu-24.04 WSL2下，以现有 `/home/zhaoxiang/miniconda3/envs/fenicsx-env/bin/python` 运行。该路径是本机部署例，代码从宿主绑定读取，不由科学输入控制。没有运行conda install/pip install、升级包或替换环境，也不source旧项目launcher。

本轮实际环境：Python3.11.15、DOLFINx0.11.0、UFL2026.1.0、petsc4py3.25.5、mpi4py4.1.2、Gmsh4.15.2、NumPy2.4.6、PyVista0.48.4、Matplotlib3.11.2。入口--probe只读元数据，不生成几何/网格/JIT或工作目录；执行时再次核对API版本，当前仅支持已验证DOLFINx0.11.0的实数、单MPI rank。

模块不使用旧CaseSpec/Pydantic/PyYAML，也不依赖旧fem_agent安装。当前科学环境可能另有这些包，但本实现不导入。Windows/Linux映射、解释器、发行版、线程、max_cells和科学客户端超时在独立的fea.deployment.v1 JSON中；全部字段类型和允许范围由标准库代码检查。环境探测7秒预算留在公共preflight10秒上限内。

调用只使用argv数组：wsl.exe --distribution DISTRO --cd LINUX_TASK_DIR --exec PYTHON -B -u SCIENCE_ENTRY --request FILE --response FILE，不经过shell、conda banner或自由拼接命令。Linux只处理原生科学文件协议，不运行mlcc或Agent。

每个公共task的artifact_dir/native单独保存输入/响应/stdout/stderr/launch与缓存。目录独占创建，已经开始过的目录禁止自动复用。字段数组用VTU交接；Windows校验输入摘要、输出schema/量纲关系、必需产物、文件hash和JSON指标一致性，公共层再校验路径/大小并登记。科学流和公共stdout协议分离。

部署上限（单线程、最多50,000一阶三角形、科学客户端至多120秒）只限定本次有界实现的资源范围，不保证内存硬隔离或精度。preflight的单元估计是保守规划量，实际网格在求解前再检查。若需要更大任务，应先另行审查预算和算法，不自行增大本轮范围。

Windows子进程timeout仅结束本地客户端的等待/进程，不证实WSL/Linux求解进程消失。当前没有远端进程组回收、取消或集群任务系统。保留不确定任务，人工确认原生进程后再决定后续动作；不得自动重提交。

env变量MLCC_FEA_DEPLOYMENT由宿主启动环境或run-windows.ps1传入；文件不含密钥。模块不会修改中央config、机器PATH、Conda、WSL配置或用户全局环境。发布时排除work、review_work运行缓存及deployment/local.json；精确环境重建和其他机器迁移尚未验证。


## 0.3.0 器件扩展增量

新增device_fem/extended/科学代码仍只在同一既有WSL环境导入，复用已有NumPy/UFL/DOLFINx/Gmsh/PETSc、PyVista/Matplotlib及XDMF/HDF5导出支持。未安装或升级任何包。AC/EM双实数P1块使用已有MUMPS；原静电直接LU保持原设置。

新v2部署见deployment/extended.example.json：schema_version=fem.deployment.v2、profile=device_extended_v1，最多150000实际三角形、240秒客户端、单线程；仅新电热/AC/EM入口接受。旧静电和多单位静电继续v1的50000/120秒限制并拒绝v2，避免静默扩大旧范围。原科学协议兼容新增可选operation字段；原请求缺该字段仍执行原静电，公共Adapter协议不变。扩展运行前再次拒绝非实数PETSc或MPI非单rank环境。

日志/缓存仍在每task/native，原始数据与单位审计独立登记。新导出包含VTU/XDMF/HDF5/NPZ，PNG是可选展示。当前Windows未装PyYAML，skill-creator的独立quick_validate因前置条件缺失not_checked；模块标准库元数据/链接检查可运行，未为此安装依赖。
