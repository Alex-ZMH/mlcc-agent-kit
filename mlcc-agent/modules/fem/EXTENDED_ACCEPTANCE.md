# FEM 0.3.0 器件扩展接入与验收

日期：2026-10-22，Asia/Shanghai。用户明确要求依次接入已审阅的电热、AC-EQS和二维电磁能力，保持原FEM框架和电仿真接入标准。本轮完成模块内正式接入；没有修改公共mlcc/schemas/tests/docs/bundle、其他模块或experiments，没有安装/升级环境、运行LLM或新增物理模型。

## 已交付

在同一module.json/adapter.py/science_entry.py链中增加electrothermal_2d、ac_eqs_2d、electromagnetic_2d；保留原electrostatics_2d与electrostatics_2d_quantities、历史任务及旧schema。专业输入/输出、示例、部署v2、方法Skill、测试、源哈希与运行说明见[EXTENDED_GUIDE](EXTENDED_GUIDE.md)、[module.json](module.json)、[EXTENDED_SOURCES](EXTENDED_SOURCES.json)。

三个新操作均由Windows公共preflight→run(defer)→worker→result/status/artifact调用既有WSL，独立任务目录等待真实结果。原始输入、canonical SI、单位规则、原生场、映射、日志和结果一起登记；没有将实验频扫/套件/旧任务系统搬入模块。公共唯一单位核心处理其已支持kind，其余物性用严格固定SI字段，不建立第二单位表。软件状态、质量判断与结果规范化不依赖LLM。

## 本轮实际任务

| 算例/操作 | 新公共task_id | 执行 | 总损耗W | 最高温升K |
| --- | --- | --- | --- | --- |
| electrothermal_2d | task-2bd9b855fa29416dbedafc7b60900200 | succeeded | 0.00970767587268 | 1.91824372105 |
| ac_eqs_2d | task-557af8194a224f25a15fcac71ef00d72 | succeeded | 0.0178086104462 | 3.518994208 |
| electromagnetic_2d | task-57b5a132265249c4bd57eec17e5b5555 | failed | — | — |
| electromagnetic_2d | task-0408aff11bd344e287b79c251439035f | succeeded | 0.0087401620523 | 5.32723863133 |
| et_zero | task-2bea610ed3a94dbeb17ede7e1b13b057 | succeeded | 0 | 0 |
| et_ac_peak_robin | task-ea258afdf41148f58fa2812c1b84f810 | succeeded | 0.016201869147 | 66.6104724208 |
| ac_layered_no_heat | task-e227acb936d14e4b8bb49f28281471cb | succeeded | 0.0227472529155 | — |
| ac_zero | task-f4608d85b29b4727bc3f1864f4afc9bb | succeeded | 0 | 0 |
| old_static | task-bb6feb8897f543ad99b8ca53695cda1b | succeeded | — | — |
| electromagnetic_2d | task-ead43fba81944f888e2b3eb366d8ac24 | succeeded | 0.0087320390624 | 5.32475559797 |

所有成功任务evidence_kind=real_computation。相同激励/几何时原始输入快照保留；不能把这些合成参数结果解释为商业器件预测。thermal.enabled=false返回温度null，零损耗的热阻null；没有把未计算结果填0。

- 主电热与AC输入：6间隙、10/0V、深度1mm、目标网格5μm；10198父网格三角形。电热DC功率0.009707675872676841W、温升1.918243721052335K，与原实验E3/coarse完全相同；AC 100kHz：Cp=12.8930378104nF，Z=(2.71237638122−j123.382920129)Ω，与原实验AC3/uniform_f100000的Y/Z完全相同。
- 电磁：1间隙、1MHz、0.1A RMS，指定闭合引导端口。首次成功粗网格5μm：9858单元，Z=(0.874016205230−j73.8671348367)Ω，P=0.008740162052298911W，温升5.327238631333786K。
- 发现粗网格原始梯度热流平衡误差18.3153%，没有用离散热平衡约1e-12掩盖。补一个原实验采用过的2μm网格，59414单元，Z=(0.873203906240−j73.7977859484)Ω，P=0.008732039062402153W，温升5.3247555979661225K，原始热流误差7.30458%。默认电磁示例现为该2μm设置；这只是两级观测，不是通用收敛/局部热流精度验收。raw_flux_acceptance继续not_checked。
- 4个针对性分支：ET零损耗严格P=0/ΔT=0；规定AC峰值/RMS转换与Robin实际出热；AC半高度双材料、非零虚电势和关闭热（无伪造温度）；AC无损严格P=0/ΔT=0。没有做参数扫描。
- 旧静电新任务task-bb6feb8897f543ad99b8ca53695cda1b的results与旧SI task-84d89822509e4c77b991e4aa1edad38f逐字段相同，C=12.893122250166755nF。旧多单位操作的原测试继续通过。

本次共8个新扩展成功任务、1个旧静电成功回归及1个首次电磁失败任务；全部保留，不用重放历史成功冒充本轮。

## 真实执行证据与复核

- [首轮电热/AC与首次电磁失败](work/extended-e2e-4238491d22ed40098aea13fbf23d47b1/summary.json)：各cli-*.json保留实际Windows参数列表、退出码/stdout/stderr。
- [修复后电磁粗网格成功](work/extended-e2e-ad6d57bc28394e708755f6dd4400ac7e/summary.json)。
- [分支和旧静电回归](work/extended-branches-a919ae68136747b7b307425a6fd34f66/summary.json)。
- [电磁2μm细网格](work/extended-e2e-fe6e955bdbab4bde8c645871bb9588e1/summary.json)。
- [8份真实结果按当前规范化器复核及40种破坏拒绝](work/extended-e2e-fe6e955bdbab4bde8c645871bb9588e1/saved-revalidation-final.json)：每份结果做错digest、错功率、伪造quality标志、错hash和缺场文件5种内存副本破坏，均INVALID_SCIENTIFIC_RESULT，未修改原任务。原字段/规范化输入从各自文件读取；SI核心可将整数表示为等值浮点，digest以实际canonical SI为准，原输入不回写。
- [受审科学函数AST/来源核对](work/extended-e2e-4238491d22ed40098aea13fbf23d47b1/source-audit.json)：13个electrical/thermal/transfer/export/AC/EM科学函数与源实验AST相同；几何函数只适配相对导入/宿主mesh cap，新增runner负责单次编排。源实验文件sha256保持原样。不将函数相同等同于重新实施全部科学验证。

原始公共结果在outputs/tasks/<task_id>/record.json；native/request.json、response.json、launch.json、stdout/stderr与method_environment记录Windows→现有Ubuntu-24.04/fenicsx-env、DOLFINx0.11.0的真实链。solution/含MSH、VTU/XDMF/HDF5、NPZ映射和可选PNG。原生VTU坐标/单元及逐场回读通过，Windows验证全部hash、结构、输入digest和指标/诊断一致；本轮未新增独立HDF5物理量积分对照，相关独立检查not_checked。已查看实际磁场图，图明确标注纵向放大，不用图片代替科学验证。

## 故障与修复记录

首次EM task-57b5a132265249c4bd57eec17e5b5555在求解及场导出后，NumPy布尔值进入标准库JSON响应导致序列化失败；原write_json先打开响应文件，失败留下空文件，使错误响应又遇独占创建冲突。该任务按failed保留，公共results为空；诊断场不冒充完成结果。修复为科学输出在进程边界转换成Python内建标量，write_json先完整序列化再独占写文件。新增坏JSON不留下空响应的测试。没有覆盖原失败任务，修复后新task单独复验。

公共回归首次隔离副本位于过深work目录，Windows WinError206/MAX_PATH导致1失败/39错误；源码未发现对应回归。保留原[失败日志](work/public-regression-43439d13bab9455187a0dbcd1332c3c9/stderr.log)，在模块q/短路径复制相同公共代码/测试并核对字节哈希后重跑，通过76项（75通过、1符号链接权限跳过）。[最终回归](q/14382a71/summary.json)、[源码哈希](q/14382a71/snapshot_files.json)证明公共源文件未改；没有修改系统长路径设置或公共测试绕过断言。

## 检查标准、通过项与未实施项

模块56项离线测试通过，原41项全部保留；涵盖新严格输入、重复损耗/不适定热边界、RMS/频率/端口、无依赖/科学失败/无效结果/未知执行状态、直接Adapter、独立预算与JSON故障。故障注入/mock与真实求解分开；记录见[tests-final.log](work/extended-e2e-ad6d57bc28394e708755f6dd4400ac7e/tests-final.log)。Bundle check valid=true（8模块）。

逐任务数值标准来自源实验已有代码，并由Windows依据测量值重新计算，不让LLM或单个PASS标志决定：

| 检查 | 继承标准及依据 |
| --- | --- |
| ET电功率/残差 | terminal_power_relative_error<1e-9；电/热solver及热weak residual<1e-8；electrothermal core.device与热核 |
| AC端口/体积功率 | complex_work与current_balance<1e-9；q_dot_identity<1e-12；relative_free_residual<1e-9；AC run.device |
| EM功率/残差 | complex_power<1e-7、active_power<1e-5、weak_Maxwell<1e-7；EM device_cases.execute |
| 源传递 | 精确单元映射及相对功率差<1e-12，理想电极模式Ni热源=0；原transfer/EM heat |
| 热平衡 | 非零功率ET/AC<1e-9、EM<1e-8；零功率绝对功率差<1e-10W；原实验检查 |

这些是受审数值回归标准，不是新发明的产品科学容差。网格语义来自内核分区/边界/连接与映射守卫；有限性与导出回读/原始指标一致性通过。完整未四舍五入的残差/原始通量保存在diagnostics，失败检查不能因execution succeeded而消失。

以下继续not_checked：原始梯度通量工程精度、单任务网格收敛和独立解析参考、端口/参考面工程接受性、实际材料和安装条件、模型适用性及独立实测器件对照。EM P1 H恢复DG0 E的局部强curl残差不能当已收敛强式；保留原诊断及限制。没有商业ESR/ESL/SRF、磁滞、三维封装或辐射签核。

本轮没有重新运行旧实验全部解析基准/频扫或新LLM对话；先前实验和静电Agent记录只是独立背景证据。新方法Skill的两字段frontmatter/链接可用标准库检查；skill-creator quick_validate因Windows缺PyYAML在校验前停止，记not_checked，见[日志](work/extended-e2e-ad6d57bc28394e708755f6dd4400ac7e/skill-validator.log)，未安装依赖。

## 运行与公共边界

新v2部署只供新操作：单线程、150000实际单元、240秒科学客户端、公共外层300秒。旧SI/多单位操作继续v1限制。Windows/WSL路径映射、每任务独占目录、日志/协议分离、未知进程状态不重提沿用原运行层；没有新增MCP、任务队列或环境。

无需修改公共接口即可调用。main后续可同步docs中的旧FEM范围/版本、扩展公共单位核心尚缺物性kind；queued配置冻结/远端进程回收仍是已有增强事项，不阻断本次接入。详见INTERFACE_PROPOSAL.md。

复核（不求解）：

```powershell
python -B -m unittest discover -s modules/fem/tests -v
python -B -m mlcc check
python -B -m modules.fem.harness.check_delivery
# 已保存证据；不修改公共task或重新计算
python -B -m modules.fem.harness.check_extended_saved --output <本模块新的JSON路径>
```

明确需要新真实任务时才用verify_extended --run-real；可指定单个operation，不重复全套实验。源/目标/验收文件保持可追溯，发布时排除work/q及本机配置。


2026-10-22 增量：fem 0.4.0新增三个器件多单位入口，旧SI能力与证据保持。真实等价任务、单位核心兼容性及未检查项见 [EXTENDED_UNITS_ACCEPTANCE.md](EXTENDED_UNITS_ACCEPTANCE.md)。
