"""Record the actual H0 engineering gates after the reviewed v003 calculations."""
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKSPACE = ROOT / "workspace"
SCOPE_CORRECTION = {
    "date": "2026-10-21",
    "evidence": "docs/matterai-runtime-scope.md",
    "change": "Desktop entry is not required; non-desktop host MCP integration was unverified at this correction.",
    "resolution": "Real original-runtime provider MCP call passed in v003; same session JSONL replay.",
}


def read(relative):
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


host_evidence = "workspace/reports/h0/matterai-headless-provider-session-v021-list-tasks-v003.json"
host = read(host_evidence)
assert host["status"] == "passed" and host["provider_session"] is True
assert host["runtime"]["childExitCode"] == 0
provider_records = [json.loads(line) for line in host["runtime"]["invocation"]["stdoutJsonl"]]
completed_calls = [event["item"] for event in provider_records
                   if event["type"] == "item.completed" and event.get("item", {}).get("type") == "mcp_tool_call"]
assert len(completed_calls) == 1
assert completed_calls[0]["server"] == "mlcc" and completed_calls[0]["tool"] == "mlcc_list_tasks"
assert completed_calls[0]["status"] == "completed" and completed_calls[0]["error"] is None
assert completed_calls[0]["result"]["content"]
comparison = read("workspace/reports/h0/vasp-comparison-v003.json")
assert comparison["passed"] is True
regression = read("workspace/reports/h0/real-vasp-regression-v005.json")
assert regression["all_passed"] is True
lineage = read("workspace/reports/h0/relax-lineage-v005.json")
assert lineage["relaxation"]["ionic_converged"] is True
legacy = read("workspace/reports/h0/vasp-comparison.json")
assert legacy["all_predeclared_checks_passed"] is False
activation = read("workspace/.zeus/bundles.json")
assert activation["bundles"] == [{"name": "mlcc-agent", "version": "0.2.1", "enabled": True}]
mcp = read("workspace/reports/h0/mcp-installed-v021-query-job29.json")
assert mcp["initialize"]["result"]["serverInfo"]["version"] == "0.2.1"
assert len(mcp["tools"]["result"]["tools"]) == 7
assert mcp["call"]["result"]["isError"] is False
assert mcp["call"]["result"]["structuredContent"]["scheduler_job_id"] == "29"

task_records = []
for path in sorted((WORKSPACE / "tasks").glob("h0-*/task.json")):
    task = json.loads(path.read_text(encoding="utf-8"))
    if task["scheduler_job_id"] is None:
        continue
    record = {
        "task_id": task["task_id"],
        "job_id": task["scheduler_job_id"],
        "state": task["scheduler_state"],
        "exit_code": task["exit_code"],
        "task_record": path.relative_to(ROOT).as_posix(),
        "resources_requested": task["resource_request"],
        "scientific_status": task["scientific_status"],
    }
    if "scheduler_fields" in task:
        record["native_scheduler_fields"] = task["scheduler_fields"]
    if "result_file" in task:
        record["result_file"] = task["result_file"]
    task_records.append(record)
task_records.sort(key=lambda item: int(item["job_id"]))
cutoff = comparison["comparisons"]["cutoff_500_vs_600"]["differences"]
stress = comparison["comparisons"]["stress_sign_finite_strain_500"]
relax = comparison["comparisons"]["relax_to_post_relax_scf_500"]
gpu_seconds = 0
for record in task_records:
    if record["task_id"].startswith("h0-ni-"):
        hours, minutes, seconds = map(int, record["native_scheduler_fields"]["RunTime"].split(":"))
        gpu_seconds += (3600 * hours + 60 * minutes + seconds) * record["resources_requested"]["ntasks"]

acceptance = {
    "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
    "command": ["workspace/.venv/Scripts/python.exe", "scripts/h0/record_acceptance.py"],
    "scope": "H0_Ni_engineering_only",
    "bundle_version": "0.2.1",
    "H0_complete": True,
    "scope_correction": SCOPE_CORRECTION,
    "gates": {
        "G0_bundle_install_and_discovery": "passed",
        "G1_runner_MPI": "passed",
        "P1_MatterAI_host_MCP_integration": "passed_real_provider_MCP_call",
        "G2_engineering_model": "passed",
        "G2_production_model": "pending_verified_source_and_production_model",
        "G3_VASP_engineering": "passed",
    },
    "host_integration_evidence": host_evidence,
    "numerical_evidence": "workspace/reports/h0/vasp-comparison-v003.json",
    "preserved_failed_numerical_evidence": "workspace/reports/h0/vasp-comparison.json",
    "parallel_test_scope": "same geometry at 400 eV, jobs20/21; not a 500 eV parallel benchmark",
    "accepted_engineering_cutoff_eV": 500,
    "kmesh_rule": "ceil(30/a), ceil(30/b), ceil(30/c); lengths in Angstrom",
    "kmesh_independent_convergence": "not_performed_user_rule",
    "production_qualification": False,
    "production_engine_switch": "not_performed",
    "user_selection": read("workspace/configs/study.json"),
    "tasks": task_records,
    "VASP_requested_GPU_hours_from_native_runtime": gpu_seconds / 3600,
}
(WORKSPACE / "reports/h0/acceptance.json").write_text(
    json.dumps(acceptance, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
)

harness_dir = WORKSPACE / "reports/harness"
harness_dir.mkdir(exist_ok=True)
case_results = []
for path in sorted((ROOT / "mlcc-agent/harness/cases").glob("*.json")):
    definition = json.loads(path.read_text(encoding="utf-8"))
    case_results.append({
        "case_id": definition["id"],
        "definition": path.relative_to(ROOT).as_posix(),
        "execution_status": (
            "passed" if definition["id"] in {"project-discovery", "vasp-roundtrip"}
            else "not_run"
        ),
    })
(harness_dir / "h0-results.json").write_text(json.dumps({
    "execution_method": "project assertions and real integration; no platform case executor claimed",
    "template_execution_status": "Bundle not_run describes the unexecuted installation template",
    "evidence": ["workspace/reports/h0/acceptance.json",
                 "workspace/reports/h0-p0/registry-v021-output.txt",
                 "workspace/reports/h0/vasp-comparison-v003.json"],
    "cases": case_results,
}, indent=2) + "\n", encoding="utf-8")

plan_path = ROOT / "plans/stages.json"
plan = json.loads(plan_path.read_text(encoding="utf-8"))
plan["status"] = "H0_engineering_completed"
plan["updated_date"] = "2026-10-21"
plan["scope_correction"] = SCOPE_CORRECTION
plan["milestones"] = {"H0": acceptance["gates"], "H0_complete": True}
by_id = {stage["id"]: stage for stage in plan["stages"]}
by_id["P0"].update(state="completed", evidence=[
    "docs/h0-p0-bundle.md", "workspace/reports/h0-p0/installer-v021-output.txt",
    "workspace/reports/h0-p0/registry-v021-output.txt", "workspace/reports/h0/unit-tests-v021.txt"])
by_id["P1"].update(state="completed_engineering_site_integration", evidence=[
    "docs/h0-mpi.md", "docs/h0-execution-ledger.md",
    "workspace/reports/h0/mcp-installed-v021-query-job29.json", "docs/matterai-runtime-scope.md", host_evidence],
    remaining=[], limitations=["sacct_not_configured_recent_scontrol_terminal_records_saved"])
by_id["P2"].update(state="engineering_fixture_passed_production_conditions_pending", evidence=[
    "workspace/models/ni-fcc-engineering/v001/model.json",
    "workspace/configs/study.json", "docs/cazro3-source-candidate.md"],
    remaining=["verified_source_structure", "production_model_and_requested_future_distributions"])
by_id["P3"].update(state="completed_engineering_bootstrap", evidence=[
    "workspace/reports/h0/vasp-comparison-v003.json",
    "workspace/reports/h0/real-vasp-regression-v005.json",
    "workspace/reports/h0/relax-lineage-v005.json",
    "docs/h0-acceptance.md"],
    qualification_scope="Ni fixed-cell fixture; 500eV engineering tolerances; no production labels",
    untested=["vasp_gam", "vasp_ncl", "cell_relax", "independent_kpoint_convergence"])
by_id["P4"]["preflight_evidence"] = ["docs/h1-abacus-preflight.md", "workspace/reports/h1/"]
plan_path.write_text(json.dumps(plan, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

rows = []
for record in task_records:
    rows.append(f"| {record['job_id']} | {record['task_id']} | {record['state']} | "
                f"{record['exit_code']} | [{record['task_id']}](../{record['task_record']}) |")
report_text = f"""# H0 工程验收与交接

日期：2026-10-20。主入口为 [机器可读验收](../workspace/reports/h0/acceptance.json)。

## 已完成

- 原版 MatterAI 安装器/registry 真实装载 `mlcc-agent@0.2.1`：1 Agent、4 Skill、7 个真实 stdio MCP 工具。
  [P0 证据](h0-p0-bundle.md)。已安装 MCP→Slurm 查询 job 29 成功；本地 `mlcc.exe` CLI 已实际安装并查询 job 30。
- 项目 Python 3.12.10；13 个局部测试通过，保留 11 条 ASE/NumPy 上游弃用告警。
  [单测](../workspace/reports/h0/unit-tests-v021.txt)、
  [包安装](../workspace/reports/h0/local-package-install-v021.txt)。
- 复用 Slurm，NVHPC `mpirun` 在 sbatch allocation 内通过单/四 rank 的 CPU/CUDA buffer reduction。
  runner 正常、显式失败、取消、查询和 scp 回传均实测。[MPI](h0-mpi.md)、[完整台账](h0-execution-ledger.md)。
- Ni 4 原子工程模型、稳定 atom ID、原始/派生结构、VASP 输入与真实解析成立。
  400 eV 单/四卡一致性通过；500 eV 固定晶胞弛豫→指定 CONTCAR→SCF→回传闭环通过。
- k 网格按用户规则各向取 `ceil(30/length)`，长度 Å；当前 Ni 为 9×9×9。
  未做独立 k 网格收敛扫描，不将此规则宣称为生产精度证明。

## 数值验收

| 检查 | 实测 | 预定阈值 | 结果 |
|---|---:|---:|---|
| 400 eV 单/四卡最大力分量差 | 1e-8 eV/Å | 1e-4 eV/Å | 通过 |
| 500→600 eV 能量差 | {cutoff['energy_eV_per_atom']:.8g} eV/atom | 0.01 eV/atom | 通过 |
| 500→600 eV 最大力分量差 | {cutoff['force_component_eV_per_A']:.8g} eV/Å | 0.03 eV/Å | 通过 |
| 500→600 eV 最大应力分量差 | {cutoff['stress_component_GPa']:.8g} GPa | 0.5 GPa | 通过 |
| 500 eV 应变能导数与应力迹差 | {stress['absolute_difference_GPa']:.8g} GPa | 1.0 GPa | 通过 |
| 500 eV 弛豫最大力 | {relax['relax']['max_force_eV_per_A']:.8g} eV/Å | 0.02 eV/Å | 通过 |
| 500 eV 后续 SCF 最大力 | {relax['post_relax_scf']['max_force_eV_per_A']:.8g} eV/Å | 0.02 eV/Å | 通过 |

证据：[v003 对照](../workspace/reports/h0/vasp-comparison-v003.json)、
[真实输出解析回归](../workspace/reports/h0/real-vasp-regression-v005.json)、
[500 eV 结构谱系](../workspace/reports/h0/relax-lineage-v005.json)。
这里验证的是 Ni 工程阈值；不构成 CaZrO3 性能、生产 DFT 方法或势标签资格。
500 eV 改变的是 cutoff；单/四卡数值等价实验发生在 400 eV，范围单独保留。
派生 Ni 结构在 symprec={lineage['symmetry']['symprec_angstrom']} Å 下检测为
{lineage['symmetry']['space_group_symbol']}；这是工程力收敛公差下的残余畸变记录，
不解释为发现了 Ni 新相，也没有把坐标强制对称化。

400 eV 的应力 cutoff 检查和应变导数检查**失败并保留**：
[原验收](../workspace/reports/h0/vasp-comparison.json)、[诊断](h0-stress-diagnosis.md)。
随后人工审查并预先记录 v003 方法/五任务预算，未降低阈值。
Job 17 QD ABI、18 CRLF、19 部分传输误提交失败均保留原日志。
原始 VASP stderr 的浮点告警未隐藏；输出有限性、OUTCAR/XML 一致性和物理对照均另行核对。

## 原生作业与资源

| Job | Task | 原生状态 | ExitCode | 完整事件/命令 |
|---:|---|---|---|---|
{chr(10).join(rows)}

数值任务均经 Slurm、最大并发 1；VASP 用原生 RunTime 与请求卡数统计约
{gpu_seconds / 3600:.3f} GPU·h（含失败尝试，不是 GPU 利用率积分）。
四卡进程的不同物理 GPU UUID 实证在
[运行快照](../workspace/reports/h0/vasp-relax-v004-runtime.txt)。
CPU 1/4 rank 请求在本机分别分配 2/8 个 SMT 逻辑线程；VASP RAM 请求 8192 MiB。
本机没有 sacct 持久记账，原生 scontrol 终态已落盘。
收尾时本用户队列和 GPU 计算进程均为空，见
[资源释放快照](../workspace/reports/h0/final-resource-release.txt)。

可重放的当前入口为：

```powershell
workspace/.venv/Scripts/python.exe scripts/h0/vasp_fixture.py <action> <case> --task-version v005 --method workspace/configs/h0-vasp-method-v003.json
workspace/.venv/Scripts/python.exe scripts/h0/compare_vasp_v003.py --scope all
workspace/.venv/Scripts/mlcc.exe status --site workspace/configs/site.v100.json --task <task.json>
```

已有 task 不重新提交；上例说明入口参数，实际 sbatch/scp 命令与原始输出在各 task.json/events。

## 未完成与下一最小任务

**H0 工程闭环已完成（2026-10-21）**：原版 MatterAI registry/Agent profile → 原版 CodexCliRuntime → 已安装 MLCC MCP 的真实模型调用通过。
实际 provider session 调用了且仅调用了 `mlcc_list_tasks`，返回 23 条任务，CLI 退出 0。
[真实宿主证据](../workspace/reports/h0/matterai-headless-provider-session-v021-list-tasks-v003.json) 保留完整 JSONL。
原版 runtime 将这版 MCP 事件交付为 `provider.raw`；验收使用真实 `item.completed/mcp_tool_call` 及返回内容，不依赖助手自述。
无桌面要求，不写 truststore；仅使用已授权项目工具，`--ignore-user-config` 隔离全局配置。
首个配置错误和原规范事件断言失败记录保留；v003 重新解析同一次成功会话，没有重跑模型来补证据。
[入口核查](matterai-runtime-scope.md) 中 2026-10-21 的待办状态由本次实测更新。
Slurm direct srun/PMIx 插件仍缺系统库；本项目明确使用已实测的 allocation 内 NVHPC mpirun。
曾短暂 PENDING/InvalidAccount 后由 Backfill 启动的现象仍保留，没有重装或修系统服务。

生产请求已确认为 **无掺杂 CaZrO3／正交 Pnma，按指定温度研究**。
生产温度为 330 K、400 K，外压 1 atm（101325 Pa）；结构来源仍待核验。
保留层与临时粘结剂两条高分子分支均保留、材料/工艺未选。

下一最小数值任务是 **P4/H1 的同几何 Ni ABACUS 单卡 SCF**：
先按实测 v3.10.1 及独立 MPICH/CUDA 环境实现输入/解析薄适配器，通过 Slurm 验证。
[H1 只读预检](h1-abacus-preflight.md) 已有本机版本与 Ni UPF/ORB 头部证据；
ABACUS Ni 候选 18 价电子与 VASP Ni 10 价电子不同，不能比较裸总能。
ORB 配对尚未确认，候选文件未被自动认定为合格基组。
P4 迁移与生产引擎切换、P5–P12 的性质/势/MD 均未完成，没有生成生产标注。

两个参考树保持只读；本轮没有 Git 提交/建分支、Slurm 重装、服务器重启或驱动升级。
"""
(ROOT / "docs/h0-acceptance.md").write_text(report_text, encoding="utf-8")
print(json.dumps({"engineering_G3": "passed", "H0_complete": True,
                  "task_count": len(task_records), "case_results": str(harness_dir / "h0-results.json")}))
