# 独立 LAMMPS-MACE 构建与接口验收（2026-10-22）

当前状态：独立引擎已安装，单V100、float64、同模型E/F/全局virial接口验收通过。安装job97为COMPLETED/0:0；job98原生GPU计算完成，但批任务因解析器失败为FAILED/1:0；job101复用98输出完成解析和数值验收，为COMPLETED/0:0。没有重复原生计算。实际启用的mlcc-agent仍为冻结0.10.0，材料势生产资格未通过。

## 定位与交付范围

MACE是公开候选势和对照工具。专用训练势主线继续采用ABACUS→DeePMD-kit→LAMMPS。DeePMD路线必须部署匹配模型backend/格式的C++ runtime及LAMMPS built-in或plugin接口，并真实验证`pair_style deepmd`和同模型E/F/virial一致性；Python训练包或模型导出本身不能证明该路线已接通。

本次只补建独立的ML-MACE GPU引擎及其真实接口实验。模型资格由另一执行窗口独立评估：job84原生MACE ASE GPU计算已COMPLETED/0:0；job87三构型科学筛查应力误差超限，故该公开模型保持未获得CZO生产资格。LAMMPS接口成功也不会覆盖该失败。

## 版本和运行入口

- 源：ACEsuit/lammps `mace`，固定commit `4d222cb3ee2a6b14083c778968497bf9e0efc4b4`，原生版本10 Sep 2025；未修改源文件。
- 独立前缀：`/home/v100/projects/mlcc/software/lammps-mace-20250910-v001`，安装二进制目标为`install/bin/lmp`。
- 构建：GCC12.4.0、CMake3.31.6、Ninja1.12.1、CUDA toolkit12.3.103、Kokkos4.6.2 VOLTA70、C++17、LibTorch2.5.1+cu121/ABI0、MPICH4.3.2；启用ML-MACE、KOKKOS、PLUGIN。
- 实际运行链接：ELF RPATH选中abacus_env的cudart12.9.79和nvrtc12.9.86，Torch编译CUDA为12.1，驱动580.178.04。环境变量顺序没有覆盖该RPATH；保留实际ldd证据，不把构建toolkit12.3误写为运行库版本。同模型GPU一致性验收覆盖的是这一实际组合。
- 模型转换：MACE0.3.10官方`mace.cli.create_lammps_model`，TorchScript float64；复用已下载的MACE-MP-0b3 medium。
- 环境：[lammps-mace-v001.sh](../workspace/configs/lammps-mace-v001.sh)；版本记录：[lammps-mace-environment-v001.json](../workspace/configs/lammps-mace-environment-v001.json)。原Ni LAMMPS 22Jul2025 Update4保持原位。

已验收的实际调用形式（必须在Slurm单rank/单V100任务内）为：

```bash
source /home/v100/projects/mlcc/configs/lammps-mace-v001.sh
/home/v100/projects/mlcc/software/lammps-mace-20250910-v001/install/bin/lmp \
  -k on g 1 -sf kk -in in.lammps
```

输入在`clear`之后显式设置`package kokkos neigh half newton on`，并使用`units metal`、`atom_style atomic`、`atom_modify map yes`、`newton on`、`pair_style mace no_domain_decomposition`和与模型匹配的元素顺序。本实验为`Ca Zr O`，不能把此顺序写为其他材料的通用默认。模型转换产物为`/home/v100/projects/mlcc/reports/lammps-mace-build-v001/mace-mp-0b3-medium.model-lammps.pt`。

## 真实接口实验

[预声明协议](../workspace/reports/lammps-mace-build-v001/acceptance_protocol.json)：复用job84同一MACE模型、float64、20原子CaZrO3/Pnma、周期晶胞和原子顺序，不再次运行ASE或DFT。job95成功执行官方模型转换，因Kokkos邻居设置在势评估前失败。显式修正后，job98复用转换产物执行GPU `run 0`。非DFT预算为单GPU、2CPU、16GiB、10分钟；没有自动重试循环。

验收要求：原生日志证实Torch CUDA和KokkosGPU；实际输出的晶胞、PBC、原子ID/元素/坐标与参考一致。总能误差≤1e-6eV，最大力分量误差≤1e-6eV/Å，六分量应力误差≤1e-5GPa。使用pair-only压力，压缩正bar转换为拉伸正GPa，再按体积记录全局virial。阈值只证明同模型跨接口数值一致性，不是材料精度指标。

job101在v100通过Slurm仅后处理job98和既有job84输出，结果如下，门限未放宽：

| 比较量 | 实际误差 | 预声明门限 | 结果 |
| --- | --- | --- | --- |
| 总能绝对误差 | 1.7783463591e-10 eV | 1e-6 eV | 通过 |
| 最大力分量误差 | 4.7477355380e-11 eV/Å | 1e-6 eV/Å | 通过 |
| 最大应力分量误差 | 4.7208109599e-7 GPa | 1e-5 GPa | 通过 |
| 周期坐标残差 | 0.0 Å | 1e-10 Å | 通过 |

LAMMPS将位于上边界y=Ly的原子6/7包回y=0；解析器按相同原子ID、元素、晶胞和PBC检查整数晶格平移，保留像移记录，不作弛豫、拟合或容差放宽。原始解析失败也保留。详见[最终数值报告](../workspace/reports/lammps-mace-build-v001/interface-v002/interface-acceptance.json)和[部署验收汇总](../workspace/reports/lammps-mace-build-v001/acceptance.json)。

该ML-MACE/Kokkos版本不提供原子级virial和原子级能量。只验收单rank、单V100、float64的声明路径，不推断多GPU、其他材料、缺陷、界面或极化/外场能力。没有新增MD轨迹或温度矩阵。

## 原生执行记录

- job90：GCC/CMake/Ninja已安装完成；慢速源文件下载阶段人为取消。固定源码在本地只作下载，再经LAN传到v100；没有本地编译/计算，没有取消DFT。
- job91：FAILED/1:0，CMake发现PyTorch wheel缺少MKL开发头文件，未进入数值计算。
- job92：FAILED/1:0，包索引未返回指定mkl-include；随后依据Intel官方PyPI元数据取得确切2024.2.2 Linux wheel，未改变Torch/MACE版本。
- job94：FAILED/1:0；512个源对象及liblammps已编译，最终lmp链接找不到主机libcuda.so.1。
- job96：FAILED/1:0；加入整个主机库目录引发MPI的libnl/ibverbs依赖冲突，没有数值计算。
- job97：COMPLETED/0:0，7秒；缩小链接目录为匹配MPI库与实际驱动库专用目录，复用已编译对象完成链接安装，未重编上游源。
- job95：依赖在首次运行前显式更新为97；FAILED/1:0，模型转换成功，Kokkos默认neigh full与newton on冲突，在势评估前停止。
- job98：显式neigh half后原生GPU run0完成；批任务FAILED/1:0来自检查器旧Kokkos标识，原始终态保留。
- job99：仅CPU后处理，FAILED/1:0；识别上边界原子的周期包回，未重算GPU。
- job101：COMPLETED/0:0，1秒；仅CPU后处理既有98输出，通过同模型全部接口门。

详见[执行账本](../workspace/reports/lammps-mace-build-v001/execution-ledger.md)。源码、构建脚本、CMakeCache、原生日志、Slurm终态和数值报告均保留；不以构建成功替代材料科学资格。

## 系统集成边界

当前冻结0.10.0的通用LAMMPS创建器尚未显式生成MACE所需的`atom_modify map yes`、Kokkos邻居设置和启动参数。此次交付是独立引擎与声明输入的真实接口验收；0.11.0候选已补此小范围创建器并通过job104实际CLI输入/prepare检查，完整通用任务的原生执行/解析仍待下一项有实际需要的实验，不能声称所有MLCC MD入口已支持MACE。见[候选记录](system-contracts-v0110.md)。复用既有Slurm runner，不新造调度框架。材料势窗口继续ABACUS参考精度调查；job87的应力筛查失败和未资格状态不因本次接口通过而改变。

## 官方依据

[MACE官方LAMMPS指南](https://mace-docs.readthedocs.io/en/latest/guide/lammps.html)说明TorchScript/ML-MACE和单GPU推荐路线；[0.3.10转换器](https://github.com/ACEsuit/mace/blob/v0.3.10/mace/cli/create_lammps_model.py)对应实际转换版本；[固定LAMMPS源码](https://github.com/ACEsuit/lammps/tree/4d222cb3ee2a6b14083c778968497bf9e0efc4b4)确定实际接口。DeePMD接口依赖和科学门见[材料势路线](material-potential-routes-20261022.md)。
