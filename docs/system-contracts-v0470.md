# 0.47 候选：原生响应结果消费

当前0.46启用冻结，0.45回退。本文记录0.47候选范围，不代表已发布。科学结果保存在workspace，Bundle只包含通用功能。

## 本次功能

- 公共声子力收集支持已声明的PW或LCAO方法。LCAO核对NUMERICAL_ORBITAL、正式NAO文件/ID/头快照及逐点方法一致性。
- 声子计划可显式指定真实P4父结构SCF为reference；位移任务继续使用完整P7计划、父子Model和Study来源。不会给原P4任务伪造位移身份。
- Study的fixture可按case_role推导；Task/Model的显式布尔标记及来源一致性保持。Study若显式提供fixture，仍必须一致。
- P5原生响应消费支持P7嵌套父信息及外置Study，保留真实atom ID、位移、单位、原生收敛与方法绑定。
- 待验收：带有显式source_model_path的PYATB任务内模型副本消费。规范父模型和副本分别记录，实际结构及原子身份必须一致，不能仅忽略路径差别。
- 待验收：已有Γ处理结果导入及同Study交付。复用公共原生来源读取，不重算谱/投影/力常数。报告格式转换留在报告适配，公共功能不硬编码材料或原子数量。

## 真实来源与已通过检查

BTO对象为用户指定的未掺杂、中性、化学计量P4mm五原子原胞，[001]极轴。GPU SCF464及469–486全部原生收敛；方法scf_thr=1e-11、Slurm time=0。PYATB499–517使用各自原生H/S/r，均COMPLETED/0:0。本候选消费这些已保存结果，不重复DFT/PYATB。

521的14项新检查通过，唯一实际19点collection完成原生方法/NAO/收敛/几何/力与来源核对；521因Study.fixture合同缺陷及一项测试夹具缺字段而FAILED/1:0。522修复两项定向检查和保存19Task元数据检查，COMPLETED/0:0，未重新解析19点。原失败证据和原collection均保留。见workspace/reports/phonon-lcao-reference-v001/acceptance.json。

Γ计算518和Born聚合520均COMPLETED/0:0；519映射索引失败保留。518保存raw/对称/投影矩阵和全部光学模；520保存实际8空间操作、9独立方向与27整数族，主线明确审定局部相对整数为0。最终公共产品/Study交付仍待本候选新增路径验收。

## 科学状态与软件状态

参考模型未弛豫，最大原生参考力0.1960780459 eV/Å超过所声明的0.01 eV/Å条件。原collection的ready_for_harmonic=false不能改写。518是用户授权的指定几何局部响应消费，两个约-96.8 cm^-1光学负模保留；离子静态响应及总静态介电仍须为unresolved/null，电子贡献可独立保存。

Born分支审定只覆盖已有参考/±0.01 Å三点，不证明未采样路径或步长、k点、基组收敛。1e-11只用于SCF，Born精度/中性及Γ标准分别见docs/born-gamma-provisional-standard-v001.md。模型差异与未完成资格不阻止正确的软件路径验收，也不因软件发布而改为合格。

不新增DFT、MD、训练、温度矩阵、自动重试或参数调整；不改旧任务、上游参考树或科学源。后续安装验收只检查新安装入口、绑定和保存产物，不重复上述计算或已通过检查。


## job523及调度恢复

523新增六项检查全部通过；真实消费在公共CLI前因内部Path/str类型不匹配退出，已修复一行，未重复测试。Slurm journal记录job523 WEXITSTATUS=1，随后slurmctld于2026-10-25 12:35:08发生SIGSEGV，终态scontrol暂不可取。服务恢复需要管理员认证；修复候选和仅消费续接脚本已准备，尚未提交。此候选仍未完成真实同Study验收或安装，0.46保持启用。详见workspace/reports/bto-native-response-v047-v001/status-523.json。
