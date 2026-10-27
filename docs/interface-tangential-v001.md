# P11 显式切向小位移与卸载工程路径

2026-10-26执行结果：job531（29项新增检查/输入）、532（原生最小化）、533（公共消费/同Study交付）全部COMPLETED/0:0，三点原生force tolerance；root已审收本功能切片。源码0.48，启用0.47/回退0.46不变，未安装发布。详情见workspace/reports/interface-tangential-native-v001/report.md及acceptance-reviewed.json。下文保留实际执行合同和分工。

2026-10-26。来源为原总计划P11.08/P11.15及用户持续开发授权。定向检查现有`normal_response_from_points`、`lammps_interface_normal`、任务reader、CLI和Study交付，当前仅有法向位移/投影，未发现切向公共语义。本轮直接补这一功能；0.47启用冻结，源码0.48，不重复524–530或新增发布/安装切片。

## 输入与输出

- `kind=interface_tangential`，`purpose=interface_tangential_response`；`tangential_response.schema=mlcc.interface-tangential-protocol.v1`。显式单位法向n与切向t必须正交；n继续绑定已有界面几何，q沿t移动，不能以t伪装几何n。面积、双周期界面和源原子映射继续绑定。
- 首切片限`fixed_cell_clamped_internal_relaxation`：固定/移动夹持及自由原子组、min_style/etol/ftol/maxiter/maxeval均显式给出。沿现有相邻q差值、两夹持setforce、minimize、unfix、同几何run0采集原始力与xu坐标；保留原生停止原因和未收敛状态。
- `tangential_response_from_points(protocol, atom_ids, points)`返回`mlcc.interface-tangential-response.v1`。原始3D力、坐标、能量和原子ID保留。移动夹持反力`R_t=-sum(F_moving) dot t`，单位eV/Å；胞净切向应力为`R_t/A*160.21766208` GPa。面积只除一次，不除界面数，不声称单界面牵引。
- 相邻区间输出`ΔR_t/Δq`（eV/Å²）及`Δτ/Δq`（GPa/Å），称区间切向刚度，不称材料剪切模量。dq=0时为null及明确原因。加载/卸载分支和输入顺序原样保留；坐标返回仅报告能量/反力/应力残差，不推断物理恢复、塑性或耗散。
- `read_interface_tangential_task(task_path)`输出保存产品，字段`tangential_response`；未完成原生任务为unresolved/null。`interface-tangential --task --output`和`deliver-properties --interface-tangential`沿已有Study绑定，保留原生job/终态、单位、来源及缺项。

## 文件分工

原实施窗口独占`lammps_interface_normal.py`、`lammps.py`、`lammps_tasks.py`及必要薄切向reader、新输入/原生/接线测试；共享CLI/property_delivery/两项Skill由该窗口串行接线。第三窗口仅独占新`interface_tangential.py`及其新领域测试。主线持有科学合同、计划、审阅和集成；Luna准备`workspace/reports/interface-tangential-native-v001/`中的新路径输入/执行材料。任何跨所有权修改先交回，不并行改同一文件。

复用runner、Prism、原生反力和停止摘要读取，不复制整份解析器，不新增来源框架；normal API及已保存产物不改语义。仅对实际变更路径增加有意义检查，静态检查不替代原生执行。

## 唯一新增工程预算

复用prepare-442的8原子Ni/Ni工程模型、Ni_u3 EAM和已核CPU LAMMPS；不创建模型或势、不替换引擎。n=[0,0,1]、t=[1,0,0]；固定[0,3]（z=0）、移动[4,7]（z=3.52Å）、自由[1,2,5,6]；面积12.3904Å²、双周期界面2。q=0→0.01Å→0，分支reference/loading/unloading；cg、etol=0、ftol=1e-6 eV/Å、maxiter=200、maxeval=2000。此为新切向路径工程输入，不赋予Ni/Ni材料资格。

合并新增软件检查与输入准备；独立原生job；独立原生消费。每段CPU1、2GiB、5分钟、no-requeue。所有数值/建模/解析/检查只在v100 Slurm。Windows只编辑、传输/公共runner控制和看证据；原生终态由真实控制器查询保存，不从进程退出码推造。失败保留原始错误，经主线定位后只修失败行为，不自动重试。

不增加Ni/BTO材料MD、破坏/温度/速度矩阵、DFT、训练或势对照。P4参数及真实界面电势源的局部缺项不阻塞此功能。总体P11可逆恢复、单界面性质、统计和材料精度不由本切片宣称完成。
