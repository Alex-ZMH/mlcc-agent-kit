# J3：LAMMPS 静态 Cij 到领域参数 JSON

本项承接 J1/J2 的领域 JSON 队列。首次 demo 完成后推进 J4，不做精度扫描、材料资格包装或独立小版本发布。当前只确定实现范围，尚无 J3 原生 job。

## 唯一最小 demo

- 复用 CZO Pnma host20、DeePMD 势146、prepare-560 保存的 Study/potential/site。势的原始状态不变，不训练或替换势。
- 原始固定胞参考一点；工程 Voigt 顺序 `xx,yy,zz,yz,xz,xy`，每方向 `-0.001/+0.001` 各一点，共13点。复用 `elastic.plan_elastic_strains` 和 `voigt_strain_model`。
- 固定分数坐标、固定应变胞、无离子弛豫、无时间积分，零速度 virial-only `run0/static_tensor`。这是所给参考几何的有限差分静态切线，不要求先优化几何。
- 复用现有 `potential_qualification` 静态计算入口及其原生应力读取，任务的请求/来源另明确 `elastic_static_demo`；不为同一 run0 另造引擎、调度或资格框架。
- 由现有 ModelArtifacts 写入函数保存12个应变派生模型，原子ID和 root 模型来源保留。每个派生任务的 child Study 显式选择其模型并记录 parent Study；最终 Cij 产品绑定 root 模型和 root Study。

## 数值消费

只读13份已保存的 LAMMPS result；不再解析日志/轨迹。原生 `stress_GPa` 已是源笛卡尔坐标、张力为正，按上述 Voigt 顺序取分量；保留静态参考应力 `sigma0`，以 `sigma(strain)-sigma0` 和工程应变调用既有 `elastic._fit_cij`。

输出原始6×6 Cij（GPa）、参考3×3应力、预测/残差及应变幅值、固定离子约束、分量顺序、单位/符号/坐标、原子映射、模型/Study和实际job来源。不得强制张量对称化、删负值、假设稳定性、加入第二幅值或据此计算必须正定才能解释的材料量。完整缺失/失败点保留原始错误，不能填零。

复用 `domain_parameter_product` 与 `deliver-properties --domain-parameters`，终点仍为同一 Study 中的领域 JSON。ABACUS 专用读取、符号与旧弹性科学检查不改动。

## 预算与分工

- 准备/新路径检查：v100 Slurm CPU2、GPU0、6GiB、10min、no-requeue。
- 每个新增 run0：GPU1、CPU2、1rank、6GiB、10min、no-requeue；最多两点同时运行。提交前读取真实共享资源，不抢占或改动他人作业。
- 一次保存原生解析及消费：CPU2、GPU0、6GiB、10min。成功部分复用，修复只续接失败节点。
- 第三窗口：准备函数、应变派生模型/child Study、现有 create/runner 静态入口的最薄接线及专属新检查。新模块建议 `lammps_elastic.py`，不改 CLI/property_delivery。
- root 的 Luna：独占 `lammps_elastic_response.py` 与专属新检查，保存 stress→既有拟合→领域 JSON 的薄适配。原实施窗口在 J2 交回后负责公共 CLI 和同 Study 消费，保持共享入口单一所有者。
- root：协议、预算、原生任务控制、集成。J2 原生源已保存，消费者仍由原实施完成；第三可并行准备独立 J3 producer 模块，不改共享 CLI/property_delivery。J3 原生提交仍在 J2 首次消费之后。

复用函数和已有来源见 `workspace/reports/czo-bulk-thermal-v001/j3-reuse-notes.md`。未运行代码不记为功能完成；最小真实请求→执行/保存结果→领域 JSON→Study 一次跑通即完成本功能。

producer 同时写出 `response-request.json`：`schema=mlcc.lammps-elastic-response-request.v1`，`study_path/model_path` 指 root，`reference={task_path,result_path,strain_voigt}` 指参考，`samples` 含12份同结构记录。消费者入口 `build_lammps_elastic_response(request_path)`；准备时结果文件尚不存在是正常状态，不伪造或补齐。
