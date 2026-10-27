# P6 逐原子共线磁矩输入切片设计 v001

状态：**规划文档，未实现**。本切片只处理 ABACUS 3.10.1 的逐原子共线初始磁矩输入、输入身份绑定和原生输入回显。它不判定磁序、磁性基态、居里温度、SOC、MAE、交换参数或生产资格。

## 1. ABACUS v3.10.1 的输入语义和版本溯源

v100 上实际安装并运行的版本身份以[安装版本记录](abacus-3101-p5-capability-audit.md)为准：版本为 `v3.10.1`，package source revision 为
`4d3cbab83d661a25770eee61ce9275be0bfebe08`。这条 revision 是当前运行时的安装证据；文档不把其他源码 revision 当作已安装版本的证明。

本次源码和 STRU 语义核对使用公开仓库的官方 `v3.10.1` tag：

- [`source/module_cell/read_atoms.cpp`](https://raw.githubusercontent.com/deepmodeling/abacus-develop/v3.10.1/source/module_cell/read_atoms.cpp)
- [`docs/advanced/input_files/stru.md`](https://raw.githubusercontent.com/deepmodeling/abacus-develop/v3.10.1/docs/advanced/input_files/stru.md)
- [v3.10.1 发布记录](https://github.com/abacusmodeling/abacus-develop/releases/tag/v3.10.1)

公开仓库当前不能直接取得 package revision `4d3cbab83d661a25770eee61ce9275be0bfebe08` 的独立源码文件；公开 tag 实际指向 `f71921fe848659deac8db319cd4311b55b5ad480`。因此下面的 `mag`/`magmom` 细节是固定版本 tag 的源码级佐证，不是安装二进制的逐文件源码证明。现有任务没有逐原子 `mag` 或全零自旋 autoset 正例，当前不能声称两种源码的这些行为已比较一致。必须以安装二进制的小型原生输入回显验证落实软件合同，源码差异与生产资格另行审查。

`UnitCell::read_atom_positions` 在每个原子坐标行后接受 `mag` 或 `magmom`。当 `nspin=2` 时，一个标量被作为共线磁矩的 z 分量；若继续给出两个数，则按三个分量读取。源码将逐原子值写入 `atoms[it].mag[ia]`，并把元素块第二行的默认磁矩置为零。文档也明确说明逐原子 `mag` 会覆盖元素块的默认磁矩。

因此，同一元素的四个原子可以写成：

```text
Ni
0.0
4
0.00 0.00 0.00 m 1 1 1 mag  0.6
0.00 0.50 0.50 m 1 1 1 mag -0.6
0.50 0.00 0.50 m 1 1 1 mag  0.3
0.50 0.50 0.00 m 1 1 1 mag -0.3
```

源码还有一个必须显式处理的行为：如果 `nspin=2` 下所有逐原子磁矩的绝对值都不超过约 `1e-5`，ABACUS 会进入 autoset 分支并把每个原子的初始磁矩设为 `1.0`。所以新的 P6 输入资格检查不应接受“`nspin=2` 且全零”作为明确的非磁性输入；非磁性参考应使用现有 `nspin=1` 路径，或另行设计并记录 ABACUS autoset 行为。

ABACUS 在读取共线输入时还会在 `running_scf.log` 中输出初始磁矩回显。对于同一元素的多个原子，第一原子总会输出，后续与第一原子不同的原子会带有 `(atomN)` 标记。这个回显是“ABACUS 读入的初始种子”，不是收敛后的局域磁矩。

## 2. 当前 MLCC 适配器审查

当前 [`abacus.py`](../mlcc-agent/src/mlcc/abacus.py) 的 `AbacusMethod` 只有 `initial_moments_muB_by_element`。`_write_stru()` 写入元素级默认值和 `m 1 1 1`，没有逐原子 `mag`。

当前 `STRU.atom-map.json` 已经包含：

- `source_index`；
- 稳定 `atom_id`；
- ABACUS 分组后的 `abacus_index`；
- 元素和标签。

因此无需改变原子排序协议，只需在现有映射上增加逐原子初始磁矩记录。

当前 `_read_stru()` 只读取坐标前三个数，忽略元素默认磁矩和坐标行中的全部 `mag`/`magmom` token，也没有给返回的 ASE `Atoms` 设置 `initial_magmoms`。ASE 本身可以保存 `initial_magmoms`，问题在于当前 MLCC 自定义 STRU 读取器没有保存它。

当前 Ni 工程模型的 `model.extxyz` 虽然有 `initial_magmoms` 数组，但 `prepare_abacus()` 实际使用的是方法配置中的元素级映射。不能把模型中已有数组静默当成用户选择的 P6 磁态。

此外，ABACUS 3.10.1 已有关于 `STRU_ION_D` 丢失原子磁矩信息的报告：[issue #6782](https://github.com/deepmodeling/abacus-develop/issues/6782)。所以初始磁态必须从任务请求、`method.json`、`STRU` 和 atom map 保存，不能从 relax 后的 `STRU_ION_D` 反推。

## 3. 建议的最小实现切片

### 3.1 方法输入

在 `AbacusMethod` 增加一个可选的、仅用于新磁态任务的字段：

```python
initial_moments_muB_by_atom_id: Mapping[int, float] | None
```

JSON 使用字符串键，内部规范化为整数：

```json
{
  "initial_moments_muB_by_atom_id": {
    "0": 0.6,
    "1": -0.6,
    "2": 0.3,
    "3": -0.3
  }
}
```

检查要求：

1. 覆盖模型全部 `atom_id`，不能按元素或位置顺序补值；
2. 值必须有限；
3. `nspin=1` 时所有值必须为零；
4. `nspin=2` 时拒绝全零映射，避免触发 ABACUS autoset；
5. 新任务的逐原子映射与请求中的磁态映射必须逐项相同。

当该字段存在时，`_write_stru()` 将元素默认值写为明确的零，并在每个原子行写 `mag <scalar>`。没有该字段的旧工程任务保持现有元素级输入行为。

### 3.2 atom map 和 method 记录

每个 `abacus_order` 条目增加：

```json
"initial_moment_muB": 0.6
```

`method.json` 保存完整的 `initial_moments_muB_by_atom_id`。这两个记录分别绑定“模型 atom_id 到 ABACUS 行”和“方法配置到生成输入”。

### 3.3 任务请求和结果

新任务的 `request.json` 增加显式磁态对象：

```json
{
  "magnetic_state": {
    "schema": "mlcc.abacus-magnetic-input.v001",
    "state_id": "ni-collinear-state-a",
    "assignment_basis": "model.atom_id",
    "initial_moments_muB_by_atom_id": {
      "0": 0.6,
      "1": -0.6,
      "2": 0.3,
      "3": -0.3
    },
    "label": "user_selected"
  }
}
```

`create_abacus_task()` 将该对象写入 `task.json`，并确认它与 `method.json` 和生成的 `STRU.atom-map.json` 一致。不得自动生成 FM、AFM 或其他磁态标签。

`parse_abacus_task()` 后续可增加：

```json
{
  "magnetic_native_observation": {
    "schema": "mlcc.abacus-magnetic-observation.v001",
    "state_id": "ni-collinear-state-a",
    "initial_moments_muB_by_atom_id": {"0": 0.6, "1": -0.6, "2": 0.3, "3": -0.3},
    "native_echo_status": "matched_input",
    "final_total_magnetization_muB": 2.41425570809,
    "local_moment_status": "unsupported",
    "magnetic_order_status": "unassessed",
    "scientific_qualification": false,
    "production_qualification": false
  }
}
```

`final_total_magnetization_muB` 继续来自现有原生日志解析；它不等价于逐原子最终磁矩。

### 3.4 原生回显门

后续新增的磁性读取器应复用现有 ABACUS 任务身份和原生来源检查，并额外确认：

- `task.json`、`method.json`、`result.json` 的 task/model/method/job 身份一致；
- `INPUT` 的 `nspin` 与 `method.json` 一致；
- `STRU`、atom map、请求磁态的逐原子映射一致；
- `running_scf.log` 的初始磁矩回显与输入一致；
- 只支持当前 collinear、非 SOC、固定胞 SCF/现有 relax 范围。

若原生回显只显示首个原子和与首个原子不同的原子，读取器应结合完整输入映射解释未重复输出的相同值，不能把日志缺少重复行误报为局域磁矩结果。

## 4. 有界 Ni4 验收设计

这不是本轮计算任务。代码完成后，才在 v100 上准备一个单独的 Ni4 固定胞 SCF 输入，用于验证：

1. `request.json` 的 `atom_id` 映射被写入 `method.json`、`STRU` 和 atom map；
2. ABACUS 3.10.1 能接受逐原子 `mag` 标量；
3. `running_scf.log` 的初始磁矩回显能够与输入绑定；
4. 现有总磁矩解析仍然有效；
5. 结果保持 `scientific_qualification=false` 和 `production_qualification=false`。

现有 `workspace/tasks/h1-ni-scf-v001` 可作为旧元素级输入和总磁矩原生解析的真实回归证据，但不能作为逐原子 `mag` 已经真实执行的正例。没有新的 V100 原生任务前，逐原子输入只能验收软件生成和身份门。

建议的测试文件所有权：

- `tests/test_abacus.py`：逐原子 `STRU` 写入、atom map 和无效映射拒绝；
- `tests/test_abacus_tasks.py`：请求、method、task 的磁态绑定；
- `tests/test_magnetism.py`：真实 Ni 旧任务读取、篡改副本拒绝、native echo 门和不可比较状态。

## 5. 明确边界

本切片不提供：

- 最终局域磁矩或自旋密度；
- FM/AFM 等磁序判定；
- 磁性基态或全局最低能态判定；
- SOC、MAE、交换参数、U/J；
- Curie 温度或温度相关磁性；
- 生产材料资格。

两个不同初始磁矩输入即使都收敛，也只能形成“用户指定的两个自洽态观测”。只有在相同几何、相同方法和相同能量定义下完成多个明确状态的真实任务后，系统才可以进一步计算相对能；仍不能仅凭一个 Ni4 SCF 宣称磁性基态或磁序。

