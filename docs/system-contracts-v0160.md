# 0.16.0交付：晶界公共模型、Study和任务来源

0.16已安装、启用并冻结，0.15回退，源码进入0.17候选。v100安装job191为COMPLETED/0:0；原版MatterAI宿主实际读取0.16并调用mlcc_list_tasks通过，registry、MCP与本地Python绑定一致。[发布证据](../workspace/reports/system-v0160/acceptance.json)。

本次范围是显式同父、中性、pristine双晶的工程建模和输入来源传递。create-grain-boundary薄调用174验收的几何模块，bind-grain-boundary-study把真实模型绑定到新Study；186通过父身份检查，189通过迁移后任务内静态来源消费。保留两个晶粒、40个原子、父映像和原Study来源，不自动CSL匹配、删原子、应变匹配或弛豫，不代选生产相/掺杂。

190在v100复用174/186创建ABACUS和LAMMPS输入，静态grain-boundary.json、atom-lineage.json及binding随任务传递；两个创建器和结果端保留Study、模型和原子/晶粒身份。原4原子Ni的56 bands不能用于40原子输入，验收副本按主代理明确决定使用560，原方法不变。所有任务仍未提交引擎；解析字段转发只有显式software stub证据，不代表原生晶界解析或科学资格。191只从安装副本消费已有来源，不重造几何或重复数值任务。

P5仍复用冻结0.15实现：SCF177/178原生电子收敛，NSCF180–185全部COMPLETED/0:0且UNLIMITED；187一次解析，188公共收集成功。原始P、极化量子和来源可交付，缺跨位移分支依据时status=unresolved_missing_branch，响应/Born列/介电保持null，科学/数值/生产资格false。168 GPU/CPU数值差异原因未确定；不调阈值、不重算。

本地绑定首次缺setuptools失败，显式指定既有workspace/build-tools/setuptools-80.9.0后安装通过；未重装依赖。第一次宿主仍读旧0.15注册项，证据单独留档，未计入0.16验收；显式更新registry/MCP后真实0.16宿主通过。v100复用0.15私有bridge依赖和0.9共享Python，未改共享环境。

下一工作只针对实际功能缺口。现有berry-response已能保存和消费188结果，因此暂不增加重复包装接口；转审查带电缺陷静电势/VBM原生来源。完整Born/介电、晶界原生计算、缺陷对齐/FNV/尺寸与化学势、完整弹性/声子和势生产资格仍未完成。MACE/CZO约2.708GPa偏差继续后置，未资格参数不当生产输入。没有用户产品指标，design_assessment=not_assessed。

旧0.10删除审批阻塞保留，0.11–0.14旧软件副本尚未退役；没有删除科学输入、原生结果或仍在使用的环境。