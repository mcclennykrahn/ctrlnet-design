# 文档对齐实施报告（2026-11-06）

本批先审计后实施，未一次完成全部文档功能。提交标识将在代码提交后追加。

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

## 剩余缺口

仪表盘原地网络底图/投影视图迁移；任意中央子午线编辑和严格基准转换；BD09 配置；完整拓扑 JSON 导入；统一多方案版本树、比较与差异；拖拽/吸附/撤销重做；全国离线矢量、MVT/RPC；GNSS/自由网等高级核心的编辑器接线。文本导入仅绝对高斯正整数点号、初始均未知且清空拓扑，不支持算例 2 的局部坐标文本回读。

未提交 `data/sample/demo_project.sqlite`，保留其原有脏状态；未提交 `.dsh-prompts/`。未改其他仓库，无历史重写。
