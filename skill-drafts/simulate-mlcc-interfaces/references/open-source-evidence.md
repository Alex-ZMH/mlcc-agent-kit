# MLCC 原子计算开源项目核实

核实日期：2026 年 10 月 19 日。证据层级区分为实际源码/算例、项目文档、论文方法/摘要。下列仓库未在本项目中安装或完成材料计算；“支持接口”不等于已有 MLCC 合格势和输入。

## 推荐的软件组合

主选：ABACUS + dpdata + DeePMD-kit + LAMMPS + DP-GEN。APEX 用于可支持的体相/表面性质对照。MOOSE 为热力学与断裂的连续尺度实现候选。

| 项目 | DFT 与 MD 证据 | 与本项目的关系 | 判定 |
| --- | --- | --- | --- |
| [deepmodeling/dpgen](https://github.com/deepmodeling/dpgen) | 有 ABACUS PW/LCAO 标注与 LAMMPS 探索算例 | 主动学习和任务组织 | 优先采用的方法链，材料输入需自建 |
| [deepmodeling/abacus-develop](https://github.com/deepmodeling/abacus-develop) | 有 DPGEN 接口实际目录与 Al 初始/训练配置 | DFT、AIMD、力/应力参考 | 核心计算引擎 |
| [deepmodeling/deepmd-kit](https://github.com/deepmodeling/deepmd-kit) | 训练势和 LAMMPS 集成，支持多种后端 | 把 DFT 标注变成 MD 势 | 模型与插件版本应成套验证 |
| [deepmodeling/dpdata](https://github.com/deepmodeling/dpdata) | 注册 ABACUS SCF/MD/relax 与 LAMMPS 格式 | 元素、坐标、能量、力和 virial 的转换 | 数据桥，不是完整计算工作流 |
| [deepmodeling/APEX](https://github.com/deepmodeling/APEX) | 文档明确 ABACUS/VASP/LAMMPS calculator，并列 EOS、弹性、表面与 decohesive line | 体相/表面性质自动化与对照 | 不直接等于异质聚合物界面或断裂相场 |
| [aboys-cb/NepTrain](https://github.com/aboys-cb/NepTrain) | 有 ABACUS 标注示例，另支持 LAMMPS/GPUMD 探索 | NEP 势路线备选 | ABACUS 示例默认 GPUMD；ABACUS+LAMMPS 组合仍应做集成验证 |
| [jthwang22/aimd-mlp-lammps](https://github.com/jthwang22/aimd-mlp-lammps) | SIESTA AIMD→DeePMD→LAMMPS，金–烷基二硫醇–金示例 | 金属/有机接触方法类比 | 非 ABACUS，非陶瓷；API 未识别明确许可证，复用前需核实 |
| [huiihao/Spiral](https://github.com/huiihao/Spiral) | 提供 PbTiO3 的 DFT 输入/训练数据/DP 模型/LAMMPS 输入 | 同类钙钛矿的多尺度数据组织参考 | 不可直接替换为 BaTiO3 或 Ni 界面势；README 与 LICENSE 的使用范围需厘清 |
| [stfc/janus](https://github.com/stfc/janus) | CP2K/QE→N2P2→LAMMPS 的历史方法链 | 工作流参考 | 已归档，项目指向 janus-core；不作为新项目主框架 |

本次检索未定位到包含 BaTiO3/Ni、保留/临时聚合物两分支、ABACUS DFT、经过验证的 LAMMPS 势以及断裂相场参数传递的现成端到端仓库。这是本次检索的范围结论，不构成对全部 GitHub 项目的不存在证明。

## 已经核实到文件的 ABACUS 与 DP-GEN 证据

### DP-GEN

本次 GitHub API 返回 master 树对应提交为 `0b9acec837474d2a93fa010598472feb8f69f82a`，树未截断。

- [LCAO Al 运行配置](https://github.com/deepmodeling/dpgen/blob/0b9acec837474d2a93fa010598472feb8f69f82a/examples/run/dp2.x-lammps-ABACUS-lcao/fcc-al/run_param.json)。存在 `sys_format: abacus/stru`、训练配置、model deviation 和 `fp_style: abacus`。
- [相应运行资源配置](https://github.com/deepmodeling/dpgen/blob/0b9acec837474d2a93fa010598472feb8f69f82a/examples/run/dp2.x-lammps-ABACUS-lcao/fcc-al/machine.json)。路径由仓库树核实，具体集群配置需要替换。
- PW 目录为 `examples/run/dp2.x-lammps-ABACUS-pw/fcc-al`，另有 methane 示例。
- 初始化目录为 `examples/init/abacus/fcc-Al-lcao`、`examples/init/abacus/fcc-Al-pw` 等。
- [参数源码](https://github.com/deepmodeling/dpgen/blob/0b9acec837474d2a93fa010598472feb8f69f82a/dpgen/generator/arginfo.py) 中 `fp_style_variant_type_args` 注册 `abacus`，`fp_style_abacus_args` 处理 UPF/ORB、INPUT 与 K 点设置。

这些是 Al/CH4 的接口示例。Al 的非磁性、步长、温度、力阈值、零 virial 权重和小训练网络均不能作为 Ni/BTO/聚合物的生产参数。

### ABACUS

本次 API 返回 develop 树对应提交为 `7be5df9759e8b76db724297492044ef644833f28`，树未截断。

实际目录为：

```text
interfaces/DPGEN_interface/
  README.md
  init_and_run/
    Al.STRU
    INPUT
    INPUT.md
    KPT
    init.json
    machine.json
    run_param.json
  autotest/
    INPUT
    INPUT.rlx
    property.json
    machine.json
```

可从 [固定提交的接口目录](https://github.com/deepmodeling/abacus-develop/tree/7be5df9759e8b76db724297492044ef644833f28/interfaces/DPGEN_interface) 核对。接口路径由 GitHub API 树验证；浏览器工具对部分目录页抓取失败，不影响 API 已返回的路径证据。

### 具体的版本差异

[ABACUS DP-GEN 文档](https://abacus.deepmodeling.com/en/latest/advanced/interface/dpgen.html) 仍出现 `examples/dpgen-example/init_and_run` 旧路径以及 `fp_style: abacus/scf` 写法；上述已检查的 DP-GEN 提交使用 `fp_style: abacus`。dpdata 的 `abacus/scf` 是数据读取格式，与 DP-GEN 后端选择字段不能混用。

因此，实际工程需要按固定提交的 schema 生成配置，先验证单点/数据转换/短 MD/模型导出闭环。不能仅凭最新文档或最低推荐版本认为任意版本组合均兼容，也不根据历史 dpgen2 issue 推断当前版本支持范围。

## 维护与许可证记录

GitHub API 本次读取到：ABACUS 和 DP-GEN 为 LGPL-3.0；NepTrain 为 GPL-3.0；Janus 为 BSD-3-Clause 且 archived=true；aimd-mlp-lammps 的 license 字段为空。Spiral 的 API 标记 MIT，但 README 对文档有 CC BY-NC-SA 4.0 表述，模型、数据和脚本的实际授权范围需要分别确认。

APEX 的仓库元数据 API 在批量请求时超时，其能力判定来自已读取的官方 README，不记录未经成功读取的维护日期或 API 许可证。活跃状态和许可证应在选定依赖时重新固定，避免用星数或近期提交替代科学验证。

## 连续尺度开源候选

| 项目 | 实际内容 | 建议用途 |
| --- | --- | --- |
| [idaholab/moose](https://github.com/idaholab/moose) | 多物理框架；相关模块有热应变、塑性、相场断裂和内聚区模型 | 首选实现候选，组合后需做本项目基准 |
| [rh201/Phase-field-Modelling-of-Thermal-Fracture](https://github.com/rh201/Phase-field-Modelling-of-Thermal-Fracture) | `elasticity.i`、`fracture.i`，MOOSE 的热力断裂研究算例 | 研究热载荷和交错求解的参考输入 |
| [taojinllnl/Thermomechanical_phasefield](https://github.com/taojinllnl/Thermomechanical_phasefield) | deal.II 热力相场断裂及不同求解方案 | 热力耦合与求解器对照，不与 MOOSE 混用输入格式 |
| [newfrac/fenicsx-fracture](https://github.com/newfrac/fenicsx-fracture) | FEniCSx 断裂力学示例 | 便于检查断裂基本模型和数值基准 |

这组项目承担连续尺度，不宣称它们本身运行 ABACUS 或 LAMMPS。DFT/MD 与相场间的参数传递由本项目的数据合同和模型校准完成。

## 材料与方法依据

- [Processing of barium titanate tapes with different binders for MLCC applications Part II](https://www.sciencedirect.com/science/article/pii/S0955221903003340)：研究 PVB 与其他粘结体系的生片加工，支持临时粘结剂分支的材料背景。
- [Binder removal and microstructure with burnout conditions in BaTiO3 based Ni-MLCCs](https://www.sciencedirect.com/science/article/pii/S027288420300049X)：排胶、残碳与微结构的工艺问题；不能由此得到本项目具体反应势或速率。
- [Effect of local oxygen activity on Ni–BaTiO3 interfacial reactions](https://www.sciencedirect.com/science/article/pii/S1359645406002321)：实验与热化学分析表明氧活度和局部还原应纳入界面化学背景。
- [Computational approaches for investigating interfacial adhesion phenomena of polyimide on silica glass](https://www.nature.com/articles/s41598-017-10994-8)：拉伸、剥离、滑移方法和聚合物构象效应的类比；其基底是 silica，不能据此声称 PI 在 BTO/Ni 上的性能。
- [A unified phase-field theory for the mechanics of damage and quasi-brittle failure](https://doi.org/10.1016/j.jmps.2017.03.015)：强度、断裂能及软化律与相场损伤模型的关系。
- [LAMMPS hybrid 文档](https://docs.lammps.org/pair_hybrid.html)：说明多体混合势和 QEq 的物理限制。
- [MOOSE 相场断裂材料说明](https://mooseframework.inl.gov/falcon/source/materials/ComputeLinearElasticPFFractureStress.html) 与 [混合模式内聚律说明](https://mooseframework.inl.gov/magpie/source/materials/cohesive_zone_model/BiLinearMixedModeTraction.html)：模型结构参考；具体主仓版本和组合接口在实施时确认。

仅将论文方法和摘要中可确认的信息用于上述背景，不从无法获取的全文推导数值参数。仓库读写、运行成功、材料适用性和实验有效性是不同证据级别。
