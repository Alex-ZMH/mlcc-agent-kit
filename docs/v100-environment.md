# v100 只读环境记录

此文保存安装前观察，不是当前 Slurm 状态。后续已按用户要求安装并配置 Slurm，当前结果以 slurm-installation.md 为准。

日期：2026-10-20，Asia/Shanghai。未创建服务器目录、传文件、安装、启服务或提交计算。发现程序不等于 MLCC 运行验收。

| 项目 | 实测证据 | 影响 |
| --- | --- | --- |
| SSH | ssh -G v100 为 v100@192.168.110.35:22，只读连接成功 | 开发/scp 走 LAN 别名 |
| 本机 | WLAN 3=192.168.110.9/24 | 与服务器同 LAN |
| 公网 | 用户提供 43.142.15.151:22022 | 未测试，不自动切换 |
| 主机 | v100-System-Product-Name；Linux 7.0.0-38-generic | 不是 ACS README 的旧站点 |
| GPU | 4×Tesla V100-SXM2-16GB，驱动 580.178.04 | 单卡 16 GiB，测量后定并行 |
| CPU/RAM | nproc=16，约 31 GiB RAM、29 GiB available | 多任务/超胞内存需预算 |
| 磁盘 | /home/v100 所在分区约 293 GiB available | 大输出不全量回传 |
| VASP | /opt/vasp/vasp_std、vasp_gam、vasp_ncl | 存在，未启动新任务 |
| 历史版本 | /home/v100/prj/test2_AIMD/OUTCAR 首行 vasp.6.5.1，2025-05-23 构建、gamma-only | 不证明 std/ncl 各二进制版本相同 |
| VASP MPI | /opt/nvidia/hpc_sdk/Linux_x86_64/24.1/comm_libs/mpi/bin/mpirun；ldd 指向 NVHPC/HPC-X | 启动显式环境 |
| ABACUS | /home/v100/miniforge3/envs/abacus_env/bin/abacus；包记录 3.10.1、cuda_mpi_mpich | 尚未验证 MLCC 功能 |
| ABACUS MPI | 同环境 bin/mpiexec→mpiexec.hydra | 不与 NVHPC MPI 混用 |
| Python | abacus_env 无 bin/python；Miniforge base Python 3.14、ASE 3.29.0、未发现 pymatgen | 建模单建项目环境 |
| UPF/ORB | /home/v100/abacus-work/PPORBs/pseudopotentials 与 orbitals-efficiency，有 Ba/Ti/O/Ni/Ca/Zr 文件 | 仅文件名存在，方法/收敛未验 |
| PATH | 非交互 PATH 未找到 vasp_std、abacus、mpirun | 不依赖交互 .bashrc |
| Slurm | sinfo/squeue：resolve_ctls_from_dns_srv / 无法获取配置 | 不启用 Slurm runner |
| 进程 | 探测未看到本用户 vasp/abacus/lmp/mpirun | 不是资源预留，不自动启动 |
| LAMMPS/MCP | PATH 未找到 lmp/lmp_mpi；未完整探测磁盘/服务端口 | 未确认可用 |
| POTCAR | 旧任务有已拼接 POTCAR，未确认完整授权库 | 不当作本项目任意组成可用资源 |

/home/v100/abacus.sh 实际固定通过 find_gpu.sh 选择一张卡，运行单 rank；注释不是任意多卡参数已实现的证据。旧 mpirun.sh 的映射/线程数也不是 MLCC 性能最优配置。

远端拟建 /home/v100/projects/mlcc，本次未创建。密钥沿用 SSH 配置，不写进项目；未输出私钥/POTCAR 正文/许可证内容。

下一轮：独立目录/项目环境→无计算命令执行/查询/回传→授权 POTCAR→VASP 小任务→ABACUS 同几何→独立弛豫→各性质能力。当前只完成环境调查。
