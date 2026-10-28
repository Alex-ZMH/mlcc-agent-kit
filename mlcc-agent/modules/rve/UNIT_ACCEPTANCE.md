# 单位接入验收

最终0.1.1通过唯一公共core1.0.0，实际catalog1.1.0；不精确锁catalog版本。轻量19项passed，四组真实2D/3D多单位对照canonical/tensor/全部原生场差0，详见[完整验收](ACCEPTANCE.md)和work/real-20261023T045702Z/native-comparison.json。

电学10um/0.01mm长度等价覆盖2D和3D；导热4、1 W/(m K)与0.04、0.01 W/(cm K)等价覆盖2D和3D。μm/µm/um/nm/mm/m别名与张量分量shared-core/replay由轻量测试覆盖，负非对角项最终三维真实任务task-9f711feb94b8404db2d3cc8d90514198已求解。count/seed经同一核心固定语义处理。raw Runtime快照不改；canonical区域字典转换有material_rows审计，WSL不读raw unit。

所有量值、来源、映射、版本及坐标说明见[UNIT_DESIGN.md](UNIT_DESIGN.md)。温度梯度和角度单位未开放，无私有换算表。实际材料标定、每任务收敛not_checked；在线模型not_run。
