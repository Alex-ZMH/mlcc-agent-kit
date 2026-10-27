# v100 DeePMD/LAMMPS 运行时只读探测（2026-10-22）

> **最终实证更新（2026-10-22，保留下方历史探测与失败记录）**：后续固定
> v3.2.0 PT 路径已在 Slurm 中完成 1 GPU job `124`、2 GPU job `125` 和公共
> 4 GPU job `129`，均为 `COMPLETED`、`ExitCode=0:0`；job `129` 完成
> `100` steps，并实际生成 `model.ckpt-100.pt`、`model.ckpt.pt` 和
> `frozen_model.pth`。`workspace/tasks/p9-deepmd-public-4gpu-v001/stdout.log`
> 保存了 `CUDA_VISIBLE_DEVICES=0,1,2,3` 以及 NCCL `rank 0..3`、`nranks 4`、
> `cudaDev 0..3` 的原生记录；伴随 `stderr.log` 保存了 DeePMD 的 `Rank: 0/4`
> 到 `Rank: 3/4` 和 CUDA/V100 banner。NCCL 在该单节点上使用 socket OOB 与
> P2P/CUMEM，IB/net plugin 不可用的提示没有导致作业失败。
>
> 同一 `frozen.pth` 的公共 LAMMPS plugin run-0 为 job `132`，状态
> `COMPLETED`、`ExitCode=0:0`；公共结果目录的 Python/native 对照为
> `energy_eV=0`、最大力误差 `1.7404006890717042e-17 eV/Å`、最大 virial
> 误差 `1.898547746792545e-08 eV`，model identity 为
> `ni-fcc-engineering/v001`，backend/format 为 PT/`.pth`。job `133` 的公共
> 结果验证也为 `COMPLETED`、`ExitCode=0:0`。最终
> `workspace/reports/deepmd-bridge-v001/acceptance.json` 标记
> `engineering_status=passed`、`interface_status=passed`。
>
> 本次交付范围已经覆盖独立 bridge、现有 MLCC `TaskRecord`/`SiteRunner`、
> LAMMPS creator/parser 与公共 4 GPU 工程 fixture；**没有激活 Bundle release**。
> `production_qualification=false`、`scientific_status=not_qualified`、
> `design_assessment=not_assessed` 仍然有效。训练只使用 2 个 Ni frame、100
> steps、`local_batch=1`，`independent_validation=false`；吞吐结果不能外推为
> 生产性能或材料科学资格。此前 job `114` 的 `libmpi.so.12` 失败和 job `115`
> 的显式取消仍保留在下方历史记录中。

本记录对应用户提出的“ABACUS→DeePMD→LAMMPS 训练接口”独立开发前置探测。初始探测通过既有 SSH 别名 `v100` 完成，仅读取主机、Slurm、GPU、Python 包、ELF 依赖和 entry point；随后在得到明确授权后，额外提交了只做版本/插件检查的 Slurm 作业 114、115、118。没有安装包或修改 dpa4 环境，也没有读取模型、训练或启动数值 LAMMPS/MD；科学计算仍必须从 Slurm 作业执行。

## 结论

v100 已有一套可以直接作为第一阶段运行时候选的完整 DeePMD/LAMMPS 环境：

| 项目 | 实测值 |
| --- | --- |
| 运行时根目录 | `/home/v100/dpa4/current`（符号链接到 `releases/3.2.0`） |
| Python | 系统 `/usr/bin/python3`，3.12；运行时为独立 virtualenv 风格目录 |
| DeePMD-kit | `3.2.0`，PyTorch/TensorFlow 构建元数据均在 wheel 中；当前 Python 环境没有 TensorFlow 模块 |
| PyTorch | `2.11.0+cu126`，`torch.version.cuda=12.6`，`torch.distributed` 可用 |
| CUDA/NCCL | CUDA Python runtime 12.6，NCCL `2.28.9`；Torch 架构列表含 `sm_70` |
| LAMMPS | Python wheel/可执行文件 `2025.7.22.2.0`，源码标记 `stable_22Jul2025_update2`，MPICH 构建 |
| DeePMD C++/LAMMPS | `deepmd/lib/libdeepmd_c.so`、`libdeepmd.so`、`libdeepmd_backend_pt.so`、`libdeepmd_op_cuda.so`、`libdeepmd_lmpplugin.so` 均存在 |
| LAMMPS plugin wiring | `deepmd-kit` 注册 `lammps.plugins: deepmd = deepmd.lmp_check_build:get_op_dir`；`lammps.executable` 自动导出 `LAMMPS_PLUGIN_PATH` |
| MPI | 运行时 MPICH `5.0.1.post1`，`libmpi.so.12` 来自同一 dpa4 根目录；LAMMPS wheel metadata 要求其 MPICH ABI |
| 设备 | 4× Tesla V100-SXM2-16GB，driver `580.178.04`，compute capability 7.0，16 GiB/卡 |
| Slurm | `23.11.4`；`cpu`/`gpu` 分区均 `UNLIMITED`；节点 16 logical CPU、27,800 MiB 可调度内存、`gpu:v100:4` |

因此，最省事的工程路径是先在 Slurm 中使用这一套固定运行时做 2 GPU PyTorch DDP 训练烟测，再做同一冻结模型的 LAMMPS plugin `pair_style deepmd` run-0；2 GPU 的训练和接口证据通过后再把同一输入扩展到 4 GPU。这个结论只说明软件依赖已经具备，**不**说明 ABACUS 标注集、训练模型、LAMMPS 同几何 E/F/virial 一致性或材料科学资格已经通过。

## 只读探测证据

SSH 解析为 `v100@192.168.110.35:22`。主机报告为 `v100-System-Product-Name`、Linux `7.0.0-38-generic`。GPU 查询返回四张相同的 V100-SXM2-16GB，显存 16384 MiB、driver 580.178.04、compute capability 7.0。运行时 Python 查询返回：

```text
torch 2.11.0+cu126 cuda 12.6
available True count 4
arch_list ['sm_50', 'sm_60', 'sm_70', 'sm_75', 'sm_80', 'sm_86', 'sm_90']
nccl (2, 28, 9)
distributed True
```

Slurm 查询返回：

```text
PARTITION|AVAIL|TIMELIMIT|NODES|GRES|CPUS|MEMORY
cpu*|up|infinite|1|gpu:v100:4|16|27800
gpu |up|infinite|1|gpu:v100:4|16|27800
```

`/home/v100/dpa4/current` 的 `pip list` 中包含：

```text
deepmd-kit 3.2.0
lammps 2025.7.22.2.0
torch 2.11.0+cu126
cuda-bindings 12.9.7
cuda-toolkit 12.6.3
mpich 5.0.1.post1
numpy 2.5.3
```

DeePMD wheel 的全局构建配置显示 `enable_pytorch=1`、`enable_tensorflow=1`、`pt_version=2.11.0`、`lammps_version=stable_22Jul2025_update2`、`dp_variant=cuda`。当前导入 `deepmd.tf.env` 会因 Python 环境中没有 `tensorflow` 而失败；训练应明确选择 `--pt`，不能让默认 backend 隐式选择 TensorFlow。

`libdeepmd_lmpplugin.so` 的 ELF 依赖包含 `libdeepmd_c.so`；其 `RPATH` 为 `$ORIGIN:$ORIGIN/../../deepmd_kit.libs`。`ldd` 能解析同一目录中的 `libdeepmd_c.so`、`libdeepmd_cc.so`、CUDA OP 和动态 cudart。`libdeepmd_backend_pt.so` 依赖 `libtorch.so`、`libtorch_cpu.so`、`libc10.so`，由 `deepmd.lmp` 在 Python 入口加载 PyTorch library 目录后解析。直接调用包装器 `/home/v100/dpa4/current/bin/lmp` 会先执行 `lammps.executable`，因此会加载 `lammps.plugins` entry point；裸的 `.../site-packages/lammps/lmp` ELF 不应被当作已经配置插件的入口。

`dpdata` 没有安装，`horovod`/`mpi4py` 也没有安装。`deepmd-kit` metadata 把 `dpdata` 放在 `test`/`dpa-adapt` extra，把 Horovod/mpi4py 放在可选 `mpi` extra；这不影响 PyTorch DDP 路径，但 ABACUS 原生输出转换仍需单独提供 `dpdata` 或 MLCC 的显式转换器。不要把现有 dpa4 运行目录当作 MLCC 已发布环境，也不要把 DPA4 预训练权重当作 ABACUS 标签模型。

## 官方路径与版本匹配

官方 DeePMD-kit v3.2.0 并行训练文档说明：PyTorch/TorchScript 与 PyTorch-Exportable 后端使用 PyTorch distributed；单节点多卡用 `torchrun --nproc_per_node=N --no-python dp --pt train input.json`，不设置 `nproc_per_node` 时只使用一张卡。日志应出现 `world size > 1`、rank、设备和 `CUDA_VISIBLE_DEVICES`。该页还说明 DDP stage 0 是默认的最低通信开销路径，只有显存不足时才考虑 ZeRO/FSDP2；本项目第一烟测固定 stage 0，不提前加入优化变量。

- [DeePMD-kit v3.2.0 parallel training](https://docs.deepmodeling.com/projects/deepmd/en/v3.2.0/train/parallel-training.html)
- [DeePMD-kit easy install / LAMMPS extra](https://docs.deepmodeling.com/projects/deepmd/en/latest/getting-started/install.html)
- [DeePMD-kit v3.2.0 LAMMPS commands](https://docs.deepmodeling.com/projects/deepmd/en/v3.2.0b0/third-party/lammps-command.html)
- [DeePMD-kit pre-compiled C library and matching libtorch](https://docs.deepmodeling.com/projects/deepmd/en/stable/install/install-from-c-library.html)

官方 LAMMPS 接口文档规定 `pair_style deepmd models ...`、单个 `pair_coeff * *` 元素映射，以及 plugin 模式可以通过 `LAMMPS_PLUGIN_PATH` 或显式 `plugin load` 使 DeePMD style 可见。v100 wheel 已提供同版本 C++ plugin；因此不应把 Python `dp train` 成功当作 LAMMPS 已成功，仍需在 Slurm 中用实际冻结模型跑一次原生 LAMMPS 输入并保存 log、版本、模型类型图、元素映射、E/F/virial。

## 推荐执行顺序

1. 在本地准备 ABACUS 原生样本清单和训练/验证分组，明确能量 eV、力 eV/Å、virial/应力六分量的来源、符号、体积和 Voigt 顺序。样本转换只写入新的 MLCC 工作目录，不修改 ABACUS 任务或现有 dpa4 环境。
2. 在 v100 的 Slurm `gpu` 分区申请 1 节点、1 task、2 张 V100、约 8 CPU、12 GiB 内存；批任务中使用 `CUDA_VISIBLE_DEVICES` 由 Slurm 注入的可见卡，运行 `torchrun --nproc_per_node=2 --no-python /home/v100/dpa4/current/bin/dp --pt train ...`。保留真实 job ID、原生 stdout/stderr、`dp` 版本、Torch/CUDA/NCCL 信息和 training summary；不在登录节点启动训练。
3. 训练完成后，在 Slurm 中用同一运行时冻结模型（路径和 backend 明确写入证据），再用 1 GPU LAMMPS plugin run-0 证明 `pair_style deepmd` 加载模型。接口 run-0 的数据必须与 Python/DeePMD 参考使用同一几何、同一元素顺序、同一胞和同一冻结文件；比较能量、逐原子力和完整六分量 virial/stress。
4. 2 GPU 路径和接口证据通过后，只改变 Slurm GPU 数量与 `torchrun --nproc_per_node=4`，重新保存独立 job ID。没有 2 GPU 证据时不直接把 4 GPU 结果写成生产路径。
5. 训练模型、冻结文件、数据来源、方法/赝势、环境版本和 LAMMPS plugin 证据通过后，才由主集成窗口把 runtime/模型字段接入 MLCC Bundle；不把现有 dpa4 release 路径硬编码进公共 Bundle。

## 可执行模板与当前版本检查

对应脚本在 [`scripts/deepmd-runtime/`](../scripts/deepmd-runtime/)：

- `runtime-check.sbatch`：Slurm `gpu` 分区、1 GPU、2 CPU、4 GiB、5 分钟；只执行 `dp --pt --version/help`、Torch/LAMMPS 入口检查和原生 plugin `pair/deepmd` style availability 检查，不读取模型、不训练、不运行 LAMMPS 输入。
- `train-2gpu.sbatch`：固定 `/home/v100/dpa4/releases/3.2.0`，申请 2 张 V100，使用官方 PyTorch DDP `torchrun --standalone --nproc_per_node=2 --no-python .../dp --pt train`。输入和输出目录必须由 MLCC 提供，脚本不会安装依赖或改写 dpa4。
- `train-4gpu.sbatch`：2 GPU 和 1 GPU plugin run-0 证据通过后，使用相同输入把 DDP world size 改成 4。
- `lammps-plugin-run1gpu.sbatch`：固定同一 release，以 Python `lammps` 入口建立 `LAMMPS_PLUGIN_PATH` 后调用原生 `lmp`；只用于实际冻结模型的后续 run-0，不能用版本检查替代同几何 E/F/virial 对比。

版本检查的部署顺序是：只把 `runtime-check.sbatch` 复制到 v100 的专属目录 `/home/v100/projects/mlcc/development/deepmd-bridge-v001`，由 Slurm 提交并保存 `runtime-check-<jobid>.out`；再把原生 job 状态、stdout/stderr 和脚本路径下载到本地 `workspace/reports/deepmd-bridge-v001/runtime/`。该检查使用 release 绝对路径，不跟随 `/home/v100/dpa4/current` 浮动指针，也不写 dpa4。训练模板的示例提交如下，`DEEPMD_INPUT` 和 `DEEPMD_RUN_DIR` 只能指向已准备好的 MLCC 项目目录：

```bash
sbatch runtime-check.sbatch
sbatch --export=ALL,DEEPMD_INPUT=/home/v100/projects/mlcc/development/deepmd-bridge-v001/input.json,DEEPMD_RUN_DIR=/home/v100/projects/mlcc/development/deepmd-bridge-v001/run-2gpu train-2gpu.sbatch
```

这次版本检查的成功条件是：真实 Slurm job 完成；固定 release 的 `dp --pt --version` 返回 `3.2.0`；`torch.distributed`、CUDA/NCCL 和 1 GPU 可见；Python LAMMPS 实例在必要时加载同目录 `libdeepmd_lmpplugin.so` 后报告 `pair_deepmd=True`。它只接受运行时/插件可用性，不接受训练质量或 LAMMPS 数值一致性。

已执行版本检查：Slurm job `118` 在 `gpu` 分区以 1 V100、2 CPU、4 GiB、5 分钟请求完成，退出码 `0:0`，原生输出保存在 [`runtime-check-118.out`](../workspace/reports/deepmd-bridge-v001/runtime/runtime-check-118.out)。输出包含 `DeePMD-kit v3.2.0`、LAMMPS `22 Jul 2025 - Update 2` / MPICH `5.0.1`，以及 Python LAMMPS 实例的 `pair_deepmd True`。首个 job `114` 的真实失败输出也保留在 [`runtime-check-114.out`](../workspace/reports/deepmd-bridge-v001/runtime/runtime-check-114.out)：Python 进程启动时没有 `libmpi.so.12`。修正脚本在 Slurm shell 中先导出 release、Torch 和 DeePMD plugin 的共享库目录后，明确新提交了 job `118`；这不是调度器或应用自动重试。job `115` 是修正前的旧脚本，提交后曾因 `InvalidAccount` 被观察为 pending，随后由操作员显式 `scancel 115`；控制器最终记录它已启动约 4 秒后收到 `REQUEST_KILL_JOB`，最终为 `CANCELLED`、`ExitCode=0:15`，没有产生 stdout。完整原生状态和操作记录见 [`runtime-check-20261022.md`](../workspace/reports/deepmd-bridge-v001/runtime/runtime-check-20261022.md) 与 [`slurm-job-control-20261022.txt`](../workspace/reports/deepmd-bridge-v001/runtime/slurm-job-control-20261022.txt)。

固定 release 的只读 `pip check` 返回 `No broken requirements found.`，其中 `deepmd-kit 3.2.0`、`lammps 2025.7.22.2.0`、`torch 2.11.0+cu126`、`mpich 5.0.1.post1` 已安装；`dpdata`、`horovod`、`mpi4py` 缺失。`dpdata` 仍需在 MLCC 的 ABACUS 转换边界单独提供，PyTorch 单节点 DDP 不依赖 Horovod/mpi4py；该结果不授权改写固定 dpa4 release。

训练脚本和 plugin smoke 模板位于 [`scripts/deepmd-runtime`](../scripts/deepmd-runtime/)。模板默认失败即停、没有自动重试、没有哈希校验或引擎替换，也不会提交作业；运行者必须显式提供训练输入或 LAMMPS 输入，并在确认版本/资源预算后通过 `sbatch` 提交。当前 `inference.py`/`training.py` 的静态审查、同模型绑定缺口、单位/旋转路径和真实 rank 证据要求见 [`inference-audit-20261022.md`](../workspace/reports/deepmd-bridge-v001/runtime/inference-audit-20261022.md)。

## 当前缺口与风险

- `dpdata` 缺失：ABACUS→DeepMD raw/npy 数据转换尚未完成，不能仅凭 extxyz 几何文件训练。需要补充固定版本 dpdata 或实现并验收一个只读转换器；转换器必须保留原子顺序、元素映射、周期胞、energy/force/virial 单位和原生来源。
- 当前 dpa4 目录不是 MLCC 独立环境，且包含其他项目的 DPA4 运行/缓存。第一轮可把它作为只读候选运行时，稳定后应在 `/home/v100/projects/mlcc/` 建独立环境或明确可复制的环境锁定文件；不能修改或清理 dpa4。
- v100 的 `lmp -h` 不会因为未初始化输入而列出 plugin styles；实际 plugin 是否加载只能由 Slurm 中的真实 `plugin`/`pair_style deepmd` 输入和原生日志证明。ELF `strings`、entry point 或 `libdeepmd_lmpplugin.so` 存在都不能替代该证据。
- MPICH 是单节点同环境匹配的候选；若后续切换 LAMMPS 二进制、Python/torch 版本或 MPI，必须重新验证 C++ ABI、`libmpi.so.12`、plugin 加载和同几何结果，不能混用已有 MACE/ABACUS MPI 环境。
- 普通 DeePMD E/F/virial 模型不自动具备极化、外场、介电或铁电自由度；这些能力仍须独立模型和接口验收。

本文件的状态是 `runtime_candidate_observed`，不是 `training_accepted`、`lammps_interface_accepted` 或 `production_qualified`。
