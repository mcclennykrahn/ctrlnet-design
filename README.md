# ctrlnet — 平面控制网精度估算与优化设计（MVP 计算核心）

`ctrlnet` 是一个纯 Python、无 GUI 的平面控制网**设计态（先验）**计算核心，实现
[`docs/redesign_plan.md`](docs/redesign_plan.md) 中“平面控制网精度估算与优化设计”
重设计方案的 MVP 部分：

- 距离、方向、角度、二维 GNSS 基线、坐标伪观测；
- 固定基准、加权基准、自由网/最小约束与秩亏诊断；
- 设计矩阵解析偏导、Cholesky 白化、SVD 求协方差；
- 点位中误差、标准/置信误差椭圆、边长相对精度；
- 多余观测分量 `r_i`、MDB、外部可靠性、w 检验；
- 方案对比、贪心观测增补优化（最大 `mp`、trace、最弱边）；
- 第 13 节黄金算例的精度与可靠性回归；
- 生成网图、对比图、可靠性图、优化过程图、CSV 与中文 `results.md`。

数值约定：内部长度单位为米、角度/方向为弧度；显示时距离用 mm、角度用角秒。
项目只做设计阶段的先验精度估算，不做实测观测值的后验平差。

## 1. 与 docs 方案的对应关系

| 重设计方案 | 本仓库实现 | 状态 |
|---|---|---|
| §5.3 基准与秩：固定/加权/最小约束/自由网 | `datum.py`、`adjustment.py`；SVD 秩、零空间诊断、伪逆 | ✅ MVP |
| §5.4 可靠性：`Qv`、`R`、`r_i`、MDB、外部可靠性、w 检验 | `reliability.py`；λ0 用 `statistics.NormalDist` 精确计算，默认 7.849 | ✅ MVP |
| §5.5 精度：`mp`、误差椭圆、边长相对精度、最弱点/边 | `precision.py`；标准椭圆与 95% 椭圆，`k=sqrt(-2ln0.05)` | ✅ MVP |
| §5.6 优化：贪心、预算/阈值、A 最优/最弱边 | `optimize.py`；贪心 + 可选 1 换 1 局部搜索 | ✅ MVP（贪心子集） |
| §10.2 第 13 节黄金回归 | `examples.py`、`tests/test_section13.py` | ✅ 全部通过 |
| 数据模型（点、观测、网、方案） | `model.py`；不可变计算入口，直接构造 `Network`/`Scenario` | ✅ MVP |
| 报告与图件 | `report.py`、`plot.py`、`scripts/run_demo.py` | ✅ MVP |
| 地图/离线底图/MBTiles、扫描图配准 | — | ❌ 未实现（后续 UI/GIS） |
| GUI、工程树、地图选点、交互编辑 | — | ❌ 未实现 |
| FastAPI/数据库/工程包/快照持久化 | — | ❌ 未实现（当前为内存对象） |
| DEM 通视、地球曲率/折光、投影归算 | — | ❌ 未实现 |
| 水准/高程网、三角高程、geoid | — | ❌ 未实现 |
| GNSS 三维 ECEF/ENU、跨基线完整 VCV、Helmert | 仅二维基线（2×2 协方差） | ⚠️ 部分 |
| 方差分量估计、稳健估计、数据 snooping 全流程 | 仅提供设计态 `r_i`/MDB 与 `w_test` 函数 | ⚠️ 部分 |
| MICP/MILP/Pareto、A/D/E 精确最优 | 仅贪心与简单局部搜索 | ⚠️ 部分 |

## 2. 安装

要求 Python ≥ 3.9，依赖 `numpy>=1.24`、`matplotlib>=3.6`；测试额外需要 `pytest`。

```bash
cd /workspace/ctrlnet-design
python -m venv .venv
source .venv/bin/activate
pip install -e ".[test]"
```

也可以使用已有的虚拟环境：

```bash
/workspace/venvs/ctrlnet/bin/pip install -e /workspace/ctrlnet-design
```

如果运行环境中的 venv/site-packages 只读，可以不安装，直接从 `src` 运行：

```bash
PYTHONPATH=src /workspace/venvs/ctrlnet/bin/python -m pytest -q
```

仓库已在 `pyproject.toml` 中配置 `pythonpath = ["src"]`，因此在仓库根目录直接运行
`python -m pytest -q` 也能找到包；演示脚本也带有 `src` 回退。

## 3. 运行测试

```bash
cd /workspace/ctrlnet-design
/workspace/venvs/ctrlnet/bin/python -m pytest -q
```

当前测试覆盖：

- `tests/test_section13.py`：第 13 节两方案的点 `σE/σN/mp`、椭圆半轴、5 条边 `σs`
  与相对精度分母、`rank=4`、冗余 3/4、`Cx` 对称、`sum r_i=3/4`、可靠性
  `r_i`/MDB/外部影响、距离/方向/角度偏导中心差分、观测顺序与参数顺序不变性；
- `tests/test_rank.py`：缺固定点、单观测待定点、自由网最小约束、加权基准、
  `σ≤0`、NaN、重合点、非法 GNSS 相关系数；
- `tests/test_optimize.py`：贪心加入观测后最大 `mp` 单调不增、预算约束、
  目标阈值、trace 目标单调性。

预期结果：`24 passed`。

## 4. 运行演示

```bash
cd /workspace/ctrlnet-design
/workspace/venvs/ctrlnet/bin/python scripts/run_demo.py
```

脚本会打印第 13 节两方案的关键精度/可靠性表，并在 `outputs/` 生成图件、CSV
和中文汇总 `results.md`。

Notebook 与脚本同源（`scripts/build_notebook.py` 从脚本的 `# %%` 单元生成），
已执行版本在 `notebooks/demo.ipynb`。重新生成并执行：

```bash
/workspace/venvs/ctrlnet/bin/python scripts/build_notebook.py
/workspace/venvs/ctrlnet/bin/python -m ipykernel install --user --name ctrlnet
/workspace/venvs/ctrlnet/bin/python -m jupyter nbconvert \
  --to notebook --execute --inplace \
  --ExecutePreprocessor.kernel_name=ctrlnet notebooks/demo.ipynb
```

如果无法写入用户 kernelspec 目录，可用 `--prefix` 安装到仓库内，并通过
`JUPYTER_PATH` 指定：

```bash
/workspace/venvs/ctrlnet/bin/python -m ipykernel install \
  --prefix /workspace/ctrlnet-design/.jupyter --name ctrlnet
JUPYTER_PATH=/workspace/ctrlnet-design/.jupyter/share/jupyter \
  /workspace/venvs/ctrlnet/bin/python -m jupyter nbconvert \
  --to notebook --execute --inplace \
  --ExecutePreprocessor.kernel_name=ctrlnet notebooks/demo.ipynb
```

## 5. 输出说明

运行演示后 `outputs/` 包含（该目录是交付物，已提交）：

| 文件 | 内容 |
|---|---|
| `network_ellipses_base.png` | 基准方案网图 + 标准/95% 误差椭圆；椭圆放大 1000× |
| `network_ellipses_added.png` | 增补方案网图 + 标准/95% 误差椭圆；椭圆放大 1000× |
| `scenario_comparison.png` | 基准 vs 增补：各点 `mp`、各边相对精度分母 |
| `reliability_ri.png` | 两方案每条观测的 `r_i`，标出 0.1/0.3/0.5 阈值线 |
| `optimizer_steps.png` | 贪心优化每步最大 `mp` |
| `points.csv` | 各方案点坐标、`σE/σN/mp`、标准/95% 椭圆半轴与方位 |
| `edges.csv` | 边长、`σs`、相对精度分母 |
| `reliability.csv` | `r_i`、MDB、MDB 单位、外部最大分量/向量范数、影响点 |
| `optimizer.csv` | 初始与每步目标值、收益、成本、已选观测 |
| `results.md` | 中文汇总表格与说明 |

图件中如检测不到中文字体，会自动退回英文标签，避免方框乱码；本机有 Noto CJK
字体时使用中文。误差椭圆在网图中做了 1000 倍放大，图题中已注明。

## 6. API 简例

```python
from ctrlnet import (
    analyze_precision,
    analyze_reliability,
    section13_base,
    solve,
)

scenario = section13_base()          # A/B 固定，C/D 待定
result = solve(scenario)             # AdjustmentResult
precision = analyze_precision(result)
reliability = analyze_reliability(result)

print(result.rank, result.redundancy, result.condition_number)
for name in ("C", "D"):
    p = precision.points[name]
    print(name, p.sigma_E_mm, p.sigma_N_mm, p.mp_mm)
for row in reliability.records:
    print(row.label, row.r_i, row.mdb_display, row.external_max_mm)
```

自定义网：

```python
from ctrlnet import Angle, Distance, FixedDatum, Network, Point, Scenario, solve

net = Network(
    [
        Point("A", 0.0, 0.0, fixed=True),
        Point("B", 100.0, 0.0, fixed=True),
        Point("C", 0.0, 100.0),
    ],
    [
        Distance("A", "C", a=0.002, b_ppm=2.0),
        Distance("B", "C", a=0.002, b_ppm=2.0),
        Angle("C", "A", "B", sigma_arcsec=1.0),
    ],
)
result = solve(Scenario("小网", net, datum=FixedDatum()))
print(result.rank, result.redundancy, result.point_covariance("C"))
```

## 7. 目录结构

```text
ctrlnet-design/
├── docs/                      # 原始方案、重设计方案、摘要
├── src/ctrlnet/
│   ├── model.py               # 点、距离、方向、角度、GNSS 基线、网、方案
│   ├── design.py              # 参数索引、设计矩阵、白化
│   ├── datum.py               # 固定/加权/最小/自由基准
│   ├── adjustment.py          # SVD 求解、秩诊断、协方差
│   ├── precision.py           # mp、误差椭圆、边相对精度
│   ├── reliability.py         # r_i、MDB、外部可靠性、w 检验
│   ├── compare.py             # 方案对比
│   ├── optimize.py            # 贪心增补与局部搜索
│   ├── plot.py                # 网图与椭圆
│   ├── report.py              # 中文表格
│   └── examples.py            # 第 13 节两方案
├── tests/                     # 黄金回归、秩/异常、优化测试
├── scripts/
│   ├── run_demo.py            # 演示主脚本
│   └── build_notebook.py      # 由脚本生成 notebook
├── notebooks/demo.ipynb       # 已执行的演示 notebook
├── outputs/                   # 图件、CSV、results.md（提交）
├── pyproject.toml
├── requirements.txt
└── README.md
```

## 8. 计算约定与限制

- 设计态：`σ0=1`，`Cx=(AᵀQl⁻¹A)⁺`，不估计单位权方差，不做实测残差平差。
- 距离先验方差：`σ²=a²+(b·10⁻⁶·s)²`；角度/方向标准差按角秒输入，内部转弧度。
- 标准误差椭圆不乘置信系数（约 39.35%）；95% 椭圆乘
  `k=sqrt(χ²(2,0.95))=sqrt(-2ln0.05)≈2.4477`。
- `r_i` 对独立观测为 `1-h_ii`；GNSS 2×2 基线按块内对角元求和。`trace(R)=n-rank`。
- MDB 默认 `λ0=7.849`（α=0.05 双侧，power=0.80）；外部可靠性取 MDB 引起的
  **最大单个坐标分量绝对值**（mm），同时保留向量范数。
- 固定点协方差为 0；自由网/最小约束使用 Moore–Penrose 伪逆，`Cx` 与所选基准
  相关，不能与固定基准结果直接比较。
- 加权基准通过坐标伪观测实现，伪观测行进入 `Ql`，默认不计入观测可靠性列表。
- 当前仅支持二维平面网；GNSS 只实现二维基线（2×2 协方差）；未实现投影归算、
  DEM 通视、水准/高程网、地图/GUI/API/数据库。
