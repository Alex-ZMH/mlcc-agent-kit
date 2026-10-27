# MLCC 0.6.1 系统功能验收

2026-10-21。当前启用 **mlcc-agent 0.6.1**，契约为 `matterai.bundle.v2`。ABACUS PW 通用入口及四项正确性修复完成复审后，本次继续实现并验收 P2/B04 前置的本地晶体导入。H1 生产方法资格仍未完成。

## 已完成的入口与修复

ABACUS 3.10.1 的 PW SCF 和固定晶胞弛豫由显式 Study、Model、Method 驱动。材料、元素顺序、赝势映射、自旋、占据、电子参数和 k 网格来自输入与配置；可执行文件和站点资源属于配置。新材料的科学方法资格仍需独立取得。

四项修复已在 [0.5.0 独立复审](../workspace/reports/system-v050/independent-review-v001.json) 通过，0.6.1 全套测试和安装版合同验收继续覆盖：

1. 续接、依赖和交付要求 `result.task_id` 与任务一致。
2. 静态 DFT 不可重标为烧制温度、施加压力或 MD 结果，交付条件须与任务冻结记录一致。
3. 续接、依赖和交付共同检查原生输出证据，结果 JSON 不代替原生日志。
4. ABACUS 力逐项检查完整元素和编号标签，再映射到稳定 `atom_id`。

本次进一步要求非 fixture 的 Study 材料、相与模型一致；解析使用任务记录的模型路径，并检查模型 ID/版本。

## 本地模型导入

公开入口为 `mlcc import-model --request <json> --output <new-directory>` 和 Python `import_model_artifacts`。请求中的相对源路径相对于请求文件目录解析。

- 支持本地 CIF、POSCAR、extxyz；多数据块/帧必须显式选择索引。
- 原始源文件、展开后的 source 模型、working 模型、元数据、掺杂记录和逐原子来源映射分别保存。
- extxyz 的整数 `atom_id` 保留；其他来源按展开结构顺序分配。CIF 不声称展开原子与非对称位点一一对应。
- 仅支持完整占位、三维周期晶体。部分占位或混占位直接拒绝。
- 等价设置变换显式提供整数幺模矩阵、平移、目标晶格和依据，并检查体积与刚体旋转关系。不会暗中改相、扩胞或弛豫。
- 未实现的矢量磁矩/动量旋转直接报错。
- 无效 CIF 数据块的解析异常和返回空结构两种情况都拒绝，防止跳过坏块后选错结构。
- 输出目录必须是新目录。模型标记 `source_reference_unrelaxed`、`relaxation_status=not_run`、`production_qualified=false`。

新功能通过 Python/CLI 暴露，现有七项 MCP 生命周期工具不变。

## CaZrO₃ 实际验收

[导入请求](../workspace/configs/model-import/cazro3-pnma-v001.json) 使用 COD 1532747 本地源和已审计的 Pcmn→Pnma 等价设置，生成 [正式模型](../workspace/models/cazro3-pnma-pristine/v001/model.json)。Ca₄Zr₄O₁₂ 共 20 原子；晶格为 `diag(5.58305, 5.75904, 8.00703)` Å，体积 257.45010182415206 Å³，与源模型一致。

源结构约 173 K，仅作为结构参考。[Study v003](../workspace/configs/cases/cazro3-firing-v003.json) 绑定该模型，保留 v002 的无掺杂、400–580 °C、温度点与顺序、1 atm 及未指定热历史。未生成高温平衡结构或完成生产弛豫，旧 Study 与任务保留。

[输入检查方法](../workspace/configs/cazro3-abacus-input-check-v001.json) 仅在本地生成 INPUT/STRU/KPT 和原子映射：100 Ry、2×2×2、`scf_thr=1e-4`、固定占据、88 能带。`scf_thr` 是 ABACUS 原生密度误差收敛参数，不是 eV 能量阈值。STRU 回读的坐标、元素和 ID 通过。

Ca UPF 含 full-relativistic/`has_so=true`，与当前 nspin=1 输入的兼容性尚未验证，见 [资源清单](../workspace/reports/p2/cazro3-upf-inventory-v001.json)。这些输入没有创建 task.json、传输或提交 Slurm，不属于生产方法。

BaTiO₃ 保留 800–1350 °C，其相、组成选择、源结构和机械边界仍未确认，本次未替它选择晶相。

## 验收与版本

- [最终验收](../workspace/reports/system-v061/acceptance.json)：105 项测试通过；155 条告警为 154 条 ASE/NumPy 弃用提示和 1 条故意不完整占位 CIF 测试的预期告警。
- [安装版模型与输入](../workspace/reports/system-v061/model-import/acceptance.json)：43 项检查通过。0.6.1 CLI 重新导入的产物与正式模型相同。
- [安装版合同](../workspace/reports/system-v061/installed/acceptance.json)：两案例条件、历史 Ni jobs32/33/34 的续接/交付通过，历史任务文本未改写。
- [原版 MatterAI 宿主](../workspace/reports/system-v061/matterai-headless-session.json)：registry、Agent/四 Skill、真实 provider→安装版 MCP 调用通过。
- [MCP 握手](../workspace/reports/system-v061/mcp-installed.json)：版本 0.6.1、七工具、列表调用成功。

初装 0.6.0 后复审发现 CIF 返回空结构时仍可能跳块，补充修复和回归。原版安装器禁止覆盖同版本，因此以 0.6.1 交付，0.6.0 保留并标为未通过最终发布验收。未修改上游、提交 Git 或建立分支。

复验命令（项目根目录）：

```powershell
workspace/.venv/Scripts/python.exe -m pytest mlcc-agent/tests -q -p no:cacheprovider
workspace/.venv/Scripts/python.exe scripts/system/verify_contracts.py --bundle-root workspace/.zeus/bundles/mlcc-agent/0.6.1 --report-dir workspace/reports/system-v061/installed
workspace/.venv/Scripts/python.exe scripts/system/verify_model_import.py --bundle-root workspace/.zeus/bundles/mlcc-agent/0.6.1 --report-dir workspace/reports/system-v061/model-import
```

## 科学资格与下一步

本轮较早的 Ni jobs38/39 与参考 job37 构成同方法三点应变链路，两项新作业分别用时 8/9 秒。执行和解析通过；应力标定最小差异 6.3555 GPa 大于预设 1 GPa，科学标定未通过。未放宽阈值、混入旧 9³ 结果或自动升精度重算，见 [应变验收](h1-strain-capability-v004.md)。

本次完成 P2/B04 的导入前置功能，B04 双材料电子/弹性/介电/声子基线尚未完成。下一最小功能是通用方法输入资格检查，将 UPF 元素、价电子、占据/能带、自旋与相对论兼容依据绑定到 Method；接着按 B04 开发公共电子/弹性任务及明确的数值能力表。科学计算仍须满足各自输入与资格条件，不铺开案例温度矩阵。

H1、生产 ABACUS 切换、四性质执行器、缺陷热力学、势资格和 MD 不因输入生成而通过。无产品规格时 `design_assessment=not_assessed`。
