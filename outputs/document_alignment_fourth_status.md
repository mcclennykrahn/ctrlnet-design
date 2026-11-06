# 第四批实施与验证（2026-11-06）

基线 main `cab7246c7ae81c467ad627a0342e7dd3744fa676`。本地实施，无 Cloud Agents；提交与推送真实结果在文末补记。

- 原生 SQLite 桥接：论文当前四库 → 命名工程 → 明确父快照另存分支 → 重新打开；仪表盘同一面板列出/选择/比较。使用 store.save_editor_version 原子事务，原生 projects/scenarios/snapshots；完整 topology 在 scenario metadata，版本点集独立，父链与父快照可追踪。旧 JSON 存档与完整 topology JSON 协议保留。
- UI/API：`/api/engineering/projects`、`save`、`open/{sid}`、`calculate/{sid}`、`compare`。两页共享 DB，页面选择不改全局 DEM 演示工程。默认 data/sample/thesis_web.sqlite，可配置 CTRLNET_THESIS_DB。
- 高级计算：选中角/距离真实联合精度计算；fixed/free/minimal → adjustment.solve，95/99%/标准椭圆 → precision；结果有秩/冗余/点精度；非法选项、欠约束明确400。GNSS基线/相关系数/robust UI未做，核心保留。非原始实测值残差迭代编辑器。
- 状态：创建/分支/快照同一事务，失败不留半个工程；项目status=saved/version=方案数，方案status=saved/version=父+1。完整状态生命周期仍部分。

## 测试

- `.venv/bin/python -m pytest -q`：**341 passed / 1 skipped / 2 xfailed / 8 warnings，20.89秒**；新增4个测试，skip/xfail为原有限制。日志 `document_alignment_fourth_pytest.txt`。
- 第四批 Chromium：**1脚本通过，零pageerror**。UI勾选距离+角、命名保存、再加一边分支、父快照、完整回读、95→99%改变请求/哈希/椭圆、dashboard选择比较、默认demo不覆盖。实际比较：观测15→16、冗余1→2、最弱点73.612→70.436 mm。日志 `document_alignment_fourth_e2e.txt`；数值与哈希 `document_alignment_fourth_evidence.json`。
- batch2 Chromium：**1脚本通过**（真实本地MBTiles、mock网络成功/abort/12秒挂起回退、JSON/投影/比较）。日志 `document_alignment_fourth_batch2_regression.txt`。
- 第三批 Chromium：**1脚本通过，零pageerror**（真实warp/等高线/配准/缓存/剖面、拖动/网格吸附/撤销重做）。日志 `document_alignment_fourth_third_regression.txt`。
- 原论文 Chromium：**1脚本通过**，9点/17线/14角、Qxx=.6502/Qyy=.3039、分母17行。日志 `document_alignment_fourth_original_regression.txt`。
- 合计 **4个浏览器脚本全部通过**；未跳过要求的旧回归。截图 `document_alignment_fourth_thesis.png` / `dashboard.png` 已视觉检查。旧脚本覆盖的既有截图已恢复，不混作新证据。底图行为未改，basemap_note无需更新。

## 文件卫生与边界

pytest与旧浏览器脚本现使用各进程临时SQLite，样例资源只读链接；没有恢复/删除共享示例数据库的操作。`data/sample/demo_project.sqlite` 前后 SHA256 均为：

`fa597f57b5952fa603b9464550c5d72e9c7c2b6bd4efc48c8281692b84a204f6`

样例DB未修改、未暂存；`.dsh-prompts/**`与原有codex长日志未暂存。无vendor底图包、无BD09/百度命名。剩余：完整树/合并/重命名、预置DEM方案自动进入论文四库、专用GNSS/robust UI、全状态机、点线吸附和持久历史、任意CRS/七参数等。默认demo地图不随共享工程选择自动转换；面板已明确说明。

实施提交 `e962e523a740553ea8a49f381cf42359a3ea2b41`；推送成功 `cab7246..e962e52 main -> main`。随后独立文档补记；没有 amend。提交后再次核对样例 SHA 一致，git status 仅剩原有未跟踪 `.dsh-prompts/**` 和旧 batch2 codex 日志，无跟踪文件脏写。
