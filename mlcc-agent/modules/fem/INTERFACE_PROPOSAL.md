## 2026-10-21 模块更名同步

用户要求目录由 fea 改为 fem；模块目录、module.json ID、Adapter 路由及模块内当前调用已同步。公共 docs/v1-status.json 和 docs/v1-scope.md 中旧 fea 条目由 main 同步为 fem，本模块未改写公共文件。历史任务不改写；v1 数据/部署 schema 标识和 MLCC_FEA_DEPLOYMENT 保持兼容。

# 给 main：Windows 宿主调用现有 WSL 科学环境的最小需求

## 当前实施结论（取代下方审阅阶段建议）

用户已明确：公共Runtime、Agent/Skill、Adapter、校验、task/result管理均在Windows；WSL只执行科学任务。**不能采用下方历史选择A，也不需要将公共Adapter直接绑到Linux Python。**

本轮沿用公共协议第3节“适配器可调用模块自己的外部科学程序”，在Windows Adapter中完成确定性转换与一次固定科学程序调用。宿主通过MLCC_FEA_DEPLOYMENT提供独立受信部署JSON，公共层仍启动Windows Python/adapter.py并管理唯一task。模块内deployment.py是该外部科学程序的窄驱动，不是队列/任务服务，不写公共record。

五个真实Windows CLI任务已完成run→worker→result/artifact，详见ACCEPTANCE。**当前最小闭环无阻塞性的公共接口变更，也不等待main实施通用WSL launcher。** 科学输入/结果外壳没有新增机器配置字段。

仍建议main后续增加受信部署上下文的摘要冻结/漂移检测：当前queued快照只含manifest/schema/Windows Python，宿主env指定的部署文件不在快照。模块已将实际部署SHA、argv、版本记录到任务产物，并在worker预检/执行检查实际环境；这不能证明与最初提交时环境完全一致。部署文件必须在提交到worker期间固定，模块不会把摘要塞入科学payload或另建公共审批/任务记录。

可选最小公共增强：宿主把命名的执行配置摘要纳入现有queued快照；worker变化则blocked。由main决定字段/兼容性，保留旧任务读取，不就地改原输入；用无科学后端的假执行配置测试漂移，真实小任务另行复核。原生进程组/取消协调是另一项后续宿主需求，不是本模块已实现功能。

未知状态的原生日志可能继续增长，公共artifact路径/大小检查会拒绝变化文件；要保留任务目录并人工核对进程，不能自动清理/重跑。超时不证明Linux求解停止。

---

以下仅保留审阅阶段历史背景；其中运行宿主选择与旧建议已被用户本轮Windows边界和上述实现结论取代，不能作为当前部署指令。

**历史提案：** 无需修改科学结果外壳，也无需为了二维静电扩充公共物理schema。

## 1. 具体场景与已确认限制

Windows公共CLI希望提交 `fea/electrostatics_2d`，科学环境实际位于已存在的 Ubuntu-24.04 / `/home/zhaoxiang/miniconda3/envs/fenicsx-env/bin/python`。Linux解释器不是Windows可直接执行文件，输入中也不应出现这些机器路径。

依据：`T/schemas/bindings.schema.json` 每模块只接受python；`T/mlcc/registry.py:23–30,80–112` 用宿主Path检查绝对路径/文件，用该解释器执行find_spec，并在宿主PATH找executable；`T/mlcc/transport.py:15–28` 固定 `[python,-u,adapter_absolute_path]`，cwd=Windows模块目录。请求artifact_dir也是Windows绝对路径。当前没有发行版、命令前缀或路径映射契约。

**最小静态复现**：Windows binding把python设Linux `/home/.../python` 不满足当前宿主路径/执行语义；把python设 `C:/Windows/System32/wsl.exe`，transport仍会把 `-u adapter.py` 当wsl参数，dependency probe还会发 `-I -c`，没有Linux Python执行上下文。并未尝试把这种伪binding运行成求解，也不建议.exe/.cmd包装器绕开公共语义。科学Adapter中自己硬编码wsl命令同样会把公共环境适配藏进科学模块。

## 2. 最小部署选择 A：整个公共 Runtime 在 WSL 中运行

本轮已用现有解释器在挂载的目标根执行：

```bash
cd /mnt/d/Zhaoxiang/code/mlcc-main
PYTHONDONTWRITEBYTECODE=1 /home/zhaoxiang/miniconda3/envs/fenicsx-env/bin/python -B -m mlcc check
PYTHONDONTWRITEBYTECODE=1 /home/zhaoxiang/miniconda3/envs/fenicsx-env/bin/python -B -m mlcc describe fea
```

实测check valid=true/module_count=8，fea保持not_integrated。原始输出在 `review_work/wsl_framework_check.json` / `wsl_fea_describe.json`。**这只验证CLI发现/结构可运行，不是正式科学Adapter已接入。**

若main接受全部公共提交/worker/读取在WSL运行，现有协议原则上可保持不变：入口/任务/产物在Linux路径视图内一致，公共层仍标准库，科学库仅由fea子进程导入。宿主命令固定到已确认环境，部署配置由main保管；Windows可阅读同一挂载目录文件。若同时有Windows原生模块，仍需main规划不同模块解释器位置，不宣称该选择解决所有模块部署。

建议优先此路线，先完成真实公共小任务验证；没有必要仅为首个模块立即新增通用执行平台。需要main确认这是受支持的部署方式，以及后续查询由哪侧解释任务路径；不要混用Windows/WSL写同一task或认为两种绝对路径等价。

## 3. 仅在必须保持 Windows 公共宿主时采用选择 B

建议增加**受信部署绑定中的类型化WSL启动配置**，而非科学输入增加命令字符串。下面仅示意待main设计的字段，当前schema不支持，不能现在保存为有效local-bindings：

```json
{
  "schema_version": "mlcc.bindings.v1",
  "modules": {
    "fea": {
      "python": "/home/zhaoxiang/miniconda3/envs/fenicsx-env/bin/python",
      "launcher": {"kind": "wsl", "distribution": "Ubuntu-24.04"}
    }
  }
}
```

字段命名、版本策略由main决定；实际机器值只存忽略的本地部署配置，模块描述保持可移植。最小行为要求：

1. host确定执行种类，验证发行版及Linux解释器；依赖find_spec/版本probe在同一WSL环境中运行。失败只使该模块不可用，不阻塞其他模块。
2. 传参用受信argv，无自由shell字符串；科学payload原样传递。host映射adapter入口、cwd和执行请求artifact_dir；环境路径不能进入input。预检null字段维持null。
3. Linux科学Adapter仍只读一个公共请求、写一个公共响应，不感知Windows/WSL启动细节。stdout不含banner，响应artifact路径始终为artifacts/...相对路径；回Windows后由现有路径/大小检查公开文件。
4. 发行版、执行种类、Linux Python、必要映射策略纳入queued快照；worker配置漂移拒绝执行。旧Windows python-only配置保持原行为。
5. 超时仍记interrupted并保留日志。必须明确WSL/Linux子进程可能遗留；未证实安全停止前不能自动再提交。若main实现进程树收尾需有独立测试，不把“杀wsl客户端”当Linux求解已停止。
6. 依赖检查、公共预检10秒预算、execute超时及日志/产物管理仍由公共层负责；不要求进度事件、取消API、远程队列或新task系统。

## 4. main 所需验证与兼容性

- 旧binding/Windows-only自检、旧task读取语义保持；新增字段是否提升bindings/schema版本由main确定。
- 假启动器单测：argv、cwd、UTF-8 stdin/stdout、null预检路径、含空格/中文路径映射、失败退出、超时、漂移和相对产物边界；不在默认公共测试启动FEniCS。
- 已授权的一个真实WSL小任务：preflight→queued→worker→result/artifact，保存原生求解及同路径文件的证据。这个测试必须等正式模块实现；当前not_checked。
- 当前公共记录以宿主绝对路径保存产物，选择A/B后都需明确记录由哪侧读取。旧任务不可就地批量改路径；跨宿主查询兼容问题由main定，不让科学Adapter重写公共record。

**请求 main 的决定**：优先确认选择A是否足够；只有产品要求Windows统一宿主才实施B。本模块继续完成不依赖公共改动的窄schema、科学函数、直接Adapter协议和小例验证。未收到决定前，不在模块内补另一套WSL任务桥。

## 2026-10-22 公共单位核心的子进程可导入需求

场景：FEM拟以新严格多单位入口复用main唯一单位核心，旧SI入口/内核不变。当前transport.invoke使用 `[module.python, -u, absolute_adapter_path]` 且cwd=module.root；脚本sys.path不自然含项目根，裸源码交付下`from mlcc.units ...`不能保证直接Adapter可导入。不得复制单位表、sys.path注入或引用来源项目路径解决。

最小需求：main在单位契约中明确公共核心的正规可导入机制（受信宿主bootstrap/可安装包等，由main实现）；公共CLI和独立Adapter使用相同环境契约。未到位前多单位入口不注册为可用。验证：清理非必需PYTHONPATH后，现有Windows解释器经公共transport调用新单位操作可规范化；直接Adapter按同一已文档化bootstrap接受相同请求；旧SI操作和历史查询保持可用。模块不改公共transport。


2026-10-22 单位导入需求已解决：main发布固定独立JSON线协议 `python -I <Bundle>/mlcc/units.py`，FEM已消费并完成真实公共入口等价任务，无需修改公共transport。原有部署快照/外部进程回收增强仍独立保留。


## 2026-10-22 用户确认的0.3.0电热/AC/EM接入（无阻断）

用户已在本thread明确要求依次纳入实验中稳定能力。fem 0.3.0沿原Adapter/Runtime/WSL文件协议新增electrothermal_2d、ac_eqs_2d、electromagnetic_2d，无公共实现改动；新部署v2在模块内仅对新操作授权150000单元/240秒，旧v1预算保持不变。真实任务及限制见EXTENDED_ACCEPTANCE.md。

请main同步公共docs/architecture、v1-scope、v1-status及acceptance中旧“fem仅静电、不扩展AC/多物理”的范围/版本描述，以用户本轮确认及当前module.json为准；本模块不擅改公共文档。

后续可在唯一公共units核心增补frequency/current/conductivity/thermal_conductivity/heat_transfer_coefficient等kind及对应白名单，由main定义名称/别名和测试。本模块当前严格固定SI字段（Hz、A、S/m、W/(m K)、W/(m² K)）可完成科学输入和审计，不建立本地换算表、不接受这些量的非SI容器；该增强非本次运行blocker。已有queued部署冻结、科学进程回收/取消的建议仍独立保留。


## 2026-10-22 多单位增量已接入（0.4.0，无新增公共阻断）

main已发布core1.0.0/catalog1.1.0，frequency/current/electrical_conductivity/thermal_conductivity/heat_transfer_coefficient等kind已由唯一公共核心支持。本模块新增三个 *_quantities 操作，原SI接口不变，见EXTENDED_UNITS_HANDOFF.md及EXTENDED_UNITS_ACCEPTANCE.md。不再需要为这些单位增补公共接口；上节“仅SI”的描述是0.3.0历史状态。公共范围文档同步、queued部署冻结及外部进程回收增强仍由main独立处理；不阻断本次受控有界调用。
