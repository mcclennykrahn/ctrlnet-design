第 C4 步（下一阶段：工程持久化、设计报告、网页方案切换）。先阅读 docs/redesign_plan.md §4（数据模型/SQLite 表结构/DesignSnapshot/input_hash）、§7、§8，以及现有 webmap 代码。
1. src/ctrlnet/store.py：SQLite 工程存储（标准库 sqlite3）：projects、points、observations、scenarios（方案版本号、父方案）、snapshots（规范化 JSON + SHA-256 input_hash）、results（按 input_hash 缓存计算结果）。API：save_project / load_project / create_scenario / list_scenarios / snapshot / get_or_compute_result。保存后再读回结果必须完全一致；同一输入哈希命中缓存；修改观测后哈希变化。
2. src/ctrlnet/reportgen.py：生成设计报告 Markdown 与 HTML（自包含，图片 base64 内嵌或相对路径），内容：工程概况、点与观测清单、先验精度模型、基准、点位精度/误差椭圆表、边相对精度、可靠性（r_i/MDB/外部）、方案对比、优化建议、通视结果、图表；可选调用 pandoc 生成 docx（本机有 pandoc；失败则跳过）。命令行：python -m ctrlnet.report --project ... --out outputs/report/。
3. 网页：webmap 增加方案下拉切换（至少：第 13 节基准/增补、DEM 演示网 全部通视边/优化后方案），切换后刷新点、观测、椭圆、统计；增加“下载报告”按钮（GET /api/report?scenario=... 返回 HTML，另有 .md/.docx）。数据从 SQLite 工程 data/sample/demo_project.sqlite 读取（体积小，可提交）。
4. 测试 tests/test_store.py、tests/test_report.py，更新 tests/test_webmap.py（新 API）。
5. 生成 outputs/report/design_report.html、design_report.md（以及 .docx 如可），重新用 Playwright（/workspace/venvs/lab 或 .venv）截图 outputs/webmap_screenshot.png（显示方案切换与报告按钮）和 outputs/webmap_scenario_screenshot.png，服务只绑定 127.0.0.1，截图后关闭。
6. README 增加对应章节，并在末尾更新路线图完成度（已完成/未完成）。
