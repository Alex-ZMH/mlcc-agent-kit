# 单位增量交main

phase_field 0.2.0，新增可选steady_si/evolve_si；原steady/evolve、dimensionless模型、科学kernel和历史读取不变。只写本模块，没有改公共代码/Bundle/Agent/Runtime/执行权或其他模块。公共唯一单位核心作为Windows stdlib子进程工具使用，无私有单位表、fem运行时依赖或WSL公共包安装。

四尺度l/P0/T/f0及来源必须显式给出，推导phi/E/epsilon/g、Landau和mobility系数与2D J/m、3D J。模型仍固定alpha*=-1,beta*=1,gamma*=0,L*=1，不支持任意材料，不默认BaTiO3尺度。旧epsilon*、绝对epsilon[F/m]、epsilon_r严格区分，epsilon_r新入口不接受。

七个小型真实公共任务完成：2D/3D各nd对照＋两种等价SI表示，另steady_si。每维度原生NPZ/全部历史与旧对照差0、SHA相同；物理数组/历史按尺度逐项核查，查询不重算。审计文件最终拆分用原生响应独立重放验收，不冒充额外求解。35项模块测试、76项公共副本测试（1跳过）、四操作离线宿主schema消费通过；未新增在线LLM调用。

原迁移ACCEPTANCE/evidence/SOURCES及main真实Agent验收不重写。此次增量看UNITS_ACCEPTANCE、units-evidence.json和UNITS_SOURCES.json。运行时公共核心SHA保留在各科学副本与索引；main后续正常输入兼容性用离线验证，未因超长pointer错误边界修复重算物理。

材料标定、实物对照、稳定性、每任务收敛、远端终止确认仍not_checked。数值QC仍nd，不复制nd绝对容差到SI。无公共接口阻断，main按自己集成规则维护公共验收/范围/Bundle即可；其他科学模块不自动启用此映射或强制其内核SI。
