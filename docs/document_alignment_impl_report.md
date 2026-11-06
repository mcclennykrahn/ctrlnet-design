# 文档对齐实施报告（2026-11-06）

本批先审计后实施，未一次完成全部文档功能。实施提交：`1f72782eced1f1954b7a516f2509b7ec87e53bdb`，已成功 `git push origin main`。本报告随后以独立文档提交补记真实哈希，未改写历史。

## 已完成

- 实际读取论文 PDF 关键页/文本、三份计划、README、指定前后端与测试，Chromium 实际打开 `/thesis` 与 `/` 后写差距矩阵。
- `/thesis` 新增离线 DEM / MBTiles / OSM 道路 / Esri 影像切换，公开 HTTPS XYZ，无密钥，无代理、预抓、百度私有 API。默认不请求外网；可见署名、数据范围与原生级别。失败明确提示并回退 DEM，首次/后续加载超时 12 秒。
- 固定 CGCS2000 高斯三度带 117°/39 带、假东/轴序/局部模式摘要和点表双坐标；跨带点击拒绝。修复算例 2 新点与原局部坐标混用问题。
- 论文绝对高斯坐标文本文件导入、覆盖确认、原子校验、地图与四库同步；已有文本导出形成对称入口。拒绝非有限数/重复点名/局部坐标/带外点，失败不覆盖现工程。
- 保留已有点线角/观测/删除级联闭环，新增导入后构线构角、命名保存、新建、列表读取的浏览器回归；新建/读取补覆盖提示。
- `/` 与 `/dashboard` 增加论文编辑器入口和工程独立说明，未把 EPSG:3857 瓦片误放入米制 CRS.Simple。
- 更新 target_spec 与 README 底图决策及新增功能说明。

## 验证

- `.venv/bin/python -m pytest -q`：**330 passed, 1 skipped, 2 xfailed，0 failed**。8 个既有依赖弃用警告。skip：可选 pyproj 未安装；xfail：论文 19/27 角完整拓扑未公布。日志 `outputs/document_alignment_pytest.txt`。
- `scripts/test_thesis_e2e.py`：PASS，9 点/17 线/14 角，Qxx=0.6502、Qyy=0.3039，分母表17行。
- `scripts/test_document_alignment_e2e.py`：PASS，文件导出再导入、构线构角、保存/新建/读取、mock 网络失败自动回退、仪表盘入口。无 pageerror。
- Chromium 本机真实联网：OSM 道路、Esri World Imagery **当前视窗瓦片均成功加载**，非 mock；状态记录 `outputs/document_alignment_network.json`，截图 `document_alignment_road.png` / `document_alignment_satellite.png`。此记录只证明本机本次可用，不保证国内网络或未来服务可用。
- 截图已视觉检查；离线 DEM 和库/投影 UI 见 `document_alignment_editor.png`。MBTiles 样本在北京、不覆盖徐州，选项如实标范围，未虚构徐州覆盖。

## 首批结束时的剩余缺口（batch2 当前状态见下文）

仪表盘原地网络底图/投影视图迁移；任意中央子午线编辑和严格基准转换；BD09 配置；完整拓扑 JSON 导入；统一多方案版本树、比较与差异；拖拽/吸附/撤销重做；全国离线矢量、MVT/RPC；GNSS/自由网等高级核心的编辑器接线。文本导入仅绝对高斯正整数点号、初始均未知且清空拓扑，不支持算例 2 的局部坐标文本回读。

未提交 `data/sample/demo_project.sqlite`，保留其原有脏状态；未提交 `.dsh-prompts/`。未改其他仓库，无历史重写。


## Batch 2 已交付（2026-11-06）

基线 `d32607c`；本批代码提交 `41577a4f15609e4bb5da23ae5582672b1a3ec6bd`，已成功 `git push origin main`。全部本机编辑与 Chromium 验证，没有使用云代理；Codex 中途停滞，由执行代理完成提交卫生与推送。

- `/` 与 `/dashboard` 原地底图选择：默认离线 DEM、离线 MBTiles、OSM 道路、Esri 影像。保留原米制地图，XYZ 在同一区域使用 EPSG:3857 地图；`/api/layers/geographic` 将工程 UTM 的点、观测及椭圆转为经纬度，无新增 pyproj 硬依赖。支持 WGS84 UTM EPSG:326xx/327xx；其他 CRS 明确报错并回退。
- 可见工程 CRS / 显示 CRS、署名；不代理、不预抓、默认无网络。瓦片错误与12秒超时回退 DEM，至少成功一张瓦片且当轮完成才宣称加载。MBTiles 元数据覆盖与原生级别可见；北京本地瓦片成功加载。XYZ 模式禁用 DEM 晕渲/等高线/配准控件，明确提示两点剖面切回 DEM；离线模式既有剖面、配准、场景、报告保持。
- thesis 顶部投影设置：任意中央子午线、3°/6°、gauss/utm、假东及轴序。保留经纬度重算平面，带外整体拒绝；摘要、点表、计算结果的 projection 字段随工程参数更新，命名保存可回读。gauss 采用 CGCS2000，utm 采用 WGS84/k0=.9996；演示默认117°/39带不变。绝对文本导入按当前工程所选参数反算，帮助文字已说明。
- thesis 完整拓扑 JSON 导入/导出：复用 `ctrlnet.thesis.web/1`，覆盖确认后原子验证；重复编号、非有限数、带外点、双坐标不一致、失效引用及错误观测编号拒绝，不污染现有工程。最近20次成功修改可撤销，失败不入栈，刷新清空，不含重做。
- 仪表盘方案版本列表、父链接和打开方案按钮；“与当前方案比较”调用 `/api/scenarios/compare`，复用 `compare.py` 实际求解比较，显示两个 input_hash、精度/冗余/工作量及点边比较表。

### JSON 入口约定

在论文页先“导出工程 JSON”，编辑文件后通过“导入完整拓扑 JSON”回读。必需 `schema: "ctrlnet.thesis.web/1"` 与 `points`、`lines`、`angles` 数组（可为空，每类最多2000项，文件最大4 MB）。

- `points`: `{id:"p1", name:"1", lon:117.2, lat:34.2, x:北坐标, y:东坐标, fixed:false}`；点名唯一正整数，稳定 id 唯一，双坐标须与 projection 一致（允许0.05 m舍入差）；局部算例沿用徐州锚点平移语义。
- `lines`: `{id:"l1", name:1, from:"p1", to:"p2"}`；引用点 id，不能同点；长度/方位由坐标重算。
- `angles`: `{id:"a1", name:1, backsight:"p1", station:"p2", foresight:"p3"}`；三个不同点 id，角值重算。
- `network`: `grade`、`observed_edges`/`added_edges`（线 id 数组）、`observed_angles`/`added_angles`（角 id 数组）、`tolerance_mm`、`ellipse_scale`、`show_ellipses`。不另设第二种 observation 格式；观测选择即论文网库中的观测。
- `projection`: `central_meridian`、`zone_width`（3/6）、`convention`（gauss/utm）、`false_easting_m`；缺省沿用117°、3°、gauss、500000。其他展示字段可随导出文件保留；`seq` 导入时重新推导。

### Batch 2 验证与证据

- 全量 `.venv/bin/python -m pytest -q`：**334 passed, 1 skipped, 2 xfailed**。新增4个测试覆盖投影保存/所选CM文本反算/原子拒绝、拓扑往返与失败不污染、仪表盘重投影、版本比较 API。日志 `outputs/document_alignment_batch2_pytest.txt`。
- `scripts/test_document_alignment_batch2_e2e.py`：Chromium 检查底图选择、XYZ CRS/成功状态、XYZ中方案切换、abort错误回退、挂起请求真实等待12秒回退、本地MBTiles成功、离线剖面SVG、版本比较、CM编辑/跨带拒绝、拓扑导入/坏引用拒绝/撤销。网络成功路径是 mock，不作为公网可用证据。
- 原 `scripts/test_thesis_e2e.py`：通过；算例1保持9点/17线/14角，Qxx=.6502、Qyy=.3039。原截图不纳入本批，保留仓库旧证据。
- 新截图 `outputs/document_alignment_batch2_dashboard.png`、`document_alignment_batch2_dashboard_xyz.png`（真实本地MBTiles）、`document_alignment_batch2_thesis.png`；已视觉检查。E2E日志同名前缀。

### Batch 2 后真实剩余缺口

XYZ中DEM栅格/等高线/扫描图与地图两点剖面尚未重投影；任意EPSG、基准七参数、南半球绝对文本等更完整CRS交换尚缺；自定义CM的带号仅参考，不等于注册EPSG。thesis命名工程与仪表盘版本仍分离，没有可编辑统一分支树/合并；无拖拽、吸附、重做或持久撤销。全国离线矢量/MVT/RPC与GNSS/自由网等高级编辑器仍缺UI。未启用BD-09。

测试运行会产生示例SQLite缓存；提交前恢复 `data/sample/demo_project.sqlite`，不暂存该文件、`.dsh-prompts/**` 或原有 `outputs/document_alignment_batch2_codex.log`。提交和推送结果：`41577a4` 已推送；未暂存 demo sqlite / `.dsh-prompts` / codex 长日志。

## 第三批（基线 0b55d04，提交结果见末尾补记）

先复审当前代码与计划，交付 Layer 1 地形显示/交互闭环以及 Layer 2 吸附、拖动、重做，未尝试不完整的统一工程存储替换。

- 仪表盘独立离线 EPSG:3857 DEM 入口；DEM 晕渲与扫描配准影像按工程边界真正 warp，最大1536像素，DEM overview、服务锁和实例缓存；缓存及投影提示可见。等高线坐标反算，所有 XYZ 底图共享开关；已知 P1 与地形/扫描背景同屏截图，并记录经纬度/像素/边界。标准 MBTiles 地理 bounds + 原生 Mercator 瓦片保持正确服务。
- XYZ 两点点击调用地理剖面 API，转换回原工程 CRS 采样原 DEM；图表与地图剖面线接线，Simple 模式保留。
- thesis 放点/拖动可选米制网格吸附，默认关闭以保留旧交互；PATCH 校验后原子更新，关联线角刷新，观测选择保留。拖动失败恢复显示。撤销/重做最近20步，普通新修改清空 redo，刷新不持久化。
- 验证：全量337 passed / 1 skipped / 2 xfailed；新增3个后端测试涵盖真实 Mercator 像元/边界、warp缓存/剖面、拖动原子性/关联几何；第三批 Chromium 实际鼠标点击/拖动、吸附、撤销/重做，零 pageerror。batch2 E2E（含真实本地MBTiles、mock网络及12秒回退）与原论文 E2E 均通过。截图已视觉检查，日志 `outputs/document_alignment_third_*`。

剩余：统一可编辑方案树、GNSS高级参数 UI、点/线吸附、持久历史、任意 CRS/基准七参数及非标准地理像元 MBTiles 通用导入，仍未完成。warp 为实例缓存而非跨重启磁盘缓存，图像为有界预览；不承诺任意大区域的全分辨率在线渲染。无 BD-09、百度或全国离线底图包。

大图有界 warp 实测：6000×6000 合成 RGBA PNG → 1188×1536，0.974秒（仅本机 warp 阶段，非完整真实大 DEM 性能保证），见 `outputs/document_alignment_third_performance.json`。固定点默认锁定，先在点库明确切换未知点方可拖动；API 同样拒绝直接移动固定点。

第三批实际实现提交：`9184088`，已成功 `git push origin main`（`0b55d04..9184088`）。最终独立全量 pytest：337 passed / 1 skipped / 2 xfailed，31.55秒；三个 Chromium 脚本通过。提交后独立补记结果，不 amend、不改写历史。示例数据库与旧截图已恢复，未暂存 `.dsh-prompts/**` 或既有 codex 长日志。
