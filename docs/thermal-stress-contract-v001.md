# 显式参考与历史下的热致应力变化

2026-10-25。独立`thermal_stress`切片只消费保存的局部应力产品、温度历史及机械约束历史。第三窗口独占原生六/九分量virial读取/转换；本片不改`local_stress.py`、原生creator或解析器，不新增材料计算，不从442总力推导单界面牵引。

## 最薄关系

已保存局部应力区域提供source Cartesian、拉伸正、GPa的完整3×3张量。对显式参考R和目标i只做`Δσ_i=σ_i−σ_R`，不重新求virial、不重做Prism旋转、不对称化或压成六分量、不假定参考无应力。结果是指定原子组/体积的应力变化，保留virial/kinetic分量约定。

两端必须是同Study、模型/版本、势/版本、method_set、source atom映射、固定晶胞、区域ID/原子集合、体积/定义和原生分量约定；不相容身份直接报原错误。缺参考、张量或体积时保留null和具体缺项。

分别给出参考与目标所选应力帧的真实step/time，以及逐帧对应的已记录区域温度和显式机械约束历史，不从热浴设定值推观测温度。机械约束记录固定胞、周期边界、固定原子组和显式loading定义。若历史齐全且所有样本约束相同，可把Δσ标为`same_constraint_thermal_stress_change`；约束/载荷不同则只保存`stress_change_GPa`并标`mixed_thermal_mechanical_change`，`thermal_stress_change_GPa=null`。缺历史时同样保留普通差量和原因，不补零或推断约束。

## 直接领域函数

`thermal_stress_change(reference, states)`接收已绑定的标准状态，不读文件。每个状态包含：

- `state_id`；`identity`：study_id/model_id/model_version/potential_id/potential_version/method_set/source_atom_ids/source_cell_angstrom/contribution/kinetic_included/native_component_order。
- `region`：region_id/atom_ids/volume_angstrom3/volume_definition；`stress_GPa`为完整3×3或null，单位/基底/拉伸正由薄适配核对。
- `frame_keys`：按原记录顺序的`{step,physical_time_ps}`；`temperature_history`与`mechanical_history`可为null。
- 温度history的`samples`为`{step,physical_time_ps,temperature_K}`；机械history的`samples`为`{step,physical_time_ps,constraint}`，constraint包含`cell_angstrom`、`boundary`、`fixed_atom_ids`和显式`loading`。两类history有`source_files`，需与本状态帧一一对应。`loading`为`{kind:"none"}`或`{kind:"declared",definition,parameters}`，不默认填字段。
- `missing_evidence`和`source_refs`按原样携带。

函数输出每状态原值/参考值、普通差量、热致差量、分类、缺项、原始历史及完整identity/region。没有材料精度门槛、自动资格升级、温度拟合或插值。

`same_constraint_thermal_stress_change`表示给定热历史、相同显式机械约束下观测到的应力变化。结构变化和未弛豫瞬态也可贡献，分类不证明温度的唯一因果作用，不等于平衡热应力系数；不为此增加计算或开发门槛。

## 保存源薄适配与公共入口

`thermal-stress --study --request --output`读取`mlcc.thermal-stress-request.v1`。请求`reference`可null，`states`为显式状态数组；每项有state_id、region_id、stress_product_path、temperature_history_path、mechanical_history_path和temperature_product_path，缺输入显式null。stress_product_path指向已保存`mlcc.local-stress-product.v1`；选其中明确region，直接读取stress_GPa与原帧，绑定原task/model/势/Study及源文件。没有应力产品的状态保留缺项。

独立历史文件schema为`mlcc.region-temperature-history.v1`或`mlcc.mechanical-history.v1`，具有task_id/native_job_id/model_id/model_version/region_id/atom_ids/samples/source_files，与本状态源绑定；机械文件另声明原protocol，不能由本次请求改写源协议。source_files必须指向实际已有证据。区域温度文件是明确记录的输入表，不由适配器合成。

只有空间温度产品而没有应力产品时，region_id可显式为null；标准状态的区域原子、体积、分量约定为null，frame_keys为空。保留原温度产品与具体缺项，不生成应力区域或伪造映射。

可选temperature_product_path指向已保存`mlcc.interface-thermal-product.v1`，只保留其中真实native_thermal.profile_frames及source任务/区域定义。空间bin没有source atom IDs时，不自动转成固定原子组温度history；空bin的原始计数与原值保留，不能把空bin的零当区域观测。产品热浴设定值不替代history。

`deliver-properties --study --thermal-stress --output`只读保存新产品，绑定各原source task与Study，原样交付差量/null/历史与artifact清单，不重算差量或解析原生表。

## 当前真实复用及验收

- 447/448为8Ni/Ni EAM静态局部应力；whole_cell有体积和GPa张量，subset_without_volume没有体积；缺匹配参考、温度和约束历史。
- 462消费458的18原子Ni/BTO MACE热MD，有11帧真实空间温度历史，无逐原子virial；AB bin6部分为空，heat_allocation为null，瞬态原值不改写。它与447身份不同，分别作为两个Study的缺项实例，不能拼成热应力对照。
- 数学夹具独立验证非对称3×3差量、匹配约束、改变载荷、缺温度/体积/参考与不相容身份。只在v100 Slurm验新增路径并通过公共入口消费两份真实保存源；不重跑447/448/458/462、MD04/MD06/MD05或材料矩阵。计算限为1CPU/2GiB/5min/no-requeue后处理，版本以提交时实际源码为准。

同批0.46公共集成复用已交回的DeePMD九分量466/468和10项原生/领域检查。保存`centroid-local-stress.json`沿`deliver-properties --local-stress`进入原CZO Study；bulk `potential_qualification`允许interface来源为null，保留parent_model、势、method和真实native job。界面任务的必需来源继续核对。只补保存交付与CLI参数解析，不再解析原生dump、转换张量或执行LAMMPS。

2026-10-25源码验收494已完成：COMPLETED/0:0，8秒，34项新增检查和5条公共命令通过。462的11帧profile与thermal_response原样保留，Ni/Ni和Ni/BTO热致差量均因缺源保持unresolved；466/468的保存九分量产品已进入原CZO Study。完整命令、资源、原值和交付见`workspace/reports/thermal-stress-v001/run-494/acceptance.json`。该证据完成源码接线验收；0.46安装/激活由主线另记，不重跑本批函数或旧原生数据。
