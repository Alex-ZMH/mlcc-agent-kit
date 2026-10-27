**Linux 有限元软件：LAMMPS 参数对接候选清单 v001**

调研日期：2026-10-26（Asia/Shanghai）。本清单延续开源软件选型范围，以可在原生 Linux 上运行、可无 GUI 批处理、能够通过材料输入或程序接口接收连续体参数为纳入条件。GPU 支持作为单独标注，不作为 Linux 清单的硬门槛。COMSOL 作为已有商业目标单列。

状态：文档与官方资料核实完成；下列开源对象均为候选，未在本站安装或执行原生有限元验收。Linux 支持不等于已适配本站发行版、MPI、CUDA 或 Slurm。清单不改变现有软件发布、计算队列或已授权实现范围。

这里的对接指单向参数传递：LAMMPS 保存结果，经统计/物性提取后进入现有 SI 参数出口，再由选定目标的薄适配器生成材料输入、曲线或场数据。没有将这些软件认定为具有现成的 LAMMPS 原生双向耦合接口；也没有将 LAMMPS dump、DeePMD/MACE 势文件等同于有限元材料文件。

参数分组用于简化表格：

- 热参数：密度 rho、定压比热 cp、热导率 kappa、热膨胀 alpha、参考温度及温度依赖表。
- 力学参数：弹性刚度 Cij、适用时的 E/nu、热应变、初始/残余应力。
- 界面参数：有明确物理定义的界面热导/面积热阻、法向/切向刚度或牵引—分离曲线。
- 迁移参数：扩散系数等连续体输运系数，需有相应保存计算来源。
- 电学参数：介电张量、电导率、损耗等；普通能量/力型 MD 势不会自动提供这些量，可来自独立 DFT、专门极化/输运模型或实验。不同来源必须保留。

**现成求解器与输入文件驱动对象**

| 对象 | 原生 Linux / 无 GUI | 推荐接收参数与用途 | 对接输入和运行形态 | GPU 实际范围 | 本项目建议 |
| --- | --- | --- | --- | --- | --- |
| Elmer FEM | 支持；可关闭 ElmerGUI 构建，官方有 Slurm 示例 | 热、力学；选定模块下的界面或电热耦合 | 生成 SIF 材料/边界设置及网格；ElmerSolver / MPI | AMGX 接口加速线性求解，非所有组装/物理模块 GPU 化 | 首选综合热力参数接收端 |
| Code_Aster（Salome-Meca 为可选前端） | 支持；run_aster 无 GUI 执行 | 热、力学、结构非线性；界面需对应模型 | .comm 命令、.export 作业描述，常用 MED 网格 | 本次未核实通用现成 GPU 求解路径，按 CPU/MPI 规划 | 热机械专用备选 |
| CalculiX | 支持；独立 ccx 命令行求解器 | 热、力学及相应接触模型 | .inp 材料/模型卡片；.dat/.frd 输出 | 外接/修改版 PaStiX-CUDA 路线需专门构建；标准安装不视为 GPU 就绪 | 结构热机械备选 |
| Palace | 支持；官方 Linux CI，CLI/MPI/Apptainer | 电场、电容、电磁；主要接收介电率、电导率、损耗等 | JSON 配置和网格；palace 批处理 | CUDA/HIP、多 GPU；部分装配等路径 | 电磁专用候选，主要依赖独立电学参数源 |

Elmer 的 Linux/无 GUI 构建见 [Ubuntu 编译指南](https://github.com/ElmerCSC/elmerfem/blob/devel/compilation_instructions/Ubuntu.md)，集群入口见 [CSC Elmer/Slurm 文档](https://docs.csc.fi/apps/elmer/)，材料字段见 [官方 SIF 示例](https://github.com/ElmerCSC/elmerfem/blob/devel/fem/tests/NaturalConvection2/case.sif)，AMGX 见 [26.1 发布说明](https://github.com/ElmerCSC/elmerfem/blob/devel/ReleaseNotes/release_26.1.md)。

Code_Aster 的部署与入口见 [安装文档](https://codeaster.readthedocs.io/en/latest/installation.html)、[run_aster 文档](https://codeaster.readthedocs.io/en/latest/devguide/run_aster/run_aster.html)；计算并行范围见 [线性求解器说明](https://code-aster.org/doc/v17/manuals/man_u/u2/u2.08.03/Les_diff_rents_solveurs_lin_aires_disponibles.html)。

CalculiX 的 Linux 源码及入口见 [官方仓库](https://github.com/Dhondtguido/CalculiX)、[命令行入口源码](https://github.com/Dhondtguido/CalculiX/blob/master/src/CalculiX.c)；外接 GPU 路线见 [维护者讨论](https://calculix.discourse.group/t/calculix-version-2-17)。

Palace 的部署见 [安装](https://awslabs.github.io/palace/stable/install/)、[Linux CI](https://awslabs.github.io/palace/stable/developer/testing/)；输入与执行见 [运行文档](https://awslabs.github.io/palace/stable/run/)，GPU 范围见 [并行与 GPU](https://awslabs.github.io/palace/stable/guide/parallelism/)，材料范围见 [参考文档](https://github.com/awslabs/palace/blob/main/docs/src/reference.md)。

**可编程框架与弱形式脚本对象**

这一类需要构造有限元模型、边界条件和材料函数。能接收某类参数，表示可以在相应实现中将参数用作系数或本构输入，不表示任意参数都有开箱即用的物理模块。

| 对象 | 原生 Linux / 无 GUI | 推荐接收参数与用途 | 对接输入和运行形态 | GPU 实际范围 | 本项目建议 |
| --- | --- | --- | --- | --- | --- |
| MOOSE | 支持 Linux/HPC；编译后的应用读取输入文件 | 热、力学、界面、扩散、相场；按模块或自定义本构 | .i 输入、材料/函数/表格；必要时开发 C++ 对象 | Kokkos-MOOSE 的已移植对象，或 MFEM-MOOSE 路径；不能默认全部模块支持 | 复杂耦合与相场方向候选 |
| FEniCSx / DOLFINx | 支持 Debian/Ubuntu、Conda、源码；Python/MPI | 热、力学、界面、扩散及自定义 PDE | Python/UFL 读取 SI 参数，形成系数、函数或场 | PETSc/专门扩展和开发中的设备路线；普通安装不等于完整 GPU 工作流 | Python 自动化与自定义方程优先候选 |
| MFEM | 支持 Linux Make/CMake/MPI；独立程序无 GUI | 热、力学、电磁等自定义高阶 FEM | 自编 C++ 求解程序读取参数、连接系数/积分器 | CUDA/HIP 等；支持的积分器可用设备装配、部分装配和算子执行 | GPU 优先的开发后端候选 |
| NGSolve / Netgen | 支持 Linux；可 USE_GUI=OFF 并保留 Python/MPI | 热、力学、电磁及自定义 PDE | Python 脚本/系数函数，必要时 C++ 扩展 | CUDA 设备矩阵/算子与矩阵无关路径；具体预条件器需确认 | Python + 高阶/GPU 备选 |
| deal.II | 支持 Linux 包、CMake/candi/Spack；无 GUI 程序 | 热、力学、扩散等自定义 FEM | 自编 C++ 程序及材料/本构类 | Kokkos Portable MatrixFree 或外接 GPU 线性代数 | 需要专用 C++ 求解器时备选 |
| FreeFEM | 支持 Linux；无 GUI / MPI 脚本入口 | 热、力学、扩散及自定义耦合弱形式 | .edp 脚本读取参数/表格并构造方程 | 经 PETSc 的线性求解 GPU 路线，非自动 GPU 装配 | 轻量 PDE 原型备选 |
| GetDP + Gmsh/ONELAB | 支持 Linux；GetDP 可独立 CLI 执行 | 热、电磁及自定义耦合 | .pro 问题定义、函数/常数、.msh 网格 | GPU-PETSc 为间接待验证路线，未核实完整原生 GPU 工作流 | 电热弱形式备选 |
| JAX-FEM | 支持 Linux Python/JAX 环境；脚本无 GUI | 热、力学、本构参数反演与设计 | Python 问题定义、材料参数及求解器配置 | JAX GPU；线性后端还可选 AMGX/PETSc/SciPy，非所有阶段驻 GPU | 可微反演/优化专项候选 |

MOOSE 的 Linux 与 HPC 路线见 [安装文档](https://mooseframework.inl.gov/getting_started/installation/index.html)，输入结构见 [输入文件示例](https://mooseframework.inl.gov/getting_started/examples_and_tutorials/examples/ex01_inputfile.html)，模块和 GPU 见 [物理模块](https://mooseframework.inl.gov/modules/index.html)、[计算后端](https://mooseframework.inl.gov/framework_development/computational_backends.html)。

FEniCSx 的 Linux 安装见 [下载与部署](https://fenicsproject.org/download/)、[DOLFINx Python 安装](https://docs.fenicsproject.org/dolfinx/main/python/installation.html)；GPU 状态见 [官方 GPU 求解器项目](https://github.com/FEniCS/dolfinx-gpu-solvers)。

MFEM 的 Linux/MPI 构建见 [Building MFEM](https://mfem.org/building/)、[构建系统](https://mfem.org/howto/build-systems/)；GPU 范围见 [装配和积分器支持矩阵](https://mfem.org/howto/assembly_levels/)。

NGSolve 的 Linux 及无 GUI 构建见 [Linux 安装](https://docu.ngsolve.org/latest/install/installlinux.html)、[CMake 选项](https://docu.ngsolve.org/latest/install/cmakeoptions.html)；GPU 范围见 [CUDA 算子示例](https://docu.ngsolve.org/latest/i-tutorials/unit-5.5-cuda/poisson_cuda.html)、[矩阵无关 GPU](https://docu.ngsolve.org/latest/i-tutorials/unit-5.6-gpu/matrixfree.html)。

deal.II 的 Linux 构建见 [安装说明](https://dealii.org/9.8.0/readme.html)、[部署方式](https://github.com/dealii/dealii/wiki/Getting-deal.II)；GPU 路线见 [官方指南](https://github.com/dealii/dealii/wiki/GPU-support-in-deal.II)。

FreeFEM 的 Linux/无 GUI/MPI 入口见 [安装](https://doc.freefem.org/introduction/installation.html)、[教程](https://doc.freefem.org/tutorials/index.html)、[并行计算](https://doc.freefem.org/documentation/parallelization.html)；GPU 边界见 [维护者说明](https://community.freefem.org/t/freefem-not-using-gpu-with-petsc/3594)。

GetDP 的 Linux、命令行和问题定义见 [官方手册](https://getdp.info/dev/doc/texinfo/getdp.html)；PETSc 能力见 [GPU roadmap](https://petsc.org/main/overview/gpu_roadmap/)。

JAX-FEM 的部署见 [安装指南](https://deepmodeling.github.io/jax-fem/guide/Installation.html)，Linux CPU/GPU 平台支持见 [JAX 安装矩阵](https://docs.jax.dev/en/latest/installation.html)，材料范围及求解后端见 [官方仓库](https://github.com/deepmodeling/jax-fem)、[solver 文档](https://deepmodeling.github.io/jax-fem/more/api/api_solver.html)。

**前后处理与商业目标的定位**

FreeCAD FEM、Salome-Meca、Gmsh/ONELAB、ParaView 可用于几何、网格、输入配置或结果显示，但不因前端名称另建一个重复的求解后端。FreeCAD FEM 调用的是外部求解器，见 [官方工作台说明](https://github.com/FreeCAD/FreeCAD-documentation/blob/main/wiki/FEM_Workbench.md)。

COMSOL 本身也支持原生 Linux，并支持 Java API 和批处理相关部署；它是需许可证的商业候选，不属于上表开源集合。Linux 条件不能作为淘汰 COMSOL 的理由，但本站环境未识别/原生导入未完成的状态仍需保留。见 [COMSOL 6.4 官方系统要求](https://www.comsol.com/system-requirements/64/general)。

**按 LAMMPS 对接目的选择**

| 首个实际目标 | 推荐候选 | 选择理由与边界 |
| --- | --- | --- |
| 用已有热/力材料参数驱动一个现成 FEM 模型 | Elmer | SIF 材料输入明确，可独立无 GUI 求解，具有 Linux/Slurm 文档 |
| Python 中快速实现自定义热/力/扩散耦合 | FEniCSx；NGSolve 或 FreeFEM 备选 | 参数读取与方程实现灵活；仍需编写模型 |
| 多物理模块、界面与相场开发 | MOOSE | 可复用已有模块；特殊材料和 GPU 需逐项适配 |
| 高阶有限元与 GPU 是首要要求 | MFEM；NGSolve 备选 | GPU 算子/装配路线明确；需要应用开发 |
| 结构热机械专用分析 | Code_Aster 或 CalculiX | 已有材料和结构求解体系；按具体模型选择 |
| 电场与电容矩阵 | Palace；GetDP 备选 | 接收独立电学参数；普通 E/F MD 不提供完整电学材料数据 |
| 可微本构反演/设计优化 | JAX-FEM | 面向可微有限元和逆问题，属于专项需求 |

以上是选型建议，不是同时引入全部框架的实施计划。若当前任务聚焦 LAMMPS 热力参数接收，建议首先只选 Elmer 作为首个目标；若明确优先 GPU 底层开发，再选择 MFEM 路线。

**与现有 MLCC 出口衔接的最小边界**

- 复用现有 continuum_parameters 的 SI 字段和来源约定。当前定义了 16 类字段，直接读取 mlcc.lammps-result.v1 的路径仅接 initial_stress；其他量需要相应保存产品或 typed source。见 [字段定义](../mlcc-agent/src/mlcc/continuum_parameters.py) 和 [已交付报告](../workspace/reports/multi-dopant-continuum-v001/report.md)。
- 目标适配器把已存在的参数转换到目标格式，保留单位、温度/压力、材料/组分/晶相、晶向、参考态、张量顺序、原生 job 和科学状态。缺失值仍缺失，未收敛或候选状态原样传递；工程接通不授予材料生产资格。
- 材料常数/温度表和空间场分别处理；残余应力等场数据还需明确空间平均、坐标变换与网格映射。当前局部夹持斜率不能未经定义转换即写成单界面刚度。
- 按目标模型需要选择已就绪参数，不因此新增 DFT、MD、NEB、训练或温度/精度矩阵。CZO/BTO 电学数据维持独立响应来源，BTO 未决静态介电不得补零。
- 运行仍由现有 runner 通过 v100 Slurm 提交并保存原生 job ID、状态与输出。本站安装、CPU/GPU/MPI 入口和实际参数消费均留待选定对象后进行必要的最小工程检查；本清单没有执行这些步骤。
- V100 属于 Volta/sm_70，应选支持该架构的 CUDA 12.x 工具链和依赖版本；CUDA 13 已移除 Volta 的离线编译/库支持。支持 GPU 的软件不等于其任意最新版二进制都支持 V100。见 [NVIDIA CUDA 13 发布说明](https://docs.nvidia.com/cuda/archive/13.0.0/cuda-toolkit-release-notes/)。
