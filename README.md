# ctrlnet — 平面/高程控制网精度估算与优化设计（MVP 计算核心）

`ctrlnet` 是一个纯 Python 的平面/高程控制网**设计态（先验）**计算核心，并附带
可选的本地只读网页地图（FastAPI + 离线 Leaflet），
实现 [`docs/redesign_plan.md`](docs/redesign_plan.md) 中“平面控制网精度估算与优化
设计”重设计方案的 MVP 与 P1/P2 部分能力：

- 平面网：距离、方向、角度、二维 GNSS 基线、坐标伪观测；
- 平面基准：固定基准、加权基准、自由网/最小约束与秩亏诊断；
- 设计矩阵解析偏导、Cholesky 白化、SVD 求协方差；
- 点位中误差、标准/置信误差椭圆、边长相对精度；
- 可靠性：多余观测分量 `r_i`、MDB、外部可靠性、w 检验；
- 模拟观测与实测平差：按先验 σ 生成距离/方向/角度/GNSS 2D/水准观测，可注入
  k·σ 粗差；平面网高斯-牛顿迭代、水准网线性迭代；
- 粗差探测与稳健估计：Baarda w 检验与迭代 snooping、Pope τ 检验、χ² 整体检验、
  Huber 与 IGG-III 迭代重加权最小二乘；
- 水准/高程网：1D 高程参数、固定/加权/自由网基准、水准测段与闭合环；
- 三角高程：斜距/平距 + 天顶距、仪器高/目标高、曲率折光改正与误差传播；
- DEM 地形：GeoTIFF 读取、双线性采样、剖面、曲率/折光通视、晕渲与等高线；
- 通视约束网：只用通视的距离/角度边做平面平差，并把 95% 误差椭圆叠加到晕渲图；
- 本地网页地图：FastAPI + 包内离线 Leaflet，晕渲/等高线/控制点/观测线/误差椭圆与两点剖面；
- 六参数仿射影像配准：最小二乘、逐点残差/RMS、`.pgw`/`.tfw` 世界文件与网页 4 点配准演示；
- 方案对比、贪心观测增补优化（最大 `mp`、trace、最弱边）；
- 第 13 节黄金算例的精度与可靠性回归；
- 生成网图、对比图、可靠性图、优化过程图、水准路线图、地形图、CSV 与中文报告。

数值约定：内部长度/高程单位为米、角度/方向为弧度；显示时距离/高差用 mm，
角度用角秒。DEM 计算使用米制局部 UTM 坐标。项目以设计阶段先验精度估算为主，
C1 起补充实测模拟观测的平差、粗差探测与稳健估计；仍不做 geoid/高程异常转换
（`height_type` 仅作为属性字段），也不实现完整工程数据库。

## 1. 与 docs 方案的对应关系

| 重设计方案 | 本仓库实现 | 状态 |
|---|---|---|
| §5.3 基准与秩：固定/加权/最小约束/自由网 | `datum.py`、`adjustment.py`；SVD 秩、零空间诊断、伪逆 | ✅ MVP |
| §5.4 可靠性：`Qv`、`R`、`r_i`、MDB、外部可靠性、w 检验 | `reliability.py`；λ0 用 `statistics.NormalDist` 精确计算，默认 7.849 | ✅ MVP |
| §5.10 粗差探测与稳健估计：模拟观测、w/τ/χ²、Huber/IGG-III | `robust.py`；高斯-牛顿、迭代 snooping、IRLS、MAD 尺度 | ✅ P1/C1 |
| §5.5 精度：`mp`、误差椭圆、边长相对精度、最弱点/边 | `precision.py`；标准椭圆与 95% 椭圆，`k=sqrt(-2ln0.05)` | ✅ MVP |
| §5.6 优化：贪心、预算/阈值、A 最优/最弱边 | `optimize.py`；贪心 + 可选 1 换 1 局部搜索 | ✅ MVP（贪心子集） |
| §5.9 水准/高程网：路线/环、`σ_km`、固定/加权/自由基准、`r_i`/MDB | `leveling.py`；1D 设计矩阵、SVD、伪逆、相对高差精度 | ✅ P1/B1 |
| §5.9.5 三角高程：斜距/平距、天顶距、曲率折光、误差传播 | `leveling.py`；解析偏导与逐项误差贡献 | ✅ P1/B1 |
| §5.2 坐标与投影：局部 UTM、经纬度↔米制转换 | `fetch_dem.py`、`terrain.py`；样例重投影到 EPSG:32650 | ✅ P1/B2（局部） |
| §5.7 DEM 通视：双线性采样、剖面、曲率/折光、四态判定 | `terrain.py`；`DEM`、`profile`、`intervisibility` | ✅ P1/B2 |
| §5.7 地形渲染：晕渲、等高线 | `terrain.py`；`hillshade`、`contours` | ✅ P1/B2 |
| §5.2.7 地图/地形图配准：6 参数仿射、控制/检查点、残差 RMS | `registration.py`；`register_affine`/`register_image`、世界文件 | ✅ P1/B3 |
| §7 接口：图层、剖面、晕渲、配准资源 | `webmap/app.py`；本地 FastAPI `/api/*` | ✅ P1/B3（只读单工程） |
| §8 界面：地图、图层、属性、剖面图 | `webmap/static/`；Leaflet `CRS.Simple` + SVG 剖面 | ✅ P1/B3（演示级） |
| §10.2 第 13 节黄金回归 | `examples.py`、`tests/test_section13.py` | ✅ 全部通过 |
| §10.3 水准模块验证：闭合差、秩 1、`Σr_i`、三角高程公式 | `tests/test_leveling.py` | ✅ 全部通过 |
| §10.3 DEM 模块验证：平面/斜面/山脊、曲率折光、插值、晕渲 | `tests/test_terrain.py` | ✅ 全部通过 |
| 数据模型（点、观测、网、方案） | `model.py`；不可变计算入口，直接构造 `Network`/`Scenario` | ✅ MVP |
| 报告与图件 | `report.py`、`plot.py`、`scripts/run_demo.py` | ✅ MVP |
| 地图/离线底图/MBTiles、扫描图配准 | `webmap/` 的单工程 DEM imageOverlay、扫描图配准与半透明叠加；MBTiles/矢量瓦片未实现 | ⚠️ 部分（B3） |
| GUI、工程树、地图选点、交互编辑 | 本地只读网页地图：图层开关、点/线点击、两点剖面；无工程树与编辑 | ⚠️ 部分（B3） |
| FastAPI/数据库/工程包/快照持久化 | `webmap/app.py` 只读 FastAPI 服务；无数据库、工程包与快照 | ⚠️ 部分（B3） |
| 投影归算全链路（投影尺度、子午线收敛角、跨带） | 仅实现局部 UTM 与 DEM 采样；未做 grid/ground 全链路归算 | ⚠️ 部分 |
| geoid/高程异常转换、GNSS 大地高→正常高 | 仅记录 `height_type`；无 N 模型/方差 | ❌ MVP 明确不做 |
| GNSS 三维 ECEF/ENU、跨基线完整 VCV、Helmert | 仅二维基线（2×2 协方差） | ⚠️ 部分 |
| 方差分量估计（VCE） | 未实现 Helmert/最小范数二次无偏估计 | ❌ 未实现 |
| MICP/MILP/Pareto、A/D/E 精确最优 | 仅贪心与简单局部搜索 | ⚠️ 部分 |

## 2. 安装

要求 Python ≥ 3.9。运行时依赖 `numpy>=1.24`、`matplotlib>=3.6`；`test` extra
提供 `pytest`、`httpx`、`fastapi`、`pillow`、`rasterio`，`demo` extra 提供
`ipykernel`、`nbconvert`、`nbformat`，`terrain` extra 提供 `rasterio`，
`webmap` extra 提供 FastAPI/uvicorn/pillow/rasterio。

```bash
cd /workspace/ctrlnet-design
python3 -m venv .venv
.venv/bin/pip install -e ".[test,demo,terrain,webmap]"  # 只跑测试可改用 ".[test]"
# 只跑 B2 DEM 演示：.venv/bin/pip install -e ".[test,terrain]"
# 只跑 B3 网页地图：.venv/bin/pip install -e ".[test,webmap]"
```

`pip install -e` 会按 `pyproject.toml` 的 `src` 布局注册 editable 包，测试和演示
都直接 `import ctrlnet`，不再使用 `pythonpath = ["src"]` 或 `sys.path` 回退。
安装后确认导入位置：

```bash
.venv/bin/python -c "import ctrlnet; print(ctrlnet.__file__)"
# 应输出 /workspace/ctrlnet-design/src/ctrlnet/__init__.py
```

## 3. 运行测试

```bash
cd /workspace/ctrlnet-design
.venv/bin/python -m pytest -q
```

当前测试覆盖：

- `tests/test_section13.py`：第 13 节两方案的点 `σE/σN/mp`、椭圆半轴、5 条边 `σs`
  与相对精度分母、`rank=4`、冗余 3/4、`Cx` 对称、`sum r_i=3/4`、可靠性
  `r_i`/MDB/外部影响、距离/方向/角度偏导中心差分、观测顺序与参数顺序不变性；
- `tests/test_rank.py`：缺固定点、单观测待定点、自由网最小约束、加权基准、
  `σ≤0`、NaN、重合点、非法 GNSS 相关系数；
- `tests/test_optimize.py`：贪心加入观测后最大 `mp` 单调不增、预算约束、
  目标阈值、trace 目标单调性；
- `tests/test_robust.py`：固定种子模拟观测、近似坐标高斯-牛顿收敛、χ² 全局检验、
  无粗差无误判、10σ 粗差被 w 检验与 IGG-III 定位、稳健解接近无粗差解、
  `r_i` 与可控性关系、水准/GNSS 2D/方向观测接口；
- `tests/test_leveling.py`：单路线 `σ_km·sqrt(L)` 与测站数随机模型、闭合环/
  附合路线解析 `Cx`、`Σr_i=冗余数`、无基准秩亏、自由网最小约束、加权高程约束、
  三角高程公式/球气差/斜距-平距等价/误差传播有限差分、`height_type` 属性；
- `tests/test_terrain.py`：平面/斜面 DEM 的双线性插值精确性、剖面端点与步长、
  平地通视、高斯山脊遮挡、提高仪器高后通视、长距离曲率+折光下沉公式、
  `marginal`/NoData `unknown` 四态、晕渲范围 `[0,1]` 与等高线冒烟测试；
- `tests/test_registration.py`：已知仿射精确恢复、加噪 RMS 合理性、少于 3 点/
  共线/非法权值报错、PNG 配准与 `.pgw`/`.tfw` 世界文件往返；
- `tests/test_webmap.py`：TestClient 覆盖页面、离线 Leaflet 静态资源、
  `/api/project`、`/api/layers`、晕渲 PNG、通视/遮挡剖面、配准演示与叠加 PNG。

预期结果：`70 passed`（FastAPI TestClient 会提示一条 httpx 弃用警告，不影响结果）。

## 4. 运行演示

```bash
cd /workspace/ctrlnet-design
.venv/bin/python scripts/run_demo.py
.venv/bin/python scripts/run_leveling_demo.py
.venv/bin/python scripts/run_robust_demo.py     # C1 粗差探测与稳健估计
.venv/bin/python scripts/fetch_dem.py          # 可选：重新下载/裁剪 DEM 小样本
.venv/bin/python scripts/run_terrain_demo.py   # B2 DEM 通视与误差椭圆演示
.venv/bin/python scripts/make_scan_sample.py   # B3 示例扫描图 + 4 对控制点
.venv/bin/ctrlnet-web                          # B3 本地网页地图（127.0.0.1:8765）
# 或：.venv/bin/python -m ctrlnet.webmap --port 8765
```

`run_demo.py` 打印第 13 节两方案的关键精度/可靠性表，并生成平面网图件、CSV
和中文汇总 `results.md`。`run_leveling_demo.py` 演示 6 点水准网 + 两条三角高程
观测，生成高程点 CSV、中文结果与水准路线图。`run_terrain_demo.py` 在真实
Copernicus GLO-30 子区域上选 7 个高地控制点，做全部 21 对通视分析，并用通视
距离/角度边构网，输出地形图、剖面图、CSV、误差椭圆图与示例工程 JSON。
`make_scan_sample.py` 生成 `data/sample/scan_sample.png` 与 4 对控制点/2 个检查点
元数据；`ctrlnet-web` 启动只绑定回环地址的网页地图，浏览器访问
`http://127.0.0.1:8765/`。

Notebook 与脚本同源（`scripts/build_notebook.py` 从脚本的 `# %%` 单元生成），
已执行版本在 `notebooks/demo.ipynb`，kernel 名为 `ctrlnet-venv`。重新生成并执行：

```bash
.venv/bin/python scripts/build_notebook.py
.venv/bin/python -m ipykernel install --user \
  --name ctrlnet-venv --display-name "ctrlnet (.venv)"
.venv/bin/python -m jupyter nbconvert \
  --to notebook --execute --inplace \
  --ExecutePreprocessor.kernel_name=ctrlnet-venv notebooks/demo.ipynb
```

如果用户 kernelspec 目录不可写（例如只读 HOME），可把 kernel 安装到仓库内被
`.gitignore` 忽略的 `.jupyter/`，执行时通过 `JUPYTER_PATH` 指定：

```bash
.venv/bin/python -m ipykernel install \
  --prefix /workspace/ctrlnet-design/.jupyter \
  --name ctrlnet-venv --display-name "ctrlnet (.venv)"
JUPYTER_PATH=/workspace/ctrlnet-design/.jupyter/share/jupyter \
  .venv/bin/python -m jupyter nbconvert \
  --to notebook --execute --inplace \
  --ExecutePreprocessor.kernel_name=ctrlnet-venv notebooks/demo.ipynb
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
| `results.md` | 平面网中文汇总表格与说明 |
| `leveling_points.csv` | 水准点高程、`σ_H`、基准角色与高程类型 |
| `leveling_results.md` | 水准/三角高程中文结果、闭合环、相对高差与可靠性表 |
| `leveling_network.png` | 水准路线图；点标注 `H`/`σ_H`，线宽按观测权重 `1/σ²` |
| `blunder_detection.png` | C1 粗差探测：迭代前后各观测 `|w|`、临界线、IGG-III 权因子与坐标偏差对比 |
| `robust_results.md` | C1 中文汇总：LS/剔除后 LS/Huber/IGG-III 偏差、snooping 轮次、`r_i` 与可控性 |
| `robust_results.csv` | C1 各方法、各待定点的真值/估值/偏差、异常标签与粗差权因子 |
| `dem_hillshade_contours.png` | 真实 DEM 晕渲 + 50 m 等高线 + 7 个控制点 + 21 对观测线（绿=通视，红=遮挡） |
| `intervisibility_profiles.png` | 6 条代表性剖面：地形、两端连线、曲率/折光视线、遮挡点与最小净空 |
| `intervisibility.csv` | 全部点对的 `status/visible/min_clearance`、遮挡位置、仪器高/目标高、`k/R`、采样数 |
| `dem_network_ellipses.png` | 只用通视距离/角度边的平面网 95% 误差椭圆叠加在晕渲图上（图题注明放大倍数） |
| `webmap_screenshot.png` | B3 本地网页地图首屏：DEM 晕渲/等高线/观测线/误差椭圆、配准影像与 4 点 RMS |
| `webmap_profile_screenshot.png` | B3 网页剖面：P1→P6 地形线、曲率折光视线、遮挡点与净空 |

图件中如检测不到中文字体，会自动退回英文标签，避免方框乱码；本机有 Noto CJK
字体时使用中文。误差椭圆在网图中做了 1000 倍放大，图题中已注明。

网图图例固定在坐标轴右侧外部，点名标签沿网形中心向外放置并位于误差椭圆之外，
不会遮挡点位或椭圆。观测线统一使用深色、线宽 ≥ 1.5：距离为黑色实线，角度为
绿色点划线并在测站处画出小圆弧及带箭头的两条方向线；方向/GNSS 基线分别用橙色
虚线和紫色虚线。`scenario_comparison.png`、`reliability_ri.png` 的图例放在
子图下方外部，`optimizer_steps.png` 的步骤标注放在数据点下方并用细引线连接，
均避免遮挡柱体、折线或数值标签。

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

## 7. 高程/水准网（B1）

### 7.1 快速开始

```python
from ctrlnet import (
    HeightDifference, LevelingNetwork, LevelingPoint, TrigHeight, solve_leveling,
)

net = LevelingNetwork(
    [
        LevelingPoint("A", 100.000, fixed=True),          # 固定高程基准
        LevelingPoint("B", 101.500),                      # 待定
        LevelingPoint("C", 102.300, sigma_H=0.003),       # 加权约束（3 mm）
    ],
    [
        # σ = σ_km·sqrt(L) = 1.0 mm/√km · sqrt(1.2 km)
        HeightDifference("A", "B", +1.500, length_km=1.2, sigma_per_km_mm=1.0),
        # 也可按测站数：σ = σ_station·sqrt(n)
        HeightDifference("B", "C", +0.800, n_stations=9, sigma_per_station_mm=0.5),
        # 三角高程：斜距 + 天顶距 + 仪器高/目标高 + 曲率折光
        TrigHeight(
            "A", "C", slope_distance=950.0, zenith_deg=89.83,
            instrument_height=1.52, target_height=1.50,
            k=0.13, R=6371000.0, sigma_zenith_arcsec=1.0,
        ),
    ],
)
result = solve_leveling(net)  # 默认 auto：固定点 + 非固定点 sigma_H 加权约束

print(result.rank, result.redundancy, result.Cx)
for name in result.point_order:
    p = result.point_precision(name)      # H / sigma_H / role
    print(name, p.H, p.sigma_mm)
print(result.relative_height("A", "C").sigma_mm)
for row in result.observation_records:    # 不含加权约束行
    print(row.label, row.kind, row.r_i, row.mdb_mm, row.external_max_mm)
```

### 7.2 模型与约定

- 观测方程：`Δh_ij = H_j − H_i + v`；设计矩阵对 `to` 为 `+1`、`frm` 为 `−1`。
- 随机模型优先级：显式 `sigma_mm` > `n_stations + sigma_per_station_mm` >
  `length_km + sigma_per_km_mm`。后两者分别按 `sqrt(n)`、`sqrt(L)` 传播。
- 基准：`fixed`（固定点）、`weighted`（`sigma_H` 伪观测）、`minimal`/`free`
  （伪逆最小约束，零空间为整体高程平移）。默认 `auto` 同时使用固定点和加权
  约束；无任何高程基准时抛 `RankDeficientError`。
- 精度：`Cx` 为未知高程协方差（m²），`sigma_H` 为点高程中误差，
  `relative_height(frm, to)` 返回平差后高差与相对高差中误差。
- 可靠性：`r_i = 1 − h_ii`（独立观测）；`MDB=sqrt(λ0/K_ii)`；外部可靠性为
  粗差未检出时对任一点高程的最大绝对影响。`result.records` 含加权约束行，
  `result.observation_records` 只含水准/三角高程；`Σr_i = m − rank`。
- 三角高程：`Δh = S·cos z + (1−k)·S²·sin²z/(2R) + i − v`；平距形式
  `Δh = D·cot z + (1−k)·D²/(2R) + i − v`。误差传播包含 `σ_z`、`σ_S/σ_D`、
  `σ_i`、`σ_v` 与可选 `σ_k`。
- `height_type` 只记录 `normal`/`orthometric`/`ellipsoidal` 等属性；MVP
  **不**把 GNSS 大地高换算为正常高，也不估计 geoid 不确定度。

## 8. DEM 通视与地形渲染（B2）

### 8.1 数据与快速开始

真实 DEM 样例来自公开的 Copernicus GLO-30 DSM（AWS Open Data，无需登录）：

```text
https://copernicus-dem-30m.s3.amazonaws.com/
  Copernicus_DSM_COG_10_N39_00_E116_00_DEM/
  Copernicus_DSM_COG_10_N39_00_E116_00_DEM.tif
```

`scripts/fetch_dem.py` 下载整幅 1°×1° 瓦片（约 48 MB），裁剪北京西山
`116.00°E–116.10°E、39.90°N–40.00°N`，双线性重投影到当地 **UTM 50N
（EPSG:32650）**，输出 `data/sample/dem_sample.tif` 与同名元数据 JSON。原始
大文件只放 `data/cache/`（已 gitignore），仓库交付的样本约 0.3 MB（≤2 MB 限制）。

```bash
.venv/bin/python scripts/fetch_dem.py          # 已有缓存时自动跳过下载
.venv/bin/python scripts/run_terrain_demo.py   # 通视 + 地形 + 误差椭圆演示
```

```python
from ctrlnet import DEM, contours, hillshade

dem = DEM.from_geotiff("data/sample/dem_sample.tif")
z = dem.elevation(415500.0, 4421300.0)          # 双线性采样（米）
prof = dem.profile((415358.4, 4421306.6), (418358.4, 4422686.6), step=10.0)
vis = dem.intervisibility(
    (415358.4, 4421306.6),
    (418358.4, 4422686.6),
    inst_h=1.5, target_h=1.5,
    k=0.13, R=6371000.0, clearance=0.5,
)
print(vis.status, vis.visible, vis.min_clearance, vis.obstruction_position)
print(vis.profile.distance, vis.profile.elevation)  # 剖面数据
hs = hillshade(dem, azimuth=315, altitude=45)       # 返回 [0,1]
cs = contours(dem, levels=20)                       # Matplotlib QuadContourSet
```

### 8.2 计算约定

- **坐标**：`DEM` 直接使用其水平 CRS 的米制 `(E,N)`；样例为 UTM 50N。
  `AffineTransform` 采用 GeoTIFF 六参数 `(a,b,c,d,e,f)`：
  `E=a·col+b·row+c`、`N=d·col+e·row+f`。经纬度只用于工程 JSON/地图展示，
  由 `rasterio.warp.transform` 与 UTM 互转，不在计算内部混用。
- **采样**：GeoTIFF 变换定位像素角点，高程值位于像素中心；`elevation(E,N)`
  先换算到中心索引再减 `0.5`，按四个邻点双线性插值。越界或参与插值的任一
  邻点为 NoData 时返回 `nan`，不会把 NoData 当 0 m。
- **剖面**：`profile(p1,p2,step=None)` 等距采样且强制包含两端点；默认
  `step = clamp(0.5×分辨率, 0.5 m, 10 m)`（方案 §5.7.2）。
- **曲率/折光**：视线高度按方案 §5.7.3 的经典形式

  ```text
  h_LOS(x) = h1 + (h2−h1)·x/d − (1−k)·x(d−x)/(2R)
  ```

  其中 `h1=地面1+仪器高`、`h2=地面2+目标高`，`R=6 371 000 m`，默认
  `k=0.13`。改正项在两端为 0，跨中最大，等价于 `R_eff=R/(1−k)` 的弦线公式。
  `curvature_refraction_correction(x,d,k,R)` 可直接复核该项。
- **四态判定**：`min_clearance ≥ clearance` 为 `visible`；`<0` 为 `blocked`；
  `0 ≤ min_clearance < clearance` 为 `marginal`（需现场复核）；剖面存在
  NoData 或端点无效时为 `unknown`，不直接判为通视。默认 `clearance=0`；
  光学观测建议现场按 0.5–1.5 m 阈值复核。
- **晕渲**：`hillshade` 由高程梯度构造法向量，与方位角（自北顺时针）/高度角
  的太阳方向点积后截断到 `[0,1]`；`contours` 直接调用 Matplotlib
  `contour`/`contourf`，传入 `DEM` 时使用真实 E/N 坐标。
- **局限**：30 m Copernicus 样例是 DSM（含植被/建筑），垂直基准为 EGM2008
  正高；不能识别围墙、电杆、车辆等小障碍，也不等价于施工后地形。长边建议
  对 `k=0.10/0.13/0.16` 做敏感性分析，关键边仍需现场复测。

### 8.3 示例结果

当前样本 `289×374`、30 m 分辨率、高程 92.6–988.5 m；边缘重投影产生约
2.5% NoData，控制点选在内部高地，剖面未落入 NoData。演示脚本在 5×5 分块中
取局部最高点，搜索空间展开且通视连通的 7 点网（前两点固定）。当前结果为：

- 21 个点对中 16 对通视、5 对遮挡；
- 平面网只用通视边：16 条距离 + 60 个角度（每个测站所有可见方向两两组合）；
- `rank=10`、冗余 66、条件数约 6.87，未知点最大 `mp≈10.05 mm`；
- 95% 误差椭圆在图上放大 50 000×，图题与图例中明确标注。

`data/sample/terrain_project.json` 汇总下一步网页地图所需内容：点的经纬度 /
UTM E/N / 高程 / 固定标志、`σE/σN/mp`、95% 椭圆半轴与方位、通视距离/角度
观测、全部点对的通视状态与遮挡位置、DEM 来源/版本/垂直基准及 k/R/阈值。

## 9. 本地网页地图（B3）

### 9.1 启动与安全边界

网页地图是**只读单工程演示**，不写回工程、不需要账号，也不应暴露到公网。
服务只允许绑定回环地址（默认 `127.0.0.1:8765`），启动入口有两个：

```bash
cd /workspace/ctrlnet-design
.venv/bin/pip install -e ".[test,webmap]"

.venv/bin/ctrlnet-web --port 8765
# 等价：.venv/bin/python -m ctrlnet.webmap --port 8765
# 指定其他工程：--project /path/to/terrain_project.json
```

浏览器访问 `http://127.0.0.1:8765/`。`--host` 仅接受 `127.0.0.1`、`localhost`
和 `::1`；传入公网地址会直接拒绝启动。FastAPI 的 OpenAPI 文档在
`/api/docs`，但页面本身不依赖外部 CDN 或在线底图。

前端 Leaflet 1.9.4 的 JS/CSS/图标已放在
`src/ctrlnet/webmap/static/leaflet/`（含 MIT LICENSE），随 wheel 一起打包；
页面只请求本机 `/static`、`/api` 和本机 PNG，不访问 `unpkg`、Google Fonts
或任何瓦片服务，因此断网可用。

### 9.2 页面与图层

页面采用 Leaflet `CRS.Simple`，直接把样例 DEM 的 UTM 50N 米制 `(E,N)` 作为
地图坐标，避免在浏览器里重复做投影。默认视图覆盖 `data/sample/terrain_project.json`
的 7 个控制点，图层顺序与方案 §8 一致（底图→地形→控制网→结果）：

| 图层 | 来源/样式 | 交互 |
|---|---|---|
| DEM 晕渲 + 分层设色 | `terrain.hillshade` + 高程调色板，后端渲染为 PNG imageOverlay | 透明度/开关 |
| 等高线 | `contours()` 提取 50 m 等高线，输出 GeoJSON LineString；每 5 条加粗 | 开关 |
| 观测线 | `visibility` 的 21 对点；通视绿色实线、遮挡红色虚线 | 点击显示平距、最小净空、遮挡点坐标/高程 |
| 95% 误差椭圆 | 以 `ellipse_95` 的 a/b/方位角生成多边形，图上放大 50 000× | 点击显示半轴 mm、方位角、置信度与放大倍数 |
| 控制点 | 固定点三角形、待定点空心圆，永久点名标签 | 点击显示 E/N、经纬度、DEM 高程、σE/σN、mp、椭圆 |
| 配准影像 | 后端按 4 点仿射重采样后的半透明 RGBA PNG | 开关；控制点/检查点有独立符号与残差提示 |

页面点击地图两点即可请求 `/api/profile`，右侧绘制 SVG 剖面：地形填充、
两端连线、曲率/折光视线、红色遮挡点、最小净空和采样数。也可以点击观测线
查看同一信息；示例截图用 `P1→P6`（遮挡，最小净空约 −51.31 m）。

### 9.3 本地 API

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/project` | 工程元数据、点、观测、通视结果、DEM 摘要与 API 入口 |
| GET | `/api/layers` | 图层清单；等高线/观测线/椭圆/控制点以 GeoJSON 内联返回 |
| GET | `/api/overlay/hillshade.png` | DEM 晕渲 + 分层设色 PNG（NoData 透明） |
| GET | `/api/profile?from=&to=` | `from`/`to` 可点名（如 `P1`）或 `E,N`；返回剖面、视线、净空、遮挡 JSON |
| GET | `/api/registration/demo` | 4 对控制点拟合结果、逐点残差、RMS、检查点 RMS、叠加范围 |
| GET | `/api/registration/demo/image.png` | 示例扫描图原始 PNG |
| GET | `/api/registration/demo/overlay.png` | 配准后重采样的半透明叠加 PNG |
| GET | `/api/health` | 健康检查，截图/部署探活使用 |

实现中 DEM、等高线、晕渲 PNG 与配准叠加均进程内缓存；首次请求做计算，
后续请求直接复用。`/api/layers` 的等高线数据约 3.5 万个顶点，适合单工程本地
浏览；更大范围应改为矢量瓦片并按视窗加载。

### 9.4 截图

`outputs/webmap_screenshot.png` 为首屏（1440×900，Chromium 无头），
`outputs/webmap_profile_screenshot.png` 为调用 `showProfile('P1','P6')` 后的
剖面页。截图命令可用：

```bash
# 终端 1
.venv/bin/ctrlnet-web --port 8765
# 终端 2：Playwright 已装在 /workspace/venvs/lab 时
/workspace/venvs/lab/bin/python scripts/capture_webmap_screenshots.py
# 可传 --url/--profile-from/--profile-to；脚本不会启动或关闭服务
```

当前网页地图的边界：单工程只读、无工程树/编辑/保存、无 MBTiles/XYZ 矢量
瓦片、无多用户与鉴权；DEM 大范围浏览和 5000+ 要素聚合未实现。

## 10. 影像配准（B3）

### 10.1 六参数仿射模型

`src/ctrlnet/registration.py` 实现像素 `(col,row)` 到工程 `(E,N)` 的六参数仿射：

```text
E = a0 + a1·col + a2·row
N = b0 + b1·col + b2·row
```

像素原点在左上角像素**角点**，`col` 向右、`row` 向下，像素中心为
`(col+0.5, row+0.5)`。至少 3 对控制点；超过 3 对时按最小二乘求解，支持
逐点相对权（内部取 `sqrt(w)`）。求解前把像素坐标中心化并归一化，用 SVD
检查退化：若 `σ_min/σ_max < 1e-9`，判定为共线/近共线并抛出
`RegistrationError`。检查点不参与参数求解，单独报告 RMS 与最大误差。

主要 API：

```python
from ctrlnet import (
    ControlPoint,
    register_affine,
    register_image,
    read_world_file,
    write_world_file,
)

points = [
    ControlPoint(col, row, E, N, label="P1"),
    # ≥3 对，建议覆盖测区四角与内部
]
result = register_affine(points, check_points=[])
print(result.transform.to_tuple())   # (a,b,c,d,e,f)
print(result.rms, result.rms_e, result.rms_n, result.max_residual)
print(result.as_dict())              # 参数、逐点 ΔE/ΔN/平面残差、检查点 RMS

# PNG → scan.pgw；GeoTIFF → scan.tfw；仅写文件时无需 Pillow
write_world_file("scan.png", result.transform)
register_image("scan.tif", points, write_world=True)
print(read_world_file("scan.tfw").to_tuple())
```

世界文件使用标准 6 行：`A,D,B,E,C,F`，其中 `C/F` 是左上角**像素中心**坐标，
即 `C=c+0.5(a+b)`、`F=f+0.5(d+e)`；`read_world_file` 会反算回角点仿射。
PNG 对应 `.pgw`，`.tif/.tiff` 对应 `.tfw`，JPEG/BMP/GIF 也有默认扩展名。
CRS 不写入世界文件，需由工程/`.prj` 另行保存。

### 10.2 网页 4 点配准演示

`scripts/make_scan_sample.py` 从真实 DEM 生成 `data/sample/scan_sample.png`
（780×820，约 1.4 MB）：晕渲 + 50 m 等高线 + 图廓/格网，模拟无地理参考的
扫描地形图。生成时使用已知仿射

```text
E = 10·col + 1·row + 414400
N = -0.8·col − 12·row + 4427200
```

但演示配准只使用 `data/sample/registration_demo.json` 中的 4 对同名点
（P1/P2/P6/P7）和少量模拟像素量测噪声（±0.3～0.4 px），另有 P3/P4 作为
独立检查点。当前结果：

- 4 个控制点拟合 6 参数，控制点平面残差 RMS **2.770 m**；
- 逐点残差约 P1 1.28 m、P2 4.27 m、P6 3.28 m、P7 0.28 m；
- 独立检查点 RMS **4.594 m**，大于控制点 RMS，符合检查点不参与拟合的预期；
- 后端用拟合参数把扫描图反算到正北向 E/N 网格，NoData/图外透明，前端以
  `opacity≈0.48` 叠加；页面同时显示控制点/检查点符号与残差。

网页上的“重新载入示例扫描图”按钮只重新执行 `register_affine` 与重采样，
不改变工程数据；这是配准演示，不是完整的影像导入/裁切/持久化流程。

### 10.3 测试覆盖

`tests/test_registration.py` 覆盖：已知仿射在浮点精度内恢复、加噪数据 RMS
落在合理区间、少于 3 点与共线/重复点报错、权重非法报错、PNG 配准并输出
`.pgw`、GeoTIFF 世界文件 `.tfw` 的写入/读取往返。`tests/test_webmap.py`
覆盖配准演示 API 的参数数量、RMS、检查点、叠加 PNG 与前端离线资源。

## 11. 粗差探测与稳健估计（C1）

### 11.1 快速开始

```python
from ctrlnet import (
    data_snooping,
    estimate_network,
    igg3_estimate,
    section13_added,
    simulate_observations,
)

scenario = section13_added()
dataset = simulate_observations(
    scenario.network,
    seed=30,
    blunders={"CD": 10.0},       # 在 CD 上注入 10σ 粗差
)
approx = {"C": (0.32, 100.28), "D": (99.74, 100.31)}

ls = estimate_network(dataset, approximate=approx)     # 高斯-牛顿 LS
snoop = data_snooping(dataset, approximate=approx)     # Baarda w 迭代剔除
robust = igg3_estimate(dataset, approximate=approx)    # IGG-III

print(ls.max_deviation_mm(), ls.iterations)
print(snoop.removed_labels)                             # ['CD']
print(robust.outlier_labels, robust.observation_weight("CD"))
```

`simulate_observations` 支持 `Network`（距离/方向/角度/GNSS 2D）和
`LevelingNetwork`；`blunders` 的键可为观测序号、标签或观测对象，值默认按
`k·σ` 解释，也可用 `BlunderSpec(..., unit="absolute")` 指定绝对单位。
`estimate_network(..., approximate=...)` 对平面网从近似坐标做高斯-牛顿迭代，
对水准网做线性迭代；`datum` 支持固定/加权基准，水准自由网暂不支持。

### 11.2 数据探测与整体检验

- `data_snooping(dataset, test="w")`：σ0 已知的 Baarda w 检验，默认临界值
  **3.29**（α0=0.001 双侧），每轮只剔除 `|w|` 最大的观测，返回所有轮次；
- `data_snooping(dataset, test="tau")`：σ0 未知时的 Pope τ 检验，默认临界值取
  对应自由度的 t 分布分位数；
- `global_model_test(result)`：χ² 整体模型检验，统计量 `vᵀPv/σ0²`，返回
  自由度、p 值、临界值与是否通过；
- `chi2_sf`/`chi2_critical`/`t_critical` 为纯 Python 分布函数，避免新增 scipy
  依赖。

### 11.3 Huber 与 IGG-III

`robust_estimate(dataset, method="huber"|"igg3")` 使用迭代重加权最小二乘：

- 标准化残差 `z_i = v_i/sqrt(diag(Qv0))`，其中 `Qv0` 为先验权下的残差协方差；
- 尺度 `s = 1.4826·MAD(z)`，`u_i = z_i/s`；
- Huber：`|u|≤c` 原权，否则 `c/|u|`，默认 `c=1.345`；
- IGG-III：`|u|≤k0` 原权，`k0<|u|≤k1` 降权，`|u|>k1` 淘汰，
  默认 `k0=1.5`、`k1=3.0`。

结果对象提供 `weight_factors`、`observation_weight_factors`、`outlier_labels`、
`robust_scale`、`converged` 与迭代历史。稳健估计降低粗差影响，但不能替代
设计阶段 `r_i`/MDB/外部可靠性；小样本下仍可能出现遮蔽或淹没。

### 11.4 演示结果

`scripts/run_robust_demo.py` 在第 13 节增补网的 CD 距离注入 10σ 粗差，输出：

- `outputs/blunder_detection.png`：初始/剔除后 `|w|`、IGG-III 权因子、坐标偏差；
- `outputs/robust_results.md` / `.csv`：LS、剔除后 LS、Huber、IGG-III 对比。

本仓库固定种子 `30` 的实测：LS 最大点位偏差约 2.06 mm，剔除后 LS 与 IGG-III
约 1.56 mm，Huber 约 1.52 mm；无粗差参考解约 1.57 mm。同一网中 CD 的
`r_i≈0.90`，10σ 粗差 |w|≈9.0；角度 `r_i` 仅 0.04～0.08，同样 10σ 的 |w| 约
2.0～2.9，低于 3.29，说明小 `r_i` 观测的粗差更难发现。

## 12. 目录结构

```text
ctrlnet-design/
├── docs/                      # 原始方案、重设计方案、摘要
├── src/ctrlnet/
│   ├── model.py               # 点、距离、方向、角度、GNSS 基线、网、方案
│   ├── design.py              # 参数索引、设计矩阵、白化
│   ├── datum.py               # 固定/加权/最小/自由基准
│   ├── adjustment.py          # SVD 求解、秩诊断、协方差
│   ├── precision.py           # mp、误差椭圆、边相对精度
│   ├── reliability.py         # 平面网 r_i、MDB、外部可靠性、w 检验
│   ├── robust.py              # 模拟观测、w/τ/χ²、Huber/IGG-III 稳健估计
│   ├── leveling.py            # 1D 水准/高程网、三角高程、高程可靠性、路线图
│   ├── terrain.py             # DEM 采样/剖面/通视/晕渲/等高线
│   ├── registration.py        # 六参数仿射、残差/RMS、世界文件
│   ├── webmap/                # 本地 FastAPI 服务 + 离线 Leaflet 页面
│   │   ├── app.py             # /api/project、/api/layers、/api/profile 等
│   │   ├── state.py           # 工程/DEM/图层/配准叠加缓存
│   │   ├── render.py          # 晕渲 PNG、等高线 GeoJSON、影像重采样
│   │   └── static/            # index.html、app.js、style.css、leaflet/
│   ├── compare.py             # 方案对比
│   ├── optimize.py            # 贪心增补与局部搜索
│   ├── plot.py                # 网图与椭圆
│   ├── report.py              # 中文表格
│   └── examples.py            # 第 13 节两方案
├── tests/                     # 黄金回归、秩/异常、优化、DEM、配准、Web API
│   ├── test_terrain.py        # 合成 DEM 插值/通视/曲率折光/晕渲
│   ├── test_robust.py         # 模拟观测/高斯-牛顿/粗差探测/稳健估计
│   ├── test_registration.py   # 仿射恢复/噪声/共线/世界文件
│   └── test_webmap.py         # FastAPI TestClient 与离线静态资源
├── scripts/
│   ├── run_demo.py            # 平面网演示主脚本
│   ├── run_leveling_demo.py   # 水准/三角高程演示
│   ├── run_robust_demo.py     # C1 粗差探测与稳健估计演示
│   ├── fetch_dem.py           # 下载/裁剪 Copernicus GLO-30 小样本
│   ├── run_terrain_demo.py    # DEM 通视 + 地形 + 误差椭圆演示
│   ├── make_scan_sample.py    # 生成示例扫描图 + 配准控制点
│   ├── capture_webmap_screenshots.py  # Playwright 无头截图
│   └── build_notebook.py      # 由脚本生成 notebook
├── data/
│   ├── cache/                 # DEM 原始大文件（gitignore）
│   └── sample/
│       ├── dem_sample.tif     # 289×374、30 m 裁剪样本（约 0.3 MB）
│       ├── dem_sample.json    # 来源/CRS/垂直基准/范围/校验和
│       ├── terrain_project.json  # 网页地图示例工程
│       ├── scan_sample.png    # 780×820 示例扫描地形图（约 1.4 MB）
│       └── registration_demo.json  # 4 控制点 + 2 检查点 + 已知仿射
├── notebooks/demo.ipynb       # 已执行的演示 notebook
├── outputs/                   # 图件、CSV、网页截图、results.md（提交）
├── pyproject.toml
├── requirements.txt
└── README.md
```

## 13. 计算约定与限制

- 设计态接口（`solve`）：`σ0=1`，`Cx=(AᵀQl⁻¹A)⁺`，不估计单位权方差。
  实测模拟接口（`estimate_network`/`robust_estimate`）另行计算残差、σ̂0、
  w/τ 统计量与稳健权因子，两者不要混用。
- 距离先验方差：`σ²=a²+(b·10⁻⁶·s)²`；角度/方向标准差按角秒输入，内部转弧度。
- 标准误差椭圆不乘置信系数（约 39.35%）；95% 椭圆乘
  `k=sqrt(χ²(2,0.95))=sqrt(-2ln0.05)≈2.4477`。
- `r_i` 对独立观测为 `1-h_ii`；GNSS 2×2 基线按块内对角元求和。`trace(R)=n-rank`。
- MDB 默认 `λ0=7.849`（α=0.05 双侧，power=0.80）；外部可靠性取 MDB 引起的
  **最大单个坐标分量绝对值**（mm），同时保留向量范数。
- 固定点协方差为 0；自由网/最小约束使用 Moore–Penrose 伪逆，`Cx` 与所选基准
  相关，不能与固定基准结果直接比较。
- 加权基准通过坐标伪观测实现，伪观测行进入 `Ql`，默认不计入观测可靠性列表。
- 高程网固定点方差为 0；加权约束点保留参数并进入 `Cx`。自由网使用
  Moore–Penrose 伪逆，`Cx` 与基准选择相关，但相对高差精度与整体平移无关。
- 高程网默认 `auto` 会把非固定点的 `sigma_H` 作为加权约束；若只想使用固定点，
  显式传 `datum="fixed"`；显式 `datum="weighted"` 时没有任何 `sigma_H` 会报错。
- 三角高程单向观测的曲率/折光改正为正值（k=0.13 时 `S=1000 m` 约 0.0683 m）；
  对向观测取均值、正常高/大地高转换与 geoid 协方差尚未实现。
- DEM 通视使用与三角高程一致的 `(1−k)x(d−x)/(2R)` 模型；`k` 随气象变化，
  长边应做敏感性分析。30 m DSM 无法反映围墙、电杆、树木、车辆等小障碍，
  NoData 或 DSM 地物不确定时输出 `unknown`，不得直接判为通视。
- DEM 样例采用局部 UTM 50N，只适用于本测区；未实现投影尺度/子午线收敛角的
  全链路 grid/ground 归算、跨带处理与 geoid 改正。
- C1 实测模块以“先验 σ 已知、σ0=1”为默认；w 检验临界值 3.29 对应
  α0=0.001 双侧，τ 检验默认 t 分位数。稳健估计使用先验权下的标准化残差
  与 MAD 尺度；IGG-III 淘汰的观测权因子为 0，但其结果仍不能替代 MDB 报告。
- 当前平面部分仅支持二维网；GNSS 只实现二维基线（2×2 协方差）；未实现
  3D 联合、数据库、多工程与编辑。
- 网页地图只绑定回环地址，无鉴权、只读单工程；扫描图配准为 6 参数仿射，
  未实现多项式/TPS/RPC、影像裁切持久化与任意客户端旋转 warp。
- MBTiles/矢量瓦片/在线底图未实现；当前 DEM 以单张 imageOverlay 叠加，
  大范围浏览需改为按视窗渲染的 XYZ 瓦片。
