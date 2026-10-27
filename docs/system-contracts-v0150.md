# 0.15.0 工程交付：陶瓷训练/MD与P5响应输入

0.15.0已安装、启用并冻结。安装验收175、原版MatterAI真实宿主会话和七MCP工具声明通过；registry、MCP入口、Python均绑定0.15。0.14回退，源码0.16。见[发布证据](../workspace/reports/system-v0150/acceptance.json)。MACE/CZO约2.708GPa应力偏差后置，系统传递与科学资格分栏。

## 陶瓷工程链与公共交付

host20/vacancy19原生ABACUS来源50/121，经141分system转换、146联合训练/冻结、150/151同一势的Python/LAMMPS E/F/virial对照、154/155各5步GPU MD，最终159通过。保留Study、原子/元素/type_map、删8谱系、净电荷、源DFT、训练任务/job及模型卡。两帧均参与训练，没有独立验证；短MD没有平衡或生产窗口。

公共六命令166通过。安装171真实执行`ceramic-training-bind`与`deliver-md`：whole_record交付两个未资格观测；缺production_window则md_thermo为null且observables为空，不隐式回退。来源/训练身份不匹配进入review_original_error。171最后汇总因Path/string错误FAILED/1:0；175只读复用既有输出完成验收，没有重新计算交付。

完整`mlcc-deepmd-bridge==0.1.0`独立包已安装。本地为workspace Python依赖；v100为0.15私有dependencies，175核对真实导入路径，没有导入开发树。169缺setuptools失败留档，170显式绑定隔离构建工具后成功。

## P5当前范围

位移生产者创建显式±位移子模型/Study/SCF；原生SCF收敛后才可生成对应NSCF。收集器消费同一manifest，验证固定胞、原子ID、方法、来源、方向和单位；显式分支且三方向齐全时最多形成一个原子的一个Born列，缺方向/分支不补零。164公共输入通过，162算法检查通过；161–163失败保留。[输入账本](../workspace/reports/berry-response-v001/execution-ledger.md)。

GPU隔离构建160和原生167完成。167使用原50电荷、原物理参数、1MPI/1V100/8GiB/time=0，4分41秒、COMPLETED/0:0、TimeLimit=UNLIMITED。168原生解析、执行身份、方法/单位与来源通过；对只读CPU58的极化差1.86e-5 C/m²超过原门1e-6，FAILED/1:0保留，数值一致性未通过。不调阈值、不重算58/167，不授予科学资格。

真实位移输入173已生成；报告脚本误将task.json文件路径当目录，176复用输入补runner脚本完成，没有重造模型或重复producer。两SCF177/178已COMPLETED/0:0并经179确认原生电子收敛；六NSCF180–185均COMPLETED/0:0、TimeLimit=UNLIMITED，187一次解析通过。188复用原生结果完成公共收集，保留两位移×三方向的P、极化量子和来源。当前没有可审计的跨位移分支依据，显式分支整数保持null；结果为unresolved_missing_branch，有限差分、Born列及介电张量均null，科学/数值/生产资格为false。该缺口不阻塞独立系统接线，不追加DFT。见[真实结果](../workspace/reports/berry-response-native-v001/berry-response-results.gpu-v002.json)与[分支审查](../workspace/reports/berry-response-native-v001/branch-review-20261022.md)。168数值差异原因仍未确定。

## 边界与下一项

- 原版安装器对既存Bundle报already installed，未修改启用项；首次旧registry宿主会话单独留档。显式更新registry/MCP后，0.15实际会话通过。
- 完整Born、电子/离子介电、真实多状态极化响应及科学数值资格仍未完成；不能以不支持的ABACUS3.10.1体相DFPT/有限场参数填空。
- 晶界几何由现有实施窗口独立开发，主窗口后续接Study/公共任务；未验收模块排除在0.15快照外。
- 缺陷势对齐/介电/FNV、尺寸与化学势、完整弹性/声子原生任务集仍有缺口。没有产品指标，design_assessment=not_assessed。

软件工程通过不授予材料、势或温区的科学资格；不为数值过线重复训练或加密DFT。
