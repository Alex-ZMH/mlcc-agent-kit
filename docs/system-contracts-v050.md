# MLCC 0.5.0 实施与验收（2026-10-21）

0.5.0 已通过原版 MatterAI 安装器、非桌面宿主真实 MCP 调用及单卡 ABACUS 小任务。H0 保持完成；H1、生产引擎切换、完整四性质及势/MD 未完成。本批仅新增 jobs 36、37，未运行陶瓷生产计算。

## 用户参数调整与真实结果

用户最新要求先跑通能力，电子阈值 1×10⁻⁴、网格统一 2×2×2。新配置是 `workspace/configs/h1-abacus-method-v003.json`，显式 `kpoints=[2,2,2]`、`scf_thr=0.0001`；截断保留既有100 Ry。ABACUS 原生 `scf_thr` 是电荷密度误差阈值，不能把它说成 VASP 的 eV 能量阈值。

| job | 任务 | 原生终态 | 电子收敛 | 用时 | 范围 |
|---|---|---|---|---|---|
| 36 | h1-ni-strainminus-v002 | COMPLETED / 0:0 | 11步 | 8分57秒 | 用户修改前已启动；9³、1e-8、−0.5%应变 |
| 37 | h1-ni-scf-v003 | COMPLETED / 0:0 | 7步，DRHO=1.3831e-5 | 10秒 | 新参数2³、1e-4；Ni单点能力验证 |

job37 自由能 −16778.90745945708 eV，最大力0.15562132315493127 eV/Å；这是位移起点单点，不是离子弛豫通过。原生 warning.log 保留 `Threshold on eigenvalues was too large.`；最终原生电子收敛已达到选定阈值，没有修改原生日志或重跑。stderr 是单rank/单OpenMP线程信息。两任务均单V100/单rank/8GiB/20分钟上限、无requeue，最终队列与GPU计算进程为空。

旧正应变请求 `ni-strainplus-v002.json` 未提交。没有将job37与旧9³数据混算有限差分；应力符号真实验收暂缓。粗参数通过只证明本方法输入、运行、解析和交付接通，不授予科学精度或陶瓷方法资格。旧0.4.1安装目录和历史任务保留。

## 已实现的调用合同

```text
mlcc create-abacus --study <study.json> --model <model目录> --method <method.json> --site <site.json> --request <request.json>
mlcc parse-abacus --task <task.json> --site <site.json>
```

- `abacus_tasks.create_abacus_task`：显式研究/模型/方法创建 PW SCF 或固定胞 relax；只写输入。泛函、自旋、逐元素初始磁矩、占据、展宽、kpoints、截断和阈值由方法给出；设备/求解器显式；站点提供MPI/程序/赝势文件路径。没有Ni科学默认值。
- `prepare_abacus`：要求显式三方向正整数 kpoints；保留元素分组和源atom_id映射。固定占据、非磁性、共线自旋、多元素顺序经局部测试；这不代表这些分支已有真实数值资格。
- `parse_abacus_task`：保存原生COMPLETED/0:0后读取实际suffix输出，检查有限E/F/应力及电子/离子收敛。力标签逐个完整匹配，Ni1/Ni2交换、Ni/N前缀混淆都报原始域错误。
- `strain.isotropic_strain_model`：指定ε、固定分数坐标并记录F、体积及atom_id。
- `strain.compare_strain_tasks`：只接受同方法的−ε/0/+ε原生完整结果，用有限展宽自由能导数核对应力迹；单测通过、真实三点未齐，不是全张量/Cij工具。
- 已有七个MCP工具继续执行准备、传输、提交、查询、取消和回传；没有新增空工具、后台自动工作流或自动重提。

续接/依赖/交付共享原产物检查，结果task_id必须匹配。metadata或result.json不能冒充原生科学日志；缺源文件不再给出有效科学交付。静态DFT不得重标为有限温度MD或已施加目标压力，已冻结任务条件必须一致。Study目标外压与固定胞实际未施加外压分开。修复了固定占据 `smearing_method=null` 与原生 `fixed` 的显式对应。

## 文件、命令与证据

改动的实现：`mlcc-agent/src/mlcc/{abacus,abacus_tasks,cli,results,workflow,studies,strain}.py`；对应tests，`scripts/h1/abacus_fixture.py`、`compare_strain.py`、`scripts/system/verify_contracts.py`。Bundle版本、README、Agent说明同步0.5.0。配置/请求和真实产物均在workspace，未进入能力包。

| 命令/验证 | 退出状态 | 证据 |
|---|---|---|
| `workspace/.venv/Scripts/python.exe -m pytest -q -p no:cacheprovider mlcc-agent/tests` | 0；82 passed | `workspace/reports/system-v050/unit-tests.txt`；96条ASE/NumPy弃用告警保留 |
| create-abacus → prepare → transfer → submit → query | 全部0，job37 | `quick-execution-commands.json`，每条保存完整参数与stdout/stderr |
| 已安装0.5.0 CLI collect → parse-abacus | 全部0 | `quick-completion-commands.json`，含实际PYTHONPATH |
| job36 query/collect/parse | 全部0 | `workspace/tasks/h1-ni-strainminus-v002/task.json` events与原产物 |
| pip install --no-deps --no-cache-dir --retries 0 -e mlcc-agent | 0 | `pip-install.txt` |
| 原版 npm run bundle:install -- D:\project\mlcc\mlcc-agent --workspace D:\project\mlcc\workspace --enable | 0 | `installer.txt` |
| verify_contracts.py --bundle-root workspace/.zeus/bundles/mlcc-agent/0.5.0 --report-dir workspace/reports/system-v050/installed | 0 | `installed/acceptance.json`；jobs32/33/34历史文本未修改 |
| headless-matterai-mcp.ts --workspace workspace --report workspace/reports/system-v050/matterai-headless-session.json | 0 | 原版runtime→实际mlcc_list_tasks完成，Bundle0.5.0 |
| probe_mcp.py ... --launcher .../0.5.0/tools/mlcc_mcp.py --query-task h1-ni-scf-v003 | 0，isError=false | `mcp-installed-job37.json`，7工具、真实Slurm终态 |

上表未写前缀的证据均位于 `workspace/reports/system-v050/`。`real-job-summary.json` 汇总数值/终态，两个 `*-delivery.json` 是已安装函数的真实交付，`acceptance.json` 是本批验收汇总。测试缓存按已核实绝对路径移至报告目录，未删除；未改上游源文件、服务器配置或驱动。

## 尚未完成与下一最小任务

H1仍缺同方法完整有限应变真实标定、生产材料赝势/方法/功能资格及显式生产切换；不能据此宣称生产DFT可用。通用输入已有实现，CZO/BTO多元素生产数值尚未验证。P5–P8四性质、P9势/训练资格、P10/P11 LAMMPS与两条高分子分支、P12完整设计交付继续未完成。

下一最小任务：以job37的新粗参数为参考，再做同方法±0.5% Ni小任务检查应变/应力能力；继续保留精度资格未完成，不开启全材料/温度矩阵。当前批次的两任务预算已经用完，未额外提交。
