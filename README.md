# ctrlnet — 平面/高程控制网精度估算与优化设计（MVP 计算核心）

`ctrlnet` 是一个纯 Python 的平面/高程控制网**设计态（先验）**计算核心，并附带
可选的本地只读网页地图（FastAPI + 离线 Leaflet），
实现 [`docs/redesign_plan.md`](docs/redesign_plan.md) 中“平面控制网精度估算与优化
设计”重设计方案的 MVP、P1–P5 部分能力与 C1–C4 增量：

- 平面网：距离、方向、角度、二维 GNSS 基线、坐标伪观测；
- GNSS 三维基线网：WGS84 大地坐标/ECEF/局部 ENU、3×3 基线协方差、固定/最小
  约束、水平/垂直/三维精度、基线相对精度与 `r_i`/MDB；
- GNSS + 地面边角 + 水准联合平差（局部 ENU 切平面近似）；
- 高程异常 ζ=h−H 的常数/平面拟合、参数协方差与残差，可选 EGM96 格网插值；
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
- 方案对比、贪心/局部搜索/精确分支定界观测优化（A/D/E/max_mp/最弱边），
  支持观测成本 + 测站首次使用固定成本，并提供 SciPy MILP 线性代理近似；
- 第 13 节黄金算例的精度与可靠性回归；
- 生成网图、对比图、可靠性图、优化过程图、水准路线图、地形图、CSV 与中文报告；
- SQLite 工程库（`store.py`）：`projects / points / observations / scenarios /
  snapshots / results`，方案版本号与父方案、规范化 JSON 快照 + SHA-256
  `input_hash`、按哈希缓存计算结果；
- 设计报告（`reportgen.py`）：工程概况、点/观测清单、先验精度模型、基准、
  点位精度与误差椭圆、边相对精度、可靠性、方案对比、优化建议、通视结果与图表，
  输出 Markdown / 自包含 HTML / 可选 DOCX（pandoc）；
- 网页方案切换与报告下载：第 13 节基准/增补、DEM 全部通视边/优化方案，
  切换后刷新点、观测、椭圆与统计；`/api/report` 返回 HTML/Markdown/DOCX。
- 论文第 3–5 章约定（`thesis.py`）：CGCS2000/WGS84 3° 带高斯正反算、
  椭球面距离/方位、表 3-1 等级、σS=a+bS 线性测距先验、测角网 P=I 的
  mm²/(″)² 精度估算、误差椭圆、坐标/角度拓扑文本导入导出；
- 论文算例复现（`thesis_examples.py`）：算例 1 的 Qxx/Qyy/最弱点、图 5-7
  边长分母反推，算例 2 的近似 Qxx/Qyy；网页数据在
  `data/sample/thesis_example1.json`、`thesis_example2.json`。

数值约定：内部长度/高程单位为米、角度/方向为弧度；显示时距离/高差用 mm，
角度用角秒。DEM 计算使用米制局部 UTM 坐标。项目以设计阶段先验精度估算为主，
C1 起补充实测模拟观测的平差、粗差探测与稳健估计；C3 起支持 GNSS 三维基线
向量网、局部 ENU 联合平差与高程异常平面拟合（可选 EGM96 格网插值），但
高程异常仍是**局部近似**，不是全国/高精度 geoid 模型。C4 起提供单工程只读
SQLite 持久化、快照/结果缓存与报告下载，但尚未实现多工程编辑、并发写入与
权限管理。

## 1. 与 docs 方案的对应关系

| 重设计方案 | 本仓库实现 | 状态 |
|---|---|---|
| §5.3 基准与秩：固定/加权/最小约束/自由网 | `datum.py`、`adjustment.py`；SVD 秩、零空间诊断、伪逆 | ✅ MVP |
| §5.4 可靠性：`Qv`、`R`、`r_i`、MDB、外部可靠性、w 检验 | `reliability.py`；λ0 用 `statistics.NormalDist` 精确计算，默认 7.849 | ✅ MVP |
| §5.10 粗差探测与稳健估计：模拟观测、w/τ/χ²、Huber/IGG-III | `robust.py`；高斯-牛顿、迭代 snooping、IRLS、MAD 尺度 | ✅ P1/C1 |
| §5.5 精度：`mp`、误差椭圆、边长相对精度、最弱点/边 | `precision.py`；标准椭圆与 95% 椭圆，`k=sqrt(-2ln0.05)` | ✅ MVP |
| §5.6 优化：贪心、预算/阈值、A/D/E 最优、最弱边、MICP/MILP | `optimize.py`；贪心 + 1 换 1 局部搜索；≤20 候选的分支定界/穷举精确解；SciPy MILP 线性代理 | ✅ C2 |
| §5.9 水准/高程网：路线/环、`σ_km`、固定/加权/自由基准、`r_i`/MDB | `leveling.py`；1D 设计矩阵、SVD、伪逆、相对高差精度 | ✅ P1/B1 |
| §5.9.5 三角高程：斜距/平距、天顶距、曲率折光、误差传播 | `leveling.py`；解析偏导与逐项误差贡献 | ✅ P1/B1 |
| §5.2 坐标与投影：局部 UTM、经纬度↔米制转换 | `fetch_dem.py`、`terrain.py`；样例重投影到 EPSG:32650 | ✅ P1/B2（局部） |
| §5.7 DEM 通视：双线性采样、剖面、曲率/折光、四态判定 | `terrain.py`；`DEM`、`profile`、`intervisibility` | ✅ P1/B2 |
| §5.7 地形渲染：晕渲、等高线 | `terrain.py`；`hillshade`、`contours` | ✅ P1/B2 |
| §5.2.7 地图/地形图配准：6 参数仿射、控制/检查点、残差 RMS | `registration.py`；`register_affine`/`register_image`、世界文件 | ✅ P1/B3 |
| §4 数据模型：Project/Point/Observation/Scenario/Snapshot/Result | `store.py`；SQLite 六表、方案版本/父方案、规范化快照与结果缓存 | ✅ C4（单工程只读） |
| §7 接口：图层、剖面、晕渲、配准、报告资源 | `webmap/app.py`；FastAPI `/api/scenarios`、`/api/scenario/{id}`、`/api/report` 等 | ✅ C4（只读单工程） |
| §8 界面：地图、图层、属性、剖面图、方案切换、报告 | `webmap/static/`；Leaflet `CRS.Simple` + SVG 剖面 + 方案下拉 + 报告按钮 | ✅ C4（演示级） |
| §10.2 第 13 节黄金回归 | `examples.py`、`tests/test_section13.py` | ✅ 全部通过 |
| §10.3 水准模块验证：闭合差、秩 1、`Σr_i`、三角高程公式 | `tests/test_leveling.py` | ✅ 全部通过 |
| §10.3 DEM 模块验证：平面/斜面/山脊、曲率折光、插值、晕渲 | `tests/test_terrain.py` | ✅ 全部通过 |
| 数据模型（点、观测、网、方案） | `model.py`；不可变计算入口，直接构造 `Network`/`Scenario` | ✅ MVP |
| 工程持久化 / 快照 / 结果缓存 | `store.py`；SQLite、`input_hash`、`get_or_compute_result` | ✅ C4 |
| 报告与图件 | `report.py`（文本表）、`reportgen.py`（Markdown/HTML/DOCX）、`plot.py`、`scripts/run_demo.py` | ✅ C4 |
| 地图/离线底图/MBTiles、扫描图配准 | `webmap/` 的单工程 DEM imageOverlay、扫描图配准与半透明叠加；MBTiles/矢量瓦片未实现 | ⚠️ 部分（B3） |
| GUI、工程树、地图选点、交互编辑 | 本地只读网页地图：图层开关、点/线点击、两点剖面；无工程树与编辑 | ⚠️ 部分（B3） |
| FastAPI/数据库/工程包/快照持久化 | `store.py` + `webmap/app.py`：SQLite 单工程、方案快照/结果缓存；工程包（zip/manifest）、多工程写入、迁移框架未实现 | ⚠️ 部分（C4） |
| 投影归算全链路（投影尺度、子午线收敛角、跨带） | 仅实现局部 UTM 与 DEM 采样；未做 grid/ground 全链路归算 | ⚠️ 部分 |
| §5.2 GNSS 三维 ECEF/ENU、局部切平面 | `gnss.py`；WGS84 自实现转换、ENU 原点与旋转 | ✅ C3 |
| §5.8 GNSS 基线网：3×3 VCV、固定/最小约束、基线相对精度 | `gnss.py`；ECEF 平差、ENU 基线旋转、Cholesky 白化、复用可靠性 | ✅ C3 |
| §5.8/§5.9 联合平差：GNSS + 距离/角度 + 水准 | `gnss.py`；同一 3D 参数集、局部 ENU、ζ 改正 | ✅ C3（局部近似） |
| §5.9.4 高程异常/geoid、GNSS 大地高→正常高 | `gnss.py`；ζ 常数/平面拟合、参数协方差、可选 EGM96 插值 | ⚠️ 近似（C3）；无高精度 geoid/方差场 |
| 跨基线相关完整 VCV、Helmert、LandXML | 仅逐基线 3×3；未实现跨基线块与七参数 | ❌ 未实现 |
| 方差分量估计（VCE） | 未实现 Helmert/最小范数二次无偏估计 | ❌ 未实现 |
| MICP/MILP/Pareto、A/D/E 精确最优 | A/D/E/max_mp/最弱边的精确分支定界（≤20 候选）与 MILP 线性代理；Pareto 前沿未实现 | ✅ C2（小规模精确） |

## 2. 安装

要求 Python ≥ 3.9。运行时依赖 `numpy>=1.24`、`matplotlib>=3.6`；`test` extra
提供 `pytest`、`httpx`、`fastapi`、`pillow`、`rasterio`、`scipy`，`opt` extra
提供 SciPy MILP（`scipy>=1.11`），`demo` extra 提供
`ipykernel`、`nbconvert`、`nbformat`，`terrain` extra 提供 `rasterio`，
`webmap` extra 提供 FastAPI/uvicorn/pillow/rasterio。

```bash
cd /workspace/ctrlnet-design
python3 -m venv .venv
.venv/bin/pip install -e ".[test,demo,terrain,webmap]"  # 只跑测试可改用 ".[test]"
# 只跑 C2 MILP 演示：.venv/bin/pip install -e ".[opt]"
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
- `tests/test_exact_optimizer.py`：A/D/E/max_mp/worst_rel 五种准则的分支定界
  与穷举目标值一致、精确解不劣于贪心、预算约束、测站首次使用成本、
  多站成本、方向定向参数、MILP 代理预算/真实目标复算；
- `tests/test_robust.py`：固定种子模拟观测、近似坐标高斯-牛顿收敛、χ² 全局检验、
  无粗差无误判、10σ 粗差被 w 检验与 IGG-III 定位、稳健解接近无粗差解、
  `r_i` 与可控性关系、水准/GNSS 2D/方向观测接口；
- `tests/test_leveling.py`：单路线 `σ_km·sqrt(L)` 与测站数随机模型、闭合环/
  附合路线解析 `Cx`、`Σr_i=冗余数`、无基准秩亏、自由网最小约束、加权高程约束、
  三角高程公式/球气差/斜距-平距等价/误差传播有限差分、`height_type` 属性；
- `tests/test_gnss.py`：大地坐标↔ECEF↔ENU 往返 <1e-6 m、已知 ENU 数值、
  协方差旋转迹/特征值不变、纯 GNSS 网 `Cx` 与解析法方程一致、ENU 基线旋转、
  自由网 3 平移零空间、联合平差加入地面观测后 `Cx` 不变差、ζ 平面参数恢复、
  EGM96 样本插值；
- `tests/test_terrain.py`：平面/斜面 DEM 的双线性插值精确性、剖面端点与步长、
  平地通视、高斯山脊遮挡、提高仪器高后通视、长距离曲率+折光下沉公式、
  `marginal`/NoData `unknown` 四态、晕渲范围 `[0,1]` 与等高线冒烟测试；
- `tests/test_registration.py`：已知仿射精确恢复、加噪 RMS 合理性、少于 3 点/
  共线/非法权值报错、PNG 配准与 `.pgw`/`.tfw` 世界文件往返；
- `tests/test_store.py`：SQLite 保存/读回往返、规范化 JSON、快照确定性、
  同一 `input_hash` 结果缓存、重新打开数据库结果一致、父方案版本、
  修改/追加观测后哈希变化；
- `tests/test_report.py`：Markdown 12 个章节、HTML base64 自包含、方案对比、
  DOCX（有 pandoc 时）、CLI 与未知方案错误；
- `tests/test_webmap.py`：TestClient 覆盖页面、离线 Leaflet 静态资源、
  `/api/project`、`/api/scenarios`、`/api/scenario/{id}`、`/api/layers` 方案切换、
  `/api/report` HTML/MD/DOCX、晕渲 PNG、通视/遮挡剖面、配准演示与叠加 PNG。

预期结果：`128 passed`（FastAPI TestClient 会提示一条 httpx 弃用警告，不影响结果）。

## 4. 运行演示

```bash
cd /workspace/ctrlnet-design
.venv/bin/python scripts/run_demo.py
.venv/bin/python scripts/run_leveling_demo.py
.venv/bin/python scripts/run_robust_demo.py     # C1 粗差探测与稳健估计
.venv/bin/python scripts/run_optimizer_compare.py  # C2 贪心/局部/精确/MILP 对比
.venv/bin/python scripts/fetch_dem.py          # 可选：重新下载/裁剪 DEM 小样本
.venv/bin/python scripts/run_terrain_demo.py   # B2 DEM 通视与误差椭圆演示
.venv/bin/python scripts/fetch_egm.py          # 可选：下载/裁剪 EGM96 小样本
.venv/bin/python scripts/run_gnss_demo.py      # C3 GNSS 三维基线网 + 联合平差 + ζ 拟合
.venv/bin/python scripts/make_scan_sample.py   # B3 示例扫描图 + 4 对控制点
.venv/bin/python scripts/build_demo_project.py # C4 生成 SQLite 演示工程
.venv/bin/python -m ctrlnet.report \
  --project data/sample/demo_project.sqlite --out outputs/report  # C4 设计报告
.venv/bin/ctrlnet-web                          # C4 本地网页地图（127.0.0.1:8765）
# 或：.venv/bin/python -m ctrlnet.webmap --port 8765
```

`run_demo.py` 打印第 13 节两方案的关键精度/可靠性表，并生成平面网图件、CSV
和中文汇总 `results.md`。`run_leveling_demo.py` 演示 6 点水准网 + 两条三角高程
观测，生成高程点 CSV、中文结果与水准路线图。`run_terrain_demo.py` 在真实
Copernicus GLO-30 子区域上选 7 个高地控制点，做全部 21 对通视分析，并用通视
距离/角度边构网，输出地形图、剖面图、CSV、误差椭圆图与示例工程 JSON。
`run_gnss_demo.py` 用 DEM 演示区 7 点构造 13 条 ENU 三维基线、6 条距离、
4 个水平角与 9 条水准，输出基线/椭圆/垂直精度图、ζ 拟合图、CSV 与中文报告。
`fetch_egm.py` 从公开 PROJ-data 下载 EGM96 15′ 格网并裁剪北京西山小样本。
`make_scan_sample.py` 生成 `data/sample/scan_sample.png` 与 4 对控制点/2 个检查点
元数据；`build_demo_project.py` 把第 13 节两方案与 DEM 全部通视边/优化方案写入
`data/sample/demo_project.sqlite`；`python -m ctrlnet.report` 生成设计报告；
`ctrlnet-web` 启动只绑定回环地址的网页地图，浏览器访问
`http://127.0.0.1:8765/`，可在左栏切换方案并下载报告。

报告生成命令也支持 `--scenario s13-added`（按 id 或名称）、`--title`、
`--confidence`、`--no-docx` 与 `--basename`；默认输出
`outputs/report/design_report.md`、`.html`、`.docx` 与 `assets/*.png`。

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
| `gnss_network.png` | C3 GNSS 基线网、95% 水平椭圆（放大 10 000×）与各点垂直/三维精度 |
| `geoid_fit.png` | C3 ζ 平面拟合残差、ζ 样本/平面/EGM96 对照 |
| `gnss_results.md` | C3 中文报告：GNSS-only vs 联合平差、点位/基线/可靠性/ζ 拟合 |
| `gnss_results.csv` | C3 长表：点、基线、ζ 控制点的精度/相对精度/`r_i`/MDB/残差 |
| `blunder_detection.png` | C1 粗差探测：迭代前后各观测 `|w|`、临界线、IGG-III 权因子与坐标偏差对比 |
| `robust_results.md` | C1 中文汇总：LS/剔除后 LS/Huber/IGG-III 偏差、snooping 轮次、`r_i` 与可控性 |
| `robust_results.csv` | C1 各方法、各待定点的真值/估值/偏差、异常标签与粗差权因子 |
| `optimizer_comparison.png` | C2 第 13 节网与 DEM 通视网在多预算下的目标值/耗时对比（贪心/局部搜索/精确/MILP） |
| `optimizer_comparison.csv` | C2 每次运行的目标、成本、选中观测、耗时、精确标志与分支节点数 |
| `optimizer_comparison.md` | C2 中文对比表、方法汇总、精确/近似说明与限制 |
| `dem_hillshade_contours.png` | 真实 DEM 晕渲 + 50 m 等高线 + 7 个控制点 + 21 对观测线（绿=通视，红=遮挡） |
| `intervisibility_profiles.png` | 6 条代表性剖面：地形、两端连线、曲率/折光视线、遮挡点与最小净空 |
| `intervisibility.csv` | 全部点对的 `status/visible/min_clearance`、遮挡位置、仪器高/目标高、`k/R`、采样数 |
| `dem_network_ellipses.png` | 只用通视距离/角度边的平面网 95% 误差椭圆叠加在晕渲图上（图题注明放大倍数） |
| `webmap_screenshot.png` | C4 本地网页地图首屏：方案下拉、报告按钮、DEM 晕渲/等高线、全部通视边与椭圆 |
| `webmap_scenario_screenshot.png` | C4 切换到“DEM 优化方案（预算 12）”后：点/观测/椭圆/统计刷新 |
| `webmap_profile_screenshot.png` | B3 网页剖面：P1→P6 地形线、曲率折光视线、遮挡点与净空（历史截图） |
| `report/design_report.md` | C4 设计报告 Markdown：工程概况、点/观测、精度、椭圆、边、可靠性、对比、建议、通视、图表 |
| `report/design_report.html` | C4 自包含 HTML（PNG 以 base64 内嵌，可离线打开） |
| `report/design_report.docx` | C4 DOCX（本机 pandoc 转换；失败自动跳过） |
| `report/assets/design_network.png` | 报告网图与 95% 误差椭圆 |
| `report/assets/design_reliability.png` | 报告可靠性 `r_i` 柱状图与 0.1/0.3 阈值线 |
| `report/assets/design_scenario_comparison.png` | 报告方案对比：各方案最大点位中误差 |
| `report/assets/design_visibility.png` | 报告通视最小净空图（通视绿/遮挡红） |

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
- `height_type` 只记录 `normal`/`orthometric`/`ellipsoidal` 等属性；B1 本身
  **不**把 GNSS 大地高换算为正常高。C3 的 `fit_height_anomaly` 提供局部
  ζ 平面近似，可做转换并传播拟合参数协方差，但不是高精度 geoid 模型。

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

## 9. 本地网页地图与方案切换（C4）

### 9.1 启动与安全边界

网页地图是**只读单工程演示**，数据来自 `data/sample/demo_project.sqlite`，
不写回工程、不需要账号，也不应暴露到公网。服务只允许绑定回环地址
（默认 `127.0.0.1:8765`），启动入口有两个：

```bash
cd /workspace/ctrlnet-design
.venv/bin/pip install -e ".[test,webmap]"
.venv/bin/python scripts/build_demo_project.py   # 可选：重建 SQLite 演示工程

.venv/bin/ctrlnet-web --port 8765
# 等价：.venv/bin/python -m ctrlnet.webmap --port 8765
# 指定其他 SQLite 工程：--project /path/to/demo_project.sqlite
# 也可用环境变量 CTRLNET_DB
```

浏览器访问 `http://127.0.0.1:8765/`。`--host` 仅接受 `127.0.0.1`、`localhost`
和 `::1`；传入公网地址会直接拒绝启动。FastAPI 的 OpenAPI 文档在
`/api/docs`，页面本身不依赖外部 CDN 或在线底图。

前端 Leaflet 1.9.4 的 JS/CSS/图标已放在
`src/ctrlnet/webmap/static/leaflet/`（含 MIT LICENSE），随 wheel 一起打包；
页面只请求本机 `/static`、`/api` 和本机 PNG，不访问 `unpkg`、Google Fonts
或任何瓦片服务，因此断网可用。

### 9.2 方案切换、页面与图层

`demo_project.sqlite` 包含四个方案：

| 方案 id | 名称 | 内容 |
|---|---|---|
| `s13-base` | 第 13 节基准方案 | A/B 固定、C/D 待定，5 距离 + 2 角度；几何与黄金算例一致，仅整体平移到 DEM 范围 |
| `s13-added` | 第 13 节增补方案 | 父方案 `s13-base`，增加角 D-C-A |
| `dem-all` | DEM 全部通视边 | 7 点，16 条通视距离 + 60 个通视水平角（76 观测） |
| `dem-opt` | DEM 优化方案（预算 12） | 全部 16 条通视距离 + 9 个优化选出的通视角度（25 观测） |

左栏“方案切换”下拉框调用 `/api/scenario/{id}` 与 `/api/layers?scenario=`，
切换后重新绘制控制点、观测线、误差椭圆、左上统计与方案元数据（观测数、
max mp、min r_i、通视对数、冗余数、父方案、快照哈希），并把视图缩放到该方案
点集。顶部“下载报告”按钮按当前方案下载 HTML，旁边 MD/DOCX 提供其他格式。

页面采用 Leaflet `CRS.Simple`，直接把样板 DEM 的 UTM 50N 米制 `(E,N)` 作为
地图坐标，避免在浏览器里重复做投影。图层顺序与方案 §8 一致
（底图→地形→控制网→结果）：

| 图层 | 来源/样式 | 交互 |
|---|---|---|
| DEM 晕渲 + 分层设色 | `terrain.hillshade` + 高程调色板，后端渲染为 PNG imageOverlay | 透明度/开关 |
| 等高线 | `contours()` 提取 50 m 等高线，输出 GeoJSON LineString；每 5 条加粗 | 开关 |
| 观测线 | 方案距离（通视绿/遮挡红/无通视蓝）、角度两条蓝色虚线射线、未作为设计观测的遮挡检查线 | 点击显示平距、净空、遮挡点、r_i/MDB 或角度值 |
| 95% 误差椭圆 | 以 `ellipse_95` 的 a/b/方位角生成多边形；放大倍数按方案网形范围自适应 | 点击显示半轴 mm、方位角、置信度与放大倍数 |
| 控制点 | 固定点三角形、待定点空心圆，永久点名标签 | 点击显示 E/N、经纬度、DEM 高程、σE/σN、mp、椭圆 |
| 配准影像 | 后端按 4 点仿射重采样后的半透明 RGBA PNG | 开关；控制点/检查点有独立符号与残差提示 |

页面点击地图两点即可请求 `/api/profile`，右侧绘制 SVG 剖面：地形填充、
两端连线、曲率/折光视线、红色遮挡点、最小净空和采样数。也可以点击观测线
查看同一信息；`P1→P6` 为遮挡示例（最小净空约 −51.31 m）。

### 9.3 本地 API

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/project?scenario=` | 工程/方案元数据、点、观测、通视、统计、快照哈希与 API 入口 |
| GET | `/api/scenarios` | 方案列表：id、名称、版本、父方案、观测数 |
| GET | `/api/scenario/{id}` | 单方案详情：点精度/椭圆、观测/可靠性、通视、统计 |
| GET | `/api/layers?scenario=` | 图层清单；等高线/观测线/椭圆/控制点以 GeoJSON 内联返回 |
| GET | `/api/overlay/hillshade.png` | DEM 晕渲 + 分层设色 PNG（NoData 透明） |
| GET | `/api/profile?from=&to=` | `from`/`to` 可点名（如 `P1`）或 `E,N`；返回剖面、视线、净空、遮挡 JSON |
| GET | `/api/report?scenario=&format=` | 设计报告：`html`（自包含，默认）、`md`、`docx`；带下载文件名 |
| GET | `/api/report.md?scenario=` | Markdown 报告快捷入口 |
| GET | `/api/report.docx?scenario=` | DOCX 报告快捷入口（pandoc 不可用时 503） |
| GET | `/api/registration/demo` | 4 对控制点拟合结果、逐点残差、RMS、检查点 RMS、叠加范围 |
| GET | `/api/registration/demo/image.png` | 示例扫描图原始 PNG |
| GET | `/api/registration/demo/overlay.png` | 配准后重采样的半透明叠加 PNG |
| GET | `/api/health` | 健康检查，截图/部署探活使用 |

实现中 DEM、等高线、晕渲 PNG、方案图层与报告均进程内缓存；结果由
`get_or_compute_result` 按 `input_hash` 从 SQLite `results` 表读取。首次请求
做计算，后续直接复用。`/api/layers` 的等高线数据约 3.5 万个顶点，适合单工程
本地浏览；更大范围应改为矢量瓦片并按视窗加载。

### 9.4 截图

`outputs/webmap_screenshot.png` 为首屏（1440×900，Chromium 无头），显示
方案下拉与“下载报告”按钮；`outputs/webmap_scenario_screenshot.png` 为切换到
`dem-opt` 后的方案页。截图命令可用：

```bash
# 终端 1
.venv/bin/ctrlnet-web --port 8765
# 终端 2：Playwright 已装在 /workspace/venvs/lab 时
/workspace/venvs/lab/bin/python scripts/capture_webmap_screenshots.py
# 可传 --url/--scenario；脚本只访问 127.0.0.1，不启动或关闭服务
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

## 12. 观测方案优化（C2）

### 12.1 统一准则与成本模型

`optimize`/`greedy_optimize`/`local_search_optimize`/`exact_optimize` 使用同一
`criterion` 接口：

| 准则 | 目标 | 说明 |
|---|---|---|
| `A` | `min trace(Cx)` | A 最优；可用 `parameter_scales` 做尺度归一化 |
| `D` | `min log det(Cx)` | D 最优；对非奇异参数缩放不变 |
| `E` | `min lambda_max(Cx)` | E 最优；最坏方向方差最小 |
| `max_mp` | `min max_i mp_i` | 直接对应点位验收指标 |
| `worst_rel` | `min max_e (σ_s/s)_e` | 最弱边相对精度 |

旧参数 `objective="trace"/"relative"` 仍作为别名保留，等价于 `A`/`worst_rel`。

成本由观测成本和测站固定成本组成：

```text
total = Σ c_e x_e + Σ_s f_s · [第 s 个测站在候选集首次被使用]
```

- `Candidate(observation, cost=..., stations=...)`：`stations` 为空时，角度/方向
  取测站，距离/GNSS 取全部引用点；显式传入可精确控制设站集合；
- `CostModel(station_costs={"C": 100, ...}, default_station_cost=0)`：
  按点名给固定成本；
- `exact_optimize(..., station_costs=...)` 可直接传数字（所有站统一）或映射；
- 默认按候选集合内“首次使用”计费，不自动扣除基准网已使用的测站；若要把
  基准网既有测站视为已建，传 `existing_stations={"A", "B"}` 或构造
  `CostModel(existing_stations=...)`。

### 12.2 精确分支定界

`exact_optimize(base, candidates, criterion="A", budget=...)` 对候选数 ≤ 20
（`max_candidates` 可调）求预算约束下的**全局最优**：

- 预先组装 `N(x)=N0+Σx_e a_e a_eᵀ/σ_e²`，候选子集只需矩阵加法；
- 分支定界以“加入全部剩余观测后的目标值”为单调下界。增加独立观测不会使
  `Cx` 变差，因此若下界已不优于当前最优，可安全剪枝；
- 同时维护预算、测站首次使用掩码和距离边掩码；
- 对方向观测引入新定向未知数、导致 `Cx` 维数变化时，A/D/E 自动关闭该下界，
  退化为带预算剪枝的精确枚举，仍保证最优；
- `exhaustive_optimize` 穷举全部预算可行子集，用于小例子交叉验证；
- 若达到 `time_limit`，结果 `exact=False` 并明确标注未证明最优。

```python
from ctrlnet import Angle, Candidate, exact_optimize, section13_base

base = section13_base()
candidates = [
    Candidate(Angle("D", "C", "A"), 1.0, stations=("C",)),
    Candidate(Angle("A", "C", "B"), 1.0, stations=("C",)),
    Candidate(Angle("D", "A", "C"), 1.0, stations=("A",)),
]
result = exact_optimize(
    base, candidates, criterion="max_mp", budget=7.0,
    cost_model=None, station_costs={"A": 2.0, "C": 5.0},
)
print(result.selected_labels, result.spent, result.objective_value)
print(result.to_text())
```

精确解要求基准网满秩（存在可平差的初始方案），并支持固定基准和加权基准；
自由网/最小约束的伪逆协方差不满足“正规矩阵直接求逆”的假设，仍建议用贪心或
局部搜索。若所选候选子集无法使网形满秩，精确搜索会返回不可行/报错，而不是
伪造一个有限目标值。

### 12.3 MILP 线性代理（近似）

`milp_optimize(..., criterion=...)` 基于 SciPy HiGHS 建立 0-1 MILP：

- `max_mp`：对每个候选计算它对各点 `mp` 的一阶改善量，约束
  `z ≥ mp_p(0) − Σ gain_{p,e} x_e`，最小化 `z`；
- `worst_rel`：对每条候选/基准边做同样的一阶最弱边代理；
- `A/D/E`：以候选单条加入时的标量目标改善量作为线性收益，做预算背包；
- 预算行同时包含观测成本与测站 0-1 变量；设站首次使用成本只计一次；
- 求解后一律用 `solve`+`analyze_precision` 真实目标复算，并做 1 加/1 换 1
  局部搜索校正。结果对象 `exact=False`、`proxy_objective` 为代理目标值。

该方法是**近似**，不保证全局最优；若没有 SciPy，调用会提示安装
`pip install -e ".[opt]"`，其余方法不受影响。

### 12.4 演示与结果

`scripts/run_optimizer_compare.py` 对第 13 节网（10 个候选角）和
DEM 通视网（基准 14 条通视距离 + 14 个通视候选）在多个预算下比较：

- 贪心；
- 贪心 + 1 换 1 局部搜索；
- 精确分支定界（`max_mp`，预算约束下证明最优）；
- SciPy MILP 线性代理（可用时）。

输出：

- `outputs/optimizer_comparison.png`：每个网的目标值—预算、耗时—预算曲线；
- `outputs/optimizer_comparison.csv`：每次运行的目标、成本、选中观测、耗时、
  精确标志和分支节点数；
- `outputs/optimizer_comparison.md`：中文对比表、方法汇总、精确/近似说明。

`tests/test_exact_optimizer.py` 验证：小例子穷举 = 分支定界；精确目标 ≤ 贪心；
预算约束；同站/多站首次使用成本；五种准则；方向定向参数；MILP 真实目标复算。

## 13. 目录结构

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
│   ├── gnss.py                # C3 WGS84/ECEF/ENU、3D 基线网、联合平差、ζ/EGM96
│   ├── terrain.py             # DEM 采样/剖面/通视/晕渲/等高线
│   ├── registration.py        # 六参数仿射、残差/RMS、世界文件
│   ├── store.py               # C4 SQLite 工程库、快照 input_hash、结果缓存
│   ├── reportgen.py           # C4 Markdown/自包含 HTML/DOCX 设计报告
│   ├── webmap/                # 本地 FastAPI 服务 + 离线 Leaflet 页面
│   │   ├── app.py             # /api/scenarios、/api/scenario、/api/report 等
│   │   ├── state.py           # SQLite 方案/DEM/图层/报告/配准缓存
│   │   ├── render.py          # 晕渲 PNG、等高线/观测 GeoJSON、影像重采样
│   │   └── static/            # index.html、app.js、style.css、leaflet/
│   ├── compare.py             # 方案对比
│   ├── optimize.py            # 贪心/局部搜索/精确分支定界/MILP 代理
│   ├── plot.py                # 网图与椭圆
│   ├── report.py              # 中文表格 + `python -m ctrlnet.report` 入口
│   └── examples.py            # 第 13 节两方案
├── tests/                     # 黄金回归、秩/异常、优化、DEM、配准、存储、报告、Web API
│   ├── test_exact_optimizer.py # C2 分支定界/穷举/预算/设站成本/五准则/MILP
│   ├── test_gnss.py           # C3 坐标/协方差/解析 Cx/联合平差/ζ 拟合/EGM96
│   ├── test_terrain.py        # 合成 DEM 插值/通视/曲率折光/晕渲
│   ├── test_robust.py         # 模拟观测/高斯-牛顿/粗差探测/稳健估计
│   ├── test_registration.py   # 仿射恢复/噪声/共线/世界文件
│   ├── test_store.py          # C4 SQLite 往返/快照哈希/结果缓存/方案版本
│   ├── test_report.py         # C4 Markdown/HTML/DOCX/章节/图表/CLI
│   └── test_webmap.py         # 方案切换、图层、报告 API 与离线静态资源
├── scripts/
│   ├── run_demo.py            # 平面网演示主脚本
│   ├── run_leveling_demo.py   # 水准/三角高程演示
│   ├── run_robust_demo.py     # C1 粗差探测与稳健估计演示
│   ├── run_optimizer_compare.py  # C2 贪心/局部/精确/MILP 多预算对比
│   ├── fetch_dem.py           # 下载/裁剪 Copernicus GLO-30 小样本
│   ├── run_terrain_demo.py    # DEM 通视 + 地形 + 误差椭圆演示
│   ├── run_gnss_demo.py       # C3 GNSS 三维基线网 + 联合平差 + ζ 拟合演示
│   ├── fetch_egm.py           # 下载/裁剪 EGM96 15′ 小样本
│   ├── make_scan_sample.py    # 生成示例扫描图 + 配准控制点
│   ├── build_demo_project.py  # C4 生成 demo_project.sqlite（4 方案）
│   ├── capture_webmap_screenshots.py  # Playwright 无头截图（首屏/方案切换）
│   ├── build_thesis_samples.py  # 生成论文算例 JSON
│   ├── run_thesis_demo.py     # 论文算例演示/CSV/网图
│   └── build_notebook.py      # 由脚本生成 notebook
├── data/
│   ├── cache/                 # DEM 原始大文件（gitignore）
│   └── sample/
│       ├── dem_sample.tif     # 289×374、30 m 裁剪样本（约 0.3 MB）
│       ├── dem_sample.json    # 来源/CRS/垂直基准/范围/校验和
│       ├── egm96_beijing.tif  # EGM96 15′ 北京西山裁剪样本（<1 KB）
│       ├── terrain_project.json  # B2 DEM 示例工程（报告/网页的 DEM 元数据源）
│       ├── demo_project.sqlite   # C4 SQLite 工程（约 108 KiB，4 个方案）
│       ├── scan_sample.png    # 780×820 示例扫描地形图（约 1.4 MB）
│       ├── thesis_example1.json  # 论文算例 1（点/线/角/拓扑/公布值/计算值）
│       ├── thesis_example2.json  # 论文算例 2 近似版
│       └── registration_demo.json  # 4 控制点 + 2 检查点 + 已知仿射
├── notebooks/demo.ipynb       # 已执行的演示 notebook
├── outputs/                   # 图件、CSV、网页截图、results.md（提交）
│   └── report/                # C4 design_report.md/html/docx + assets/*.png
├── pyproject.toml
├── requirements.txt
└── README.md
```

## 14. 计算约定与限制

- 设计态接口（`solve`）：`σ0=1`，`Cx=(AᵀQl⁻¹A)⁺`，不估计单位权方差。
  实测模拟接口（`estimate_network`/`robust_estimate`）另行计算残差、σ̂0、
  w/τ 统计量与稳健权因子，两者不要混用。
- 距离先验方差：`σ²=a²+(b·10⁻⁶·s)²`；角度/方向标准差按角秒输入，内部转弧度。
- 标准误差椭圆不乘置信系数（约 39.35%）；95% 椭圆乘
  `k=sqrt(χ²(2,0.95))=sqrt(-2ln0.05)≈2.4477`。
- `r_i` 对独立观测为 `1-h_ii`；GNSS 2×2/3×3 基线按块内对角元求和，故一条
  3D 基线的 `r_i∈[0,3]`。`trace(R)=n-rank`。
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
  对向观测取均值尚未实现。C3 的高程异常平面拟合可把 GNSS 大地高转正常高，
  但只适用于小范围；高精度 geoid 格网方差场与跨基准转换尚未实现。
- DEM 通视使用与三角高程一致的 `(1−k)x(d−x)/(2R)` 模型；`k` 随气象变化，
  长边应做敏感性分析。30 m DSM 无法反映围墙、电杆、树木、车辆等小障碍，
  NoData 或 DSM 地物不确定时输出 `unknown`，不得直接判为通视。
- DEM 样例采用局部 UTM 50N，只适用于本测区；未实现投影尺度/子午线收敛角的
  全链路 grid/ground 归算、跨带处理与 geoid 改正。
- C1 实测模块以“先验 σ 已知、σ0=1”为默认；w 检验临界值 3.29 对应
  α0=0.001 双侧，τ 检验默认 t 分位数。稳健估计使用先验权下的标准化残差
  与 MAD 尺度；IGG-III 淘汰的观测权因子为 0，但其结果仍不能替代 MDB 报告。
- C2 精确优化仅面向候选数 ≤ 20 的小规模组合，并要求所选方案满秩；
  自由网/最小约束的伪逆协方差不适合直接进入正规矩阵分支定界。
  分支定界默认按候选集合内首次使用计设站费，不自动扣除基准网既有测站；
  需要时用 `existing_stations` 显式声明。MILP 为线性代理近似，不能替代
  精确解或最终平差复算。
- GNSS 三维网在 ECEF 中平差，水平距离/角度与水准在局部 ENU 切平面内联合；
  测区跨度增大时切平面/投影尺度误差不可忽略，必须改用严格投影归算。
- 基线向量三分量已知时，自由网零空间为 3 个整体平移（固定 1 点即可）；
  方案 §5.8.3 的 7 个缺陷对应距离/方向型或需估计相似变换的网。当前实现按
  实际设计矩阵报告零空间，不强行施加 7 个约束。
- 逐基线 3×3 VCV 已支持；跨基线相关块、Helmert 七参数、方差分量估计与
  LandXML 导入尚未实现。
- 高程异常平面拟合的 `E,N` 必须与联合平差的 ENU/工程平面一致；模型不含
  geoid 系统误差，外推会失效。EGM96 15′ 格网只作为对照/可选插值，不应当作
  高精度似大地水准面。
- C4 SQLite 工程库为**单工程只读演示**：`projects/points/observations/scenarios/
  snapshots/results` 六表已实现，支持方案版本/父方案、规范化快照与
  `input_hash` 结果缓存；尚未实现多工程编辑、并发写锁、迁移框架
  （Alembic/schema_version 升级）、审计与工程包（zip/manifest）。
- 报告为设计态报告：HTML 中图片 base64 内嵌；Markdown 使用 `assets/` 相对路径；
  DOCX 依赖本机 pandoc，失败时自动跳过。未实现 PDF、报告模板选择与签名。
- 网页地图报告由 SQLite 结果实时生成并在进程内缓存；方案切换只读，不写回数据库。
- 网页地图只绑定回环地址，无鉴权、只读单工程；扫描图配准为 6 参数仿射，
  未实现多项式/TPS/RPC、影像裁切持久化与任意客户端旋转 warp。
- MBTiles/矢量瓦片/在线底图未实现；当前 DEM 以单张 imageOverlay 叠加，
  大范围浏览需改为按视窗渲染的 XYZ 瓦片。

## 15. 工程持久化、设计报告与方案切换（C4）

### 15.1 SQLite 工程库

`src/ctrlnet/store.py` 只用标准库 `sqlite3`，表结构与重设计方案 §4.5 对应：

| 表 | 关键字段 | 说明 |
|---|---|---|
| `projects` | id、name、schema_version、crs、metadata_json | 工程身份与 CRS |
| `points` | project_id、name、e/n、fixed、sigma_e/n、elevation/lon/lat | 工程级点表 |
| `scenarios` | id、project_id、name、version、parent_id、metadata_json | 方案版本与父方案 |
| `observations` | id、scenario_id、kind、ordinal、enabled、payload_json | 按方案保存观测 |
| `snapshots` | id、scenario_id、input_hash UNIQUE、payload_json | 规范化输入快照 |
| `results` | input_hash PK、result_json、options_json | 按输入哈希缓存结果 |

方案通过 `metadata.points` 选择本方案使用的点集，因此同一工程可同时容纳
第 13 节 4 点网与 DEM 7 点网。模块级 API：

```python
from ctrlnet.store import (
    save_project, load_project, create_scenario, list_scenarios,
    snapshot, get_or_compute_result, update_observations,
)

project = load_project("data/sample/demo_project.sqlite")
child = create_scenario(db, "增补", parent_id="s13-base")   # version=2
snap = snapshot(db, "s13-added")                            # 规范化 JSON + SHA-256
result = get_or_compute_result(db, "s13-added")             # 命中 results 缓存
```

`ProjectStore` 类提供同名方法；`get_or_compute_result` 首次计算也先写入
`results` 再从 JSON 反序列化返回，因此首次与重新打开数据库后读取逐位一致。
同一 `input_hash` 只计算一次；修改/追加观测后快照哈希变化，旧结果保留为历史。

### 15.2 快照与结果缓存

快照结构包含 `schema_version`、工程/网元数据、`parameter_order`、点、观测、
随机模型与 `engine.options`；`canonical_json` 对键排序、浮点按 15 位有效数字
规范化，拒绝 NaN/Inf，再计算 SHA-256。结果包含：

- `network`：点数、观测数、参数数、秩、冗余数、条件数、参数顺序；
- `points`：σE/σN、mp、标准/置信椭圆 a/b/方位角；
- `edges`：边长、σs、相对精度分母；
- `observations`：r_i、MDB（mm/角秒）、外部可靠性最大分量与影响点；
- `reliability` 与 `summary`：min r_i、max MDB、最弱点/边、快照哈希。

### 15.3 设计报告

```bash
.venv/bin/python -m ctrlnet.report \
  --project data/sample/demo_project.sqlite --out outputs/report
# 可选：--scenario s13-added --title "..." --confidence 0.95 --no-docx
```

`src/ctrlnet/reportgen.py` 生成：

1. 工程概况与数据版本（快照哈希、引擎版本、生成时间）；
2. 点与观测清单、先验精度模型、基准；
3. 点位精度/误差椭圆表、边相对精度表；
4. 可靠性（r_i / MDB / 外部）与汇总；
5. 方案对比（全部方案 + 父方案差异）；
6. 优化建议（最弱点/边、r_i/MDB/外部阈值、优化元数据）；
7. DEM 通视结果表；
8. 网图、可靠性图、方案对比图、通视净空图；
9. 复现命令与结果缓存说明。

Markdown 图片使用 `assets/` 相对路径；HTML 把 PNG 以 base64 内嵌，单文件可
离线打开；DOCX 通过本机 pandoc 从 Markdown 转换，pandoc 缺失或失败时跳过并
在 CLI 输出原因。`/api/report` 复用同一生成器，按方案缓存 HTML/MD/DOCX。

### 15.4 网页方案切换与报告下载

`data/sample/demo_project.sqlite` 由 `scripts/build_demo_project.py` 生成，
含 `s13-base`、`s13-added`、`dem-all`、`dem-opt` 四个方案。网页新增：

- 左栏方案下拉：`GET /api/scenarios` 填充，切换调用 `/api/scenario/{id}` 与
  `/api/layers?scenario=`，刷新点、观测、椭圆、统计与视图范围；
- 顶部报告按钮：`GET /api/report?scenario=...&format=html` 下载自包含 HTML；
  相邻 MD/DOCX 按钮下载其他格式；
- 观测图层同时显示距离、角度射线与未作为设计观测的遮挡检查线；
- 方案元数据面板显示版本、父方案、观测数、max mp、min r_i、通视对数、
  冗余数与快照哈希。

### 15.5 测试与演示

```bash
.venv/bin/python -m pytest -q
.venv/bin/python scripts/build_demo_project.py
.venv/bin/python -m ctrlnet.report --project data/sample/demo_project.sqlite \
  --out outputs/report
```

`tests/test_store.py` 验证保存/读取往返、快照确定性、同一哈希缓存、修改观测
后哈希变化、父方案版本与结果重新打开一致；`tests/test_report.py` 验证 Markdown
章节、HTML base64 自包含、DOCX（有 pandoc 时）与 CLI；`tests/test_webmap.py`
验证四方案列表、方案切换后的点/观测/椭圆/统计、图层 GeoJSON 与报告 API。

## 16. GNSS 三维基线网与高程异常（C3）

### 16.1 快速开始

```python
import numpy as np
from ctrlnet import (
    Angle, Distance, GnssBaseline, GnssNetwork, GnssPoint,
    HeightDifference, fit_height_anomaly, solve_gnss,
)

# 点可用经纬度+椭球高，也可用 ECEF (xyz=...)
P1 = GnssPoint("P1", 39.9376, 116.0093, 934.72, fixed=True)
P2 = GnssPoint("P2", 39.9504, 116.0443, 842.49)
P3 = GnssPoint("P3", 39.9209, 116.0096, 824.26)
net = GnssNetwork(
    [P1, P2, P3],
    [
        # ENU 基线：ΔE/ΔN/ΔU + 3×3 协方差
        GnssBaseline("P1", "P2", [2985.8, 1413.9, -93.1],
                     [[4e-6, 4e-7, 0], [4e-7, 4e-6, 0], [0, 0, 1.6e-5]],
                     frame="ENU"),
        GnssBaseline("P2", "P3", [-2965.2, -3274.6, -18.2],
                     [[4e-6, 0, 0], [0, 4e-6, 0], [0, 0, 1.6e-5]],
                     frame="ENU"),
    ],
    distances=[Distance("P1", "P3")],
    angles=[Angle("P1", "P2", "P3")],
    leveling=[HeightDifference("P1", "P3", -110.46, length_km=3.3)],
    origin="P1",
)
result = solve_gnss(net, datum="fixed")
print(result.rank, result.redundancy, result.max_mp, result.max_m3D)
print(result.points["P3"].sigma_E_mm, result.points["P3"].sigma_U_mm)
print(result.baselines["P1-P2"].relative_horizontal)
print(result.reliability.by_label["GNSS P1-P2"].r_i)
```

> 上面的 ENU 数值只为 API 示意；实际请用完整坐标计算，不要手填近似基线。
> `example` 不能直接作为可复现算例，真实演示见 `scripts/run_gnss_demo.py`。

高程异常平面拟合：

```python
from ctrlnet import GeoidControlPoint, fit_height_anomaly

samples = [
    GeoidControlPoint("P1", E=0.0, N=0.0, h=934.72, H=944.88),
    GeoidControlPoint("P2", E=2985.8, N=1413.9, h=842.49, H=852.60),
    GeoidControlPoint("P3", E=20.7, N=-1860.7, h=824.26, H=834.46),
]
# 3 个点刚好确定平面（dof=0）；显式给单位权方差，避免 a priori σ0=1。
fit = fit_height_anomaly(samples, mode="plane", variance_factor=4e-6)
print(fit.a, fit.b, fit.c, fit.rms, fit.applicability_note)
H, sigma_H = fit.normal_height(824.26, 20.7, -1860.7, sigma_h=0.004)
```

### 16.2 模型与约定

- **坐标**：WGS84 `a=6378137.0 m`、`f=1/298.257223563`；`geodetic_to_ecef`、
  `ecef_to_geodetic`、`ecef_to_enu_matrix` 等自实现，不依赖 pyproj。
- **基线观测**：`l_ij = X_j − X_i + v`。ECEF 框架下设计矩阵对 `from` 为
  `−I₃`、对 `to` 为 `+I₃`；参数改为 ENU 时用公共原点的 `Rᵀ`（ECEF→ENU 的
  转置）作链式变换。ENU 基线先按 `reference` 点（默认 `from`）旋转到 ECEF：
  `l_ECEF=Rᵀl_ENU`、`C_ECEF=RᵀC_ENU R`。
- **随机模型**：每条基线完整 3×3 协方差，必须对称正定；`whiten()` 用
  Cholesky `Ql=LLᵀ` 白化，再 SVD 求 `Cx`。逐基线块对角；跨基线相关尚未实现。
- **基准**：`fixed` 删除固定点参数（纯基线向量网固定 1 点即可消除 3 个平移）；
  `minimal`/`free` 用 Moore–Penrose 伪逆，并报告实际零空间维数。`rank` 不足且
  使用 fixed 时抛 `RankDeficientError`。
- **联合平差**：水平距离/角度在公共 ENU 切平面内按 `ΔE,ΔN` 计算；水准高差
  作用于 `U`。若附 `fit_height_anomaly` 结果，正常高差按
  `Δh = ΔH + (ζ_j−ζ_i)` 转为椭球高差；否则假定输入已是椭球高差或局部
  geoid 梯度可忽略。**这是本模块最重要的近似假设。**
- **输出**：点 `E/N/U`、`X/Y/Z`、经纬度/大地高、`σE/σN/σU`、`mp`、`m3D`、
  水平误差椭圆；基线三维/水平长度、`σ`、相对精度；`r_i`/MDB 复用
  `reliability.analyze_reliability`。
- **高程异常**：`fit_height_anomaly` 支持常数 `ζ=a` 与平面 `ζ=a+bE+cN`；
  参数协方差由 `σ0²(AᵀA)⁻¹` 给出；`dof>0` 时默认由残差估计 `σ0²`，
  `dof=0` 或已知噪声水平时用 `variance_factor=` 显式指定 `σ0²`。
  `normal_height()` 同时传播 `σ_h` 与 `σ_ζ`。结果带 `applicability_note`，
  明确“近似，仅适用于小范围”。
- **EGM96 可选**：`EGMGrid.from_geotiff()` 读取 PROJ-data 的
  `us_nga_egm96_15.tif` 或裁剪样本，双线性插值。完整格网约 2.7 MB，放在
  `data/cache/`（gitignore）；仓库只提交 `data/sample/egm96_beijing.tif` 小样本。

### 16.3 演示与结果

```bash
.venv/bin/python scripts/fetch_egm.py      # 可选；已有裁剪样本时跳过
.venv/bin/python scripts/run_gnss_demo.py
```

演示用 `terrain_project.json` 的 7 点（P1/P2 固定）构造 13 条 ENU 基线、
6 条距离、4 个水平角、9 条水准；大地高由 EGM96 格网 ζ 加 4 mm 模拟噪声生成。
当前结果：

- GNSS-only：参数 15、冗余 24，max `mp≈3.02 mm`，max `m3D≈5.23 mm`；
- 联合平差：冗余 43，max `mp≈2.98 mm`，max `m3D≈3.14 mm`，max `σU≈1.26 mm`；
- ζ 平面：`a≈−10.1666 m`、`b≈7.71 ppm`、`c≈18.14 ppm`，残差 RMS≈4.8 mm；
- EGM96 与平面近似的差值 RMS≈0.96 mm（局部 15′ 格网很平滑，主要用于格式与
  流程对照，不代表 geoid 精度）。DEM 的垂直基准为 EGM2008，演示格网为
  EGM96；两者模型差异未改正，ζ 数值只用于演示转换/拟合流程。

测试覆盖：`tests/test_gnss.py` 的坐标往返、已知 ENU、协方差旋转、解析 `Cx`、
联合精度不劣化、ζ 参数恢复与 EGM96 插值。第 13 节黄金期望值未修改。

## 17. 论文算法与算例复现（D1）

本节实现 `docs/target/target_spec.md` 第 3 节的论文约定，并与现有平差引擎并存。
所有计算离线完成，不访问任何在线瓦片/地图 API。

### 17.1 快速开始

```python
from ctrlnet.thesis import (
    gauss_forward, gauss_inverse, distance_sigma_mm, build_angle_network,
    error_ellipse, export_coordinate_text, export_angle_topology,
)

x, y = gauss_forward(34.2, 117.2)                 # CM 117°E，y 含 500 km
lat, lon = gauss_inverse(x, y, lon_hint=117.2)
sigma = distance_sigma_mm(544.8431, a_mm=15, b_ppm=20, model="linear")
```

测距先验在 `Distance` 上也可选：

```python
from ctrlnet.model import Distance
d = Distance("1", "2", a=0.015, b_ppm=20.0, sigma_model="linear")
```

### 17.2 论文约定

- **高斯投影**：Krüger n⁶ 级数，CGCS2000（默认）/WGS84，3° 带自动或指定
  中央子午线，东坐标 +500 km；正反算往返 <1e-6 m，已用 PROJ 离线核对。
- **测角网**：式 3-22，`ρ″=206265`、坐标改正以 mm 计，`P=I`；
  `Q=(BᵀPB)⁻¹` 为 mm²/(″)²，`M=Mw·sqrt(Qxx+Qyy)` 为 mm。
- **论文截图口径**：`Q_paper = Q_mm2/100`（实际为 cm²/(″)²），
  `ThesisNetworkResult` 同时提供 `q_mm2` 与 `paper_q()`；`M` 的 cm/mm
  10 倍口径差见 `docs/target/reproduction.md`。
- **误差椭圆**：式 3-38/3-39，`E/F` 与 `φE`；用 `atan2` 保证象限正确。
- **角度拓扑**：论文三元组按数值验证为 `(测站, 后视, 前视)`；解析/导出
  默认 `order="station_first"`，并支持 `"backsight_first"`。已知点 8/9
  记为 -1/-2。
- **文本**：坐标导出为 `点1；x，y` 逐行；支持解析回读。

### 17.3 算例 1（9 点测角网）

14 个已给角、`Mw=10″`：

| 量 | 严格 mm² 口径 | 论文截图口径 |
|---|---:|---:|
| Qxx(1) | 65.0191 | **0.6502** |
| Qyy(1) | 30.3890 | **0.3039** |
| 最弱点 | 1 | 1 |
| M1 | 97.677 mm | 9.768（论文标 0.97 cm） |

图 5-7 的边长相对中误差分母反推为 `D = S / 0.01 m = 100·S`；17 条中 14 条
完全一致，线 1/3/6 差 0.2/0.2/2.0 m，正好对应线库距离的截图转录差。

正文称 19 个角，但公布 Q 精确等于 14 个角的满秩解；补 5 个真实角只会改善
Q（穷举 C(13,5) 最佳为 0.4740/0.2473）。27 角优化的新增角未公布，13 元
子集搜索最佳为 0.4129/0.1942，均不能精确复现，测试中标 `xfail` 并注明原因。
完整记录见 [`docs/target/reproduction.md`](docs/target/reproduction.md)。

### 17.4 算例 2（9 点边角网，近似）

点位未公布，用 17 条线库边的距离/方位角以 soft-L1 重建局部坐标（残差约
2 cm）。在 3 分钟上限内搜索“10 边 + 11 角”，二级参数 `a=15 mm`、
`b=20 ppm`、`σS=a+bS`、`P=σ0²/σS²`（取 `σ0=10`），得到点 7 为最弱点：

| 量 | 本仓库 | 论文公布 |
|---|---:|---:|
| Qxx(7)（论文口径） | 0.17153 | 0.1715 |
| Qyy(7)（论文口径） | 0.15748 | 0.1575 |
| M7（论文数值口径） | 5.736 | 0.57 cm=5.7 mm |

观测选择与 σ0 是必要的近似假设，故只声称 4 位小数近似复现。

### 17.5 命令与输出

```bash
.venv/bin/python scripts/build_thesis_samples.py
.venv/bin/python scripts/run_thesis_demo.py
.venv/bin/python -m pytest -q tests/test_thesis.py
```

- `data/sample/thesis_example1.json`、`thesis_example2.json`：网页用点/线/
  角/拓扑/公布值/计算值/误差椭圆。
- `outputs/thesis_results.md`、`thesis_example1_edges.csv`、
  `thesis_example1_network.png`：演示结果与图。
- `tests/test_thesis.py`：投影往返、PROJ 对照、等级表、线性 σ、拓扑/坐标
  文本往返、误差椭圆、算例黄金断言与 2 个 `xfail`。

## 18. 路线图完成度

以重设计方案 §9 的 P0–P5 与本仓库的 B1/B2/B3/C1/C2/C4 增量对照：

| 阶段/能力 | 状态 | 已实现 | 未完成 |
|---|---|---|---|
| P0 基线/架构、§13 黄金回归 | ✅ 已完成 | `examples.py`、`tests/test_section13.py`、文档与目录 | — |
| P1 平面 MVP：边角/方向、基准、精度、可靠性 | ✅ 已完成 | 设计矩阵、SVD/伪逆、固定/加权/自由基准、mp/椭圆/边、r_i/MDB/外部 | 投影全链路、跨带 |
| P2 水准/高程（B1/C3） | ✅ 已完成（局部 geoid） | 1D 水准、路线/环、三角高程、高程可靠性、ζ 平面拟合/正常高转换 | 高精度 geoid、跨基准方差场 |
| P2 GNSS（C3） | ✅ 已完成（核心） | 3D ECEF/ENU、3×3 VCV、固定/最小约束、联合平差、基线相对精度 | 跨基线相关 VCV、Helmert、LandXML |
| P3 DEM 通视/地形渲染（B2） | ✅ 已完成 | GeoTIFF 采样、剖面、曲率折光、四态、晕渲/等高线 | 大范围瓦片化 |
| P3 投影归算 | ⚠️ 部分 | 局部 UTM 50N、DEM 米制坐标 | 投影尺度、子午线收敛角、grid/ground、跨带 |
| P4 观测优化（C2） | ✅ 小规模精确 | 贪心/1 换 1、A/D/E/max_mp/最弱边、≤20 候选分支定界、MILP 代理 | Pareto 前沿、大规模 MICP、成本模型持久化 |
| C4 SQLite 工程库/快照/结果缓存 | ✅ 已完成 | 六表、方案版本/父方案、`input_hash`、结果缓存 | 多工程编辑、迁移框架、审计、工程包 |
| C4 设计报告 | ✅ 已完成 | Markdown、自包含 HTML、DOCX（pandoc）、图表与方案对比 | PDF、模板选择、签名 |
| C4 网页方案切换/报告下载 | ✅ 已完成 | 四方案下拉、图层/统计刷新、`/api/report` HTML/MD/DOCX | 在线编辑、工程树、鉴权 |
| P5 硬化/试点 | ⚠️ 部分 | 本地回环、只读、离线 Leaflet、单元/集成测试 | 安装包、并发写、审计、试点、性能压测 |
| 地图资源/MBTiles/矢量瓦片 | ⚠️ 部分 | 单张 DEM imageOverlay、扫描图 6 参数仿射 | MBTiles/XYZ、多项式/TPS/RPC、图层管理 |
| VCE、Helmert、多用户 | ❌ 未完成 | GNSS 3D 联合平差、局部 ζ 拟合 | Helmert/VCE、跨基线相关 VCV、多用户与权限 |
