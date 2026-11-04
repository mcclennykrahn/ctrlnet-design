# 平面控制网精度估算与优化设计系统重设计方案

> 依据文档：《基于双模式离线地图的平面控制网精度估算与优化设计详细方案》（original.md，下称“原方案”）。
>
> 读者对象：产品负责人、系统架构师、测绘算法工程师、前后端工程师、测试与质量负责人。
>
> 设计定位：把原方案从“平面边角网精度估算器”升级为“**多源控制网设计、可靠性评估与观测方案优化平台**”。保留原方案的业务闭环、版本机制、数学主干和第 13 节算例；在分层架构、数据模型、网型覆盖、可靠性、优化、地形与投影处理上系统补齐。

## 0. 设计摘要

### 0.1 一句话方案

以**不可变设计快照**为计算契约，以**纯函数计算内核**为核心，采用“六层架构 + 端口适配 + 异步任务”的本地优先 Web/桌面应用；MVP 先交付可信的平面边角网与可靠性分析，再逐步扩展 GNSS 基线向量网、水准/高程网、DEM 通视、投影变形处理和 A/D/E 观测方案优化。

### 0.2 与原方案的关键差异

| 维度 | 原方案 | 重设计 |
|---|---|---|
| 系统定位 | 平面控制网设计器 | 多源控制网设计与优化平台 |
| 架构 | 四层结构，计算层与存储层边界较粗 | 六层架构；领域层定义端口，计算内核无 I/O，基础设施适配 |
| 网型 | 平面测角/测边/边角网 | 平面 2D、GNSS 基线 3D、水准 1D；预留 3D 联合 |
| 随机模型 | 对角/分块协方差 | 完整 VCV、跨基线相关、可选方差分量估计 |
| 基准 | 固定点、带精度约束、自由网简述 | 固定/加权/最小约束/自由网/Helmert 基准，统一秩诊断 |
| 可靠性 | 只给冗余数 `m−rank(A)` | `r_i`、内部/外部可靠性、MDB、w-test、粗差可探测性 |
| 优化 | 手工复制、逐个候选试算 | 贪心/局部搜索 + 整数规划/MICP；A/D/E 最优准则；成本模型 |
| 地形 | DEM 显示、查询、等高线 | 剖面采样、通视矩阵、地球曲率与折光改正、DSM/DTM 语义 |
| 坐标 | 提到投影与归算 | 显式投影归算管线、尺度因子、高程归算、跨带/变形检查 |
| 数据模型 | Observation 宽表 + 可空外键 | 类型化观测 + 观测方程注册 + 全局点身份 + 快照 |
| 接口 | 少量 REST 端点 | 版本化 REST + 异步任务 + SSE 事件 + 幂等/ETag |
| 验证 | 第 13 节精度复算 | 第 13 节精度 + 可靠性 + GNSS/水准/通视/优化回归 |

### 0.3 设计原则

1. **正确性优先于功能数量**：任何精度结果必须可复算、可解释、可追溯；单位、基准、投影、参数顺序必须显式。
2. **设计态与实测态分离**：先验精度估算和实测后验平差共用模型，但输入、输出和诊断字段分开，避免把设计精度误当实测精度。
3. **快照不可变**：计算只接受 `DesignSnapshot`，结果只绑定 `snapshot_hash`；编辑永远不直接改历史结果。
4. **内核纯净**：平差、可靠性、优化、地形、大地计算不依赖数据库、HTTP、UI，便于单测、批处理和第三方复算。
5. **渐进交付**：MVP 先闭环、先可信；GNSS、水准、优化按阶段增量，不搞“大爆炸式”重写。
6. **优化可解释**：推荐方案必须给出边际收益、成本、约束满足情况、与基准方案的差异，允许人工否决。
7. **离线优先**：地图、DEM、字体、依赖本地分发；联网只是可选增强。
8. **默认安全**：本地单用户也要有输入校验、路径限制、资源配额、审计与备份。

### 0.4 关键术语

| 术语 | 含义 |
|---|---|
| VCV | Variance-Covariance Matrix，观测或参数的协方差矩阵 |
| `r_i` | 第 i 个观测的多余观测分量（redundancy number），衡量该观测对检核的贡献 |
| MDB | Minimal Detectable Bias，给定显著性/检验功效下可探测的最小粗差 |
| A/D/E 最优 | 最小化参数协方差迹 / 最大化信息矩阵行列式 / 最大化信息矩阵最小特征值 |
| DSM/DTM | 数字表面模型（含地物）/ 数字地形模型（裸地） |
| ENU/ECEF | 局部东-北-天坐标 / 地心地固坐标 |
| Snapshot | 某一输入版本的点、观测、随机模型、基准、引擎配置的不可变序列化 |

## 1. 现状评估与设计目标

### 1.1 原方案可保留的资产

- **业务闭环**：建工程 → 组织底图 → 选点构网 → 设置计算 → 分析调整 → 方案比较 → 导出回读。
- **版本与状态机制**：`input_hash`、`stale/valid`、旧任务归档，直接继承并强化。
- **双地图分工**：真实地图辨认地物，地形图观察坡地、道路、高差与设站环境。
- **数学主干**：距离/方向/角度偏导、固定/加权基准、Cholesky 白化、SVD 求协方差、误差椭圆、相对精度。
- **第 13 节算例**：坐标、观测、随机模型和结果完整，是极好的黄金回归基准。
- **工程化约束**：单位、角度包裹、秩阈值、错误码、事务回滚、工程包 manifest。
- **离线部署思路**：本地瓦片、字体、图标、依赖随程序分发。

### 1.2 缺口、影响与优先级

| 缺口 | 影响 | 优先级 | 对应阶段 |
|---|---|---|---|
| 无 GNSS 基线向量网 | 无法设计现代 GNSS 控制网；无法处理 3×3 基线协方差与相关基线 | P1 | V1 |
| 无水准/高程网 | 高程控制与平面控制割裂；无法做水准环闭合与高程基准设计 | P1 | V1 |
| 无 `r_i`/内部外部可靠性/MDB | 无法识别“精度好但检核能力差”的网形；无法回答能发现多大粗差 | P0 | MVP |
| 优化仅靠手工试算 | 候选多时效率低；无法保证预算下近似最优 | P1 | V1（贪心）/ V2（整数规划） |
| DEM 未用于通视 | 计划观测可能实际不可通视；长边受地球曲率/折光影响 | P1 | V1 |
| 投影/高程归算不系统 | 大范围、高海拔、跨带测区存在系统性尺度误差 | P0 | MVP（基础）/ V1（完整） |
| 随机模型不支持完整 VCV | GNSS 相关基线、多类观测权比失真 | P1 | V1 |
| 无粗差探测/稳健估计 | 实测数据无法定位粗差；设计阶段无探测能力指标 | P1 | V1 |
| 数据模型宽表、可空外键 | 新观测类型需改表；基线/水准表达困难 | P0 | MVP |
| 稠密 SVD、无稀疏策略 | 大规模网络性能不可接受 | P2 | V2 |
| 接口覆盖不足 | 优化、通视、基线导入、任务事件缺失 | P1 | 随功能 |
| 单机单用户、地图版权/体积 | 企业推广受限 | P2 | V2 |
| 验证仅覆盖简单边角网 | 新功能缺质量门槛 | P0 | 全程 |

### 1.3 设计目标

**功能目标**

1. 支持平面测角、测边、边角、方向观测，支持固定/加权/自由基准。
2. 支持 GNSS 基线向量网（3D ECEF/ENU）与水准/高程网（1D），并预留 3D 联合。
3. 输出点位精度、误差椭圆、相对精度、方位角精度、高程精度。
4. 输出 `r_i`、内部可靠性（MDB）、外部可靠性、w-test/粗差探测结果。
5. 支持基于候选观测集的贪心、局部搜索和（小规模）整数规划优化，支持 A/D/E 准则与成本约束。
6. 支持基于 DEM 的通视分析、地球曲率/折光改正、投影归算与变形检查。
7. 支持方案比较、差异分析、可回读工程包和带来源/版本的报告。

**质量属性**

| 属性 | 目标 | 验证方式 |
|---|---|---|
| 数值正确性 | 第 13 节结果误差 ≤ 0.001 mm；协方差对称正定；解析偏导与数值差分相对误差 ≤ 1×10⁻⁶ | 黄金回归 + 有限差分 |
| 可复现性 | 同一快照、同一引擎版本，结果在浮点容差内一致 | 快照重放测试 |
| 性能 | 300 点/600 参数平面网 < 2 s；2000 点稀疏网 < 30 s（目标值，需基准测试确认） | pytest-benchmark |
| 可用性 | 新建工程到首次计算 ≤ 5 个主要步骤；错误可定位到实体 | 可用性测试 |
| 离线性 | 断网可完成选点、计算、导出 | 离线 E2E |
| 可维护性 | 计算内核分支覆盖率 ≥ 90%；API 覆盖率 ≥ 80% | CI 覆盖率 |

### 1.4 非目标（MVP 明确不做）

- 不做 GNSS 原始观测处理（RINEX 解算）、不做基线解算软件替代；只接收基线向量及其协方差。
- 不做水准外业记录/电子水准仪手簿的完整替代；只做网设计与平差。
- 不做完整厘米级大地水准面精化；只接入已有 geoid 模型并传播其不确定度。
- 不做云端多人实时协同、移动端外业采集（V2 以后评估）。
- 不做自动绘制规范图签、自动生成全部测绘成果模板；先提供可配置报告骨架。

## 2. 总体架构

### 2.1 六层架构

```text
┌─────────────────────────────────────────────────────────────┐
│ L1 交互层  Web UI / 桌面壳                                   │
│   地图画布、点线角编辑、观测表、诊断面板、优化工作台、报告预览 │
├─────────────────────────────────────────────────────────────┤
│ L2 应用层  用例编排、事务、权限、任务调度                     │
│   ProjectAppService / DesignAppService / CalculationAppService│
│   OptimizationAppService / ExportAppService                   │
├─────────────────────────────────────────────────────────────┤
│ L3 领域层  实体、值对象、不变量、领域服务                     │
│   Project / Network / Point / Observation / Datum / Snapshot  │
│   定义 Repository、MapProvider、DemProvider、JobQueue 等端口  │
├─────────────────────────────────────────────────────────────┤
│ L4 计算内核  纯函数、无 I/O、可独立 CLI/批处理                │
│   geodesy / adjustment / reliability / optimization / terrain │
├─────────────────────────────────────────────────────────────┤
│ L5 基础设施  端口适配器                                       │
│   SQLite/PostGIS、MBTiles/PMTiles、GeoTIFF/DEM、文件存储、     │
│   任务队列、报告渲染、日志、缓存                               │
├─────────────────────────────────────────────────────────────┤
│ L6 平台层  打包、配置、升级、备份、监控                       │
│   Electron/Tauri 壳、Python sidecar、安装器、日志、健康检查    │
└─────────────────────────────────────────────────────────────┘
```

**依赖规则**：

- L1 只调用 L2 的 API/用例，不直接访问数据库或计算内核。
- L2 编排 L3 与 L4；负责事务边界、权限、任务状态，不实现数学公式。
- L3 不依赖 L4 的具体实现，只依赖 `core-types` 中的值对象；通过端口访问外部资源。
- L4 只依赖数值/地理库（`numpy/scipy/pyproj/rasterio` 等）与 `core-types`，输入 `DesignSnapshot`，输出 `CalculationResult`；禁止读数据库、发网络请求，文件读取由传入的数组/端口完成。
- L5 实现 L3 定义的端口；可以依赖具体数据库/地图库。
- L6 只负责运行环境，不承载业务逻辑。

这样做的直接收益：算法可用 pytest 单独跑；同一套内核可被 API、CLI、批处理、云端复用；替换 SQLite/PostGIS 或地图源不影响数学代码。

### 2.2 模块划分与包结构

| 模块 | 职责 | 关键接口/输出 |
|---|---|---|
| `core-types` | ID、单位、角度、CRS、协方差、结果、错误码等值对象 | `Covariance`, `PointRef`, `ObservationRef`, `ResultEnvelope` |
| `geodesy` | 坐标转换、投影归算、尺度因子、曲率/折光、方位角 | `ProjectionService`, `ReductionPipeline` |
| `network` | 网构建、连通性、参数排序、观测图、候选集 | `NetworkBuilder`, `ParameterIndex` |
| `map` | 地图资源、配准、瓦片、图层、覆盖检查 | `MapService`, `RegistrationService` |
| `adjustment` | 线性化、法方程、白化、SVD/QR、协方差 | `AdjustmentEngine.solve(snapshot)` |
| `reliability` | `Qv`、`R`、`r_i`、MDB、外部可靠性、w-test | `ReliabilityEngine.analyze(...)` |
| `optimization` | 贪心、局部搜索、MICP、A/D/E、成本模型 | `Optimizer.optimize(problem)` |
| `terrain` | DEM 采样、剖面、通视、曲率折光 | `VisibilityService.profile(...)` |
| `application` | 工程、设计、计算、比较、导入导出用例 | `*AppService` |
| `infrastructure` | DB、瓦片、DEM、队列、报告、文件 | `*Repository`, `*Provider` |
| `api` | REST/OpenAPI、SSE、鉴权、错误映射 | `/api/v1/...` |
| `web` | React 前端、地图、表格、图表 | SPA |
| `worker` | 异步计算进程/线程池 | `run_job(job_id)` |

建议的仓库结构：

```text
repo/
├─ backend/
│  ├─ app/
│  │  ├─ core_types/
│  │  ├─ domain/
│  │  ├─ engine/
│  │  │  ├─ geodesy/
│  │  │  ├─ adjustment/
│  │  │  ├─ reliability/
│  │  │  ├─ optimization/
│  │  │  └─ terrain/
│  │  ├─ application/
│  │  ├─ infrastructure/
│  │  ├─ api/
│  │  └─ worker/
│  ├─ tests/
│  │  ├─ unit/
│  │  ├─ golden/
│  │  ├─ integration/
│  │  └─ performance/
│  └─ pyproject.toml
├─ frontend/
│  ├─ src/
│  │  ├─ features/map/
│  │  ├─ features/network/
│  │  ├─ features/diagnostics/
│  │  ├─ features/optimization/
│  │  └─ shared/
│  └─ package.json
├─ fixtures/
│  ├─ section13_base.json
│  ├─ section13_added.json
│  └─ gnss_leveling/
└─ docs/
   ├─ adr/
   ├─ api/
   └─ user-guide/
```

### 2.3 关键数据流

```text
用户编辑
  → 命令（带 expected_version）
  → 领域校验（几何、单位、外键、精度参数）
  → 事务写入（点/观测/约束）
  → 版本号 +1，标记 stale
  → 创建 DesignSnapshot（规范化 JSON + SHA-256）
  → 提交计算任务（幂等键 = snapshot_hash + engine_version）
  → Worker 调用 AdjustmentEngine / ReliabilityEngine
  → 结果写入 calculation（含 diagnostics）
  → 仅当当前 snapshot_hash 仍匹配，发布为“最新”
  → 前端通过 SSE 收到进度/完成事件
```

**关键点**：

- 快照必须**规范化**：字段排序、数值格式、单位、参数顺序、观测顺序固定，确保哈希稳定。
- 计算任务幂等：同一 `snapshot_hash + engine_version + options_hash` 直接复用结果。
- 结果不可变：修正错误应生成新快照/新计算，不能原地改历史结果。
- 发布采用乐观并发：`If-Match`/`expected_version` 冲突返回 409。

### 2.4 运行形态与部署

**MVP：本地桌面应用**

- 外壳：Electron（成熟、Python sidecar 集成简单）或 Tauri 2（安装包更小，但引入 Rust）。MVP 建议 Electron，后续可替换外壳，业务层不变。
- 后端：Python 3.12 + FastAPI，`uvicorn` 绑定 `127.0.0.1` 随机端口；桌面壳启动/停止 sidecar。
- 数据库：SQLite（WAL 模式），空间扩展可用 SpatiaLite；工程资源目录与数据库同包。
- 地图：本地 MBTiles/PMTiles 读取 + FastAPI 瓦片端点；前端 MapLibre GL JS 渲染。兼容 XYZ/TMS，MBTiles 行号按 `2^z−1−y` 转换；PBF 原始字节与 gzip 头按原方案处理；缺失瓦片返回明确的空语义。
- 计算：独立 worker 进程池（默认 2～4 个），避免阻塞 API；大任务可取消。
- 报告：本地渲染 HTML/PDF/DOCX，不依赖外网。
- 离线资源：字体、图标、样式、模板、PROJ/GDAL 数据随安装包分发；运行时禁止依赖 CDN；地图/DEM 缺失时给出资源检查清单。

**V2：服务器模式（可选）**

- 同一套 API 部署到内网服务器；PostgreSQL/PostGIS 替换 SQLite；Redis/RQ 或 Celery 替换本地队列；对象存储保存矩阵/报告；OIDC + RBAC。
- 桌面端与服务器端共用前端与计算内核，仅基础设施适配不同。

### 2.5 并发、版本与幂等

| 机制 | 设计 |
|---|---|
| 乐观锁 | 每个聚合根有 `version`；更新带 `expected_version`，冲突 409 |
| 快照 | `design_snapshot` 只插入不更新；`snapshot_hash` 唯一索引 |
| 任务状态 | `queued → running → succeeded / failed / canceled`；超时自动失败 |
| 幂等 | `Idempotency-Key` 或 `snapshot_hash + engine_version + options_hash` |
| 取消 | 任务内检查取消令牌；线性代数分块间检查；已产生临时文件清理 |
| 事件 | SSE `/events` 推送 `job.progress`、`job.completed`、`job.failed` |
| 失败恢复 | 重启后把 `running` 标记为 `interrupted`；可从快照重跑 |
| 审计 | `audit_event` 记录创建、修改、删除、计算、导出、导入 |

### 2.6 架构决策记录（ADR）

| 编号 | 决策 | 理由 | 代价/替代 |
|---|---|---|---|
| ADR-01 | 计算内核用 Python + NumPy/SciPy | 大地测量、栅格、优化生态成熟；开发速度快；易与 GDAL/PROJ 集成 | 大规模性能不如 C++/Rust；用稀疏矩阵和可选原生扩展弥补 |
| ADR-02 | 计算只接受不可变快照 | 可复现、可缓存、可审计；避免“边算边改” | 快照序列化成本；用规范化 JSON + 压缩 |
| ADR-03 | 类型化观测表 + 方程注册表 | 核心类型强约束，扩展类型有统一入口 | 表较多；用 1:1 明细表和迁移管理 |
| ADR-04 | 平面/高程/GNSS 分网设计，预留联合 | 维度、基准、单位不同；先保证各自正确 | 联合平差推迟到 V2；接口预留 `combined` |
| ADR-05 | MVP 稠密 SVD，V2 稀疏 | 300 点内稠密足够；SVD 稳健、易诊断 | 大规模需稀疏 QR/Cholesky |
| ADR-06 | 本地 SQLite 优先，PostGIS 可选 | 离线、免运维、单文件工程包 | 多用户并发弱；服务器模式切换 |
| ADR-07 | REST + SSE，而非纯 WebSocket | 请求-响应清晰；SSE 足够推送进度；易调试/缓存 | 双向实时协作需 WebSocket |
| ADR-08 | 单位内部统一 SI | 避免毫米/米、度/弧度混用 | 边界转换多；用类型和测试约束 |

## 3. MVP 与扩展功能划分

### 3.1 划分原则

- MVP 必须**端到端闭环**：建工程 → 选点 → 建观测 → 算精度/可靠性 → 比较 → 导出/回读。
- MVP 必须**可信**：第 13 节黄金回归、可靠性公式、投影/基准显式校验通过。
- 不在 MVP 堆网型；GNSS、水准、通视、整数规划按“可独立验收的垂直切片”增量交付。
- 每个扩展都必须带数据模型、接口、测试、报告四件套，避免“只加算法不加产品”。

### 3.2 范围矩阵

| 能力 | MVP（0.9～1.0） | V1（1.x） | V2（2.x） | 说明 |
|---|---|---|---|---|
| 平面测角/测边/边角 | ✅ | 增强 | — | 含方向观测与定向未知数 |
| 固定/加权基准 | ✅ | — | — | 坐标伪观测 |
| 自由网/最小约束 | — | ✅ | — | 内约束/广义逆 |
| 随机模型 | 对角 + 分块 | 完整 VCV | 方差分量估计 | GNSS 需要完整 VCV |
| 精度指标 | ✅ | 方位角/高程扩展 | 3D | mp、椭圆、相对边 |
| 可靠性 `r_i`/MDB/外部 | ✅ | w-test 实测 | 稳健估计 | 可靠性是 MVP 核心差异点 |
| 粗差探测 | — | ✅ | 多粗差/稳健 | 需实测观测 |
| GNSS 基线向量网 | — | ✅ | 联合 3D | 3D ECEF/ENU、3×3 VCV |
| 水准/高程网 | — | ✅ | 联合 | 1D、路线/环、geoid |
| 三角高程 | — | ✅ | — | 曲率/折光改正 |
| DEM 通视 | — | ✅ | 批量/ skyline | 光学观测；GNSS 用天空视图 |
| 投影归算/变形 | 基础 | 完整 | 跨带/变形模型 | 尺度因子、高程归算 |
| 贪心优化 | — | ✅ | 增强 | 前向/后向/交换 |
| 整数规划/MICP | — | — | ✅ | 小规模精确/近似 |
| A/D/E 准则 | — | ✅（贪心评分） | ✅（凸优化） | 统一定义与缩放 |
| 成本模型 | 简单 | 完整 | 多资源 | 设站/方向/距离/公里 |
| 地图/配准/报告 | ✅ | 增强 | 多用户 | 离线优先 |
| 多用户/权限 | — | — | ✅ | 服务器模式 |

### 3.3 MVP 验收标准

1. 第 13 节基准/增补两套算例的点位、椭圆、边精度全部在 0.001 mm 内复现。
2. 第 13 节可靠性基准（`r_i`、MDB、外部影响）在声明假设下复现，误差 ≤ 1×10⁻³。
3. 任意合法平面网可输出 `Cx` 的对称性/正定性检查、秩、冗余数、条件数。
4. 删除必要基准约束、制造孤立点、非法协方差时，返回明确错误码并定位实体。
5. 工程可导出、回读，点 ID、观测拓扑、快照哈希、结果数值一致。
6. 断网环境下完成选点、计算、报告导出。
7. 300 点平面网计算 < 2 s（基准硬件），无内存泄漏。
8. 核心引擎单测覆盖率 ≥ 90%，第 13 节回归在 CI 中必跑。
9. 投影/归算已知点、已知边、尺度因子单测通过；`grid/ground` 模式切换不产生未声明的尺度跳变。

### 3.4 扩展触发条件

- 候选观测 > 150 或需要精确预算最优 → 启用整数规划/MICP；否则贪心 + 局部搜索足够。
- 项目含 GNSS 基线 → 必须启用 V1 的 3D 基线模块，不能把基线硬塞进 2D 距离观测。
- 测区跨度导致投影尺度变化 > 10 ppm 或跨带 → 启用完整投影归算/分区。
- 长边 > 1 km 的光学观测 → 默认启用曲率/折光改正与 DEM 通视。
- 需要回答“能发现多大粗差” → 必须输出 `r_i`/MDB，不能只给冗余数。

## 4. 数据模型调整

### 4.1 建模原则

1. **全局点身份 + 分网角色**：`point` 只存稳定身份与名称；`network_point` 存某网中的坐标、角色、坐标来源。避免同一物理点在平面网、GNSS 网、水准网中重复建三条记录。
2. **类型化观测**：`observation` 存公共字段（类型、启用、组、时间、精度模型），1:1 明细表存类型专属字段；用 `equation_type` 注册观测方程。
3. **协方差是一等公民**：`vcv_block` 存矩阵及其来源、单位、维数、正定性校验；观测可引用块，支持跨观测相关。
4. **快照不可变**：`design_snapshot` 存规范化 JSON + 哈希 + 参数顺序 + 观测顺序；计算只读快照。
5. **设计态/实测态分离**：`observation.measurement_status` 区分 `planned/measured/imported`；设计值可为空，实测值参与后验平差。
6. **来源可追溯**：坐标、观测、协方差、DEM、地图、投影参数都带 `source`、`version`、`accuracy`、`created_at`。
7. **单位显式**：数据库存 SI（米、弧度、秒），API 可带单位；禁止裸数字跨层传递。
8. **软删除 + 审计**：删除用 `deleted_at`，保留历史；审计表记录操作者与原因。

### 4.2 实体关系

```text
Project 1─N Network 1─N NetworkPoint N─1 Point
Network 1─N Observation 1─1 ObservationDetail
Observation N─1 VCVBlock
Network N─1 DatumDefinition 1─N DatumConstraint
Network 1─N DesignSnapshot 1─N Calculation 1─0..1 ReliabilityResult
Calculation 1─N ResultArtifact
OptimizationProblem 1─N OptimizationRun 1─N OptimizationCandidate
TerrainResource 1─N VisibilityResult
Project 1─N CoordinateOperation
Project 1─N CostModel
```

### 4.3 核心实体与调整点

| 实体 | 关键字段 | 相对原方案的调整 |
|---|---|---|
| `crs_definition` | id、epsg、wkt、type、axis_order、unit、area | 坐标参考独立成表；保留完整 WKT，不只存 EPSG |
| `project` | id、name、schema_version、crs_id、linear_unit、angle_unit、epoch、created_at | 引用 CRS；增加 epoch（历元）与版本 |
| `coordinate_operation` | id、project_id、method、source_crs、target_crs、params_json、accuracy、area、source | 记录投影/基准/变形转换的参数与精度，禁止“隐式转换” |
| `map_resource` | id、project_id、kind、path、format、crs、extent、min_zoom、max_zoom、version、license | 真实地图/地形图/瓦片包；版本与许可可追溯 |
| `map_layer` | id、resource_id、registration_id、display_order、opacity、style_json | 图层顺序、透明度、样式；替代原 MapLayer |
| `registration` | id、resource_id、model、control_points_json、params_json、residuals_json、check_points_json、accuracy、enabled | 仿射/多项式配准；独立检查点与残差 |
| `network` | id、project_id、kind、dimension、datum_id、status、version | 新增 `kind`：planar/gnss/leveling/combined；`dimension`：2/3/1 |
| `point` | id、project_id、label、description、created_at | 只存身份；坐标移到 `network_point` |
| `network_point` | network_id、point_id、E、N、H、X、Y、Z、role、coord_source、coord_vcv_id | 支持 2D/3D/1D；role：fixed/constrained/unknown/check；坐标协方差可引用 VCV |
| `observation` | id、network_id、type、equation_type、enabled、repeats、group_id、status、measured_at、vcv_id、meta_json、version | 去掉大量可空外键；公共字段统一；`repeats` 保留测回数，`group_id` 支持相关组 |
| `distance_obs` | observation_id、from_point、to_point、value_m、reduction_method、slope_distance_m、vertical_angle_rad、instrument_height_m、target_height_m | 明确坡距/平距/投影平距；保留归算参数 |
| `angle_obs` | observation_id、rear_point、station_point、front_point、value_rad、sigma_rad、direction_mode | 角度/方向分开；方向模式带定向未知数 |
| `direction_obs` | observation_id、station_point、target_point、value_rad、orientation_id、sigma_rad | 测站定向参数；避免与派生角重复 |
| `baseline_obs` | observation_id、from_point、to_point、dx、dy、dz、frame、vcv_id、session_id、solution_type、antenna_height_from/to | GNSS 核心；3×3 协方差；支持 ECEF/ENU |
| `leveling_obs` | observation_id、from_point、to_point、delta_h_m、route_id、length_km、sigma_mm_per_km、method | 水准/高程；支持路线与环 |
| `height_obs` | observation_id、point_id、height_m、height_type、sigma_m、source | GNSS 大地高/正常高/正高，显式类型 |
| `trig_height_obs` | observation_id、from_point、to_point、slope_distance_m、vertical_angle_rad、instrument_height_m、target_height_m、refraction_k | 三角高程；曲率/折光参数可追溯 |
| `constraint_obs` | observation_id、point_id、component、value、sigma、distribution | 坐标/高程伪观测；替代散落字段 |
| `vcv_block` | id、dimension、matrix_blob、unit、source、is_positive_definite、created_at | 完整/分块协方差；正定性校验 |
| `stochastic_model` | id、network_id、kind、sigma0、components_json、correlation_groups、version | 支持对角/分块/完整；记录 σ0 约定 |
| `datum_definition` | id、network_id、kind、rank、params_json、description | kind：fixed/weighted/minimal/free/helmert |
| `datum_constraint` | id、datum_id、point_id、component、value、sigma、enabled | 逐分量约束，便于诊断 |
| `design_snapshot` | id、network_id、hash、schema_version、engine_version、payload_json、created_at | 不可变；计算契约 |
| `calculation` | id、snapshot_id、status、options_hash、started_at、finished_at、diagnostics_json、result_path | 结果与快照/引擎/选项绑定 |
| `result_artifact` | id、calculation_id、kind、name、path、sha256、shape、dtype、unit | 大矩阵/报告/图件；避免 JSON 膨胀 |
| `reliability_result` | calculation_id、observation_id、r_i、mdb、mdb_unit、external_max_mm、external_point、w_test | 逐观测可靠性 |
| `optimization_problem` | id、network_id、objective、candidate_set_json、constraints_json、cost_model_id、budget | 优化输入 |
| `optimization_run` | id、problem_id、algorithm、status、solver、gap、started_at、finished_at | 运行记录 |
| `optimization_candidate` | run_id、rank、selected_obs_json、cost、metrics_json、feasible、explanation | 推荐方案与解释 |
| `cost_model` | id、project_id、version、items_json、currency | 设站/方向/距离/公里/交通 |
| `terrain_resource` | id、project_id、path、format、crs、vertical_datum、resolution_m、surface_type、extent | DSM/DTM、来源、精度 |
| `visibility_result` | id、from_point、to_point、profile_json、min_clearance_m、blocked、curvature_k、refraction_k、dem_version | 通视结果可缓存 |
| `audit_event` | id、project_id、actor、action、entity_type、entity_id、before_json、after_json、at | 审计 |

### 4.4 观测类型与方程注册

| `equation_type` | 观测值 | 未知参数 | 方程/说明 | VCV | 阶段 |
|---|---|---|---|---|---|
| `distance` | 平距/坡距 | 两端 E,N | `s = norm(P_j − P_i)`；坡距需归算 | 1×1 | MVP |
| `direction` | 方向值 | 测站 E,N + 定向 ω | `α_jk − ω_j` | 1×1 | MVP |
| `angle` | 水平角 | 三点 E,N | `α_jk − α_ji` | 1×1 | MVP |
| `baseline` | ΔX/ΔY/ΔZ 或 ΔE/ΔN/ΔU | 两端 3D 坐标 | `X_j − X_i` | 3×3（可跨基线相关） | V1 |
| `leveling` | 高差 | 两端高程 | `H_j − H_i` | 1×1（按 km） | V1 |
| `height` | 大地高/正常高 | 单点高程 | `H_i` 伪观测 | 1×1 | V1 |
| `trig_height` | 斜距+竖直角 | 两端高程 | 含曲率/折光 | 1×1 | V1 |
| `constraint` | 坐标/高程约束 | 对应分量 | 伪观测 | 1×1 或块 | MVP |

### 4.5 关键表结构（SQLite 摘要）

```sql
CREATE TABLE network (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES project(id),
  kind TEXT NOT NULL CHECK (kind IN ('planar','gnss','leveling','combined')),
  dimension INTEGER NOT NULL CHECK (dimension IN (1,2,3)),
  datum_id TEXT,
  status TEXT NOT NULL DEFAULT 'draft',
  version INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);

CREATE TABLE point (
  id TEXT PRIMARY KEY,
  project_id TEXT NOT NULL REFERENCES project(id),
  label TEXT NOT NULL,
  description TEXT,
  deleted_at TEXT
);

CREATE UNIQUE INDEX ux_point_label_alive
  ON point(project_id, label) WHERE deleted_at IS NULL;

CREATE TABLE network_point (
  network_id TEXT NOT NULL REFERENCES network(id),
  point_id TEXT NOT NULL REFERENCES point(id),
  e REAL, n REAL, h REAL,
  x REAL, y REAL, z REAL,
  role TEXT NOT NULL CHECK (role IN ('fixed','constrained','unknown','check')),
  coord_source TEXT,
  coord_vcv_id TEXT REFERENCES vcv_block(id),
  PRIMARY KEY (network_id, point_id)
);

CREATE TABLE observation (
  id TEXT PRIMARY KEY,
  network_id TEXT NOT NULL REFERENCES network(id),
  type TEXT NOT NULL,
  equation_type TEXT NOT NULL,
  enabled INTEGER NOT NULL DEFAULT 1,
  repeats INTEGER NOT NULL DEFAULT 1 CHECK (repeats > 0),
  group_id TEXT,
  status TEXT NOT NULL DEFAULT 'planned'
    CHECK (status IN ('planned','measured','imported','disabled')),
  vcv_id TEXT REFERENCES vcv_block(id),
  meta_json TEXT NOT NULL DEFAULT '{}',
  version INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE distance_obs (
  observation_id TEXT PRIMARY KEY REFERENCES observation(id) ON DELETE CASCADE,
  from_point TEXT NOT NULL,
  to_point TEXT NOT NULL,
  value_m REAL,
  reduction_method TEXT NOT NULL DEFAULT 'horizontal'
    CHECK (reduction_method IN ('horizontal','slope','grid','geodetic')),
  slope_distance_m REAL,
  vertical_angle_rad REAL,
  instrument_height_m REAL,
  target_height_m REAL
);
-- angle_obs / direction_obs / baseline_obs / leveling_obs / height_obs 同理，1:1 明细

CREATE TABLE vcv_block (
  id TEXT PRIMARY KEY,
  dimension INTEGER NOT NULL,
  matrix_blob BLOB NOT NULL,
  unit TEXT NOT NULL,
  source TEXT,
  is_positive_definite INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL
);

CREATE TABLE design_snapshot (
  id TEXT PRIMARY KEY,
  network_id TEXT NOT NULL REFERENCES network(id),
  hash TEXT NOT NULL UNIQUE,
  schema_version TEXT NOT NULL,
  engine_version TEXT NOT NULL,
  payload_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE calculation (
  id TEXT PRIMARY KEY,
  snapshot_id TEXT NOT NULL REFERENCES design_snapshot(id),
  status TEXT NOT NULL CHECK (status IN ('queued','running','succeeded','failed','canceled')),
  options_hash TEXT NOT NULL,
  diagnostics_json TEXT,
  result_path TEXT,
  started_at TEXT,
  finished_at TEXT
);

CREATE TABLE reliability_result (
  calculation_id TEXT NOT NULL REFERENCES calculation(id),
  observation_id TEXT NOT NULL,
  r_i REAL NOT NULL,
  mdb REAL,
  mdb_unit TEXT,
  external_max_mm REAL,
  external_point_id TEXT,
  w_test REAL,
  PRIMARY KEY (calculation_id, observation_id)
);
```

> 说明：SQLite 不支持完整 `CHECK` 约束表达矩阵正定性，正定性在应用层用 Cholesky 校验；`matrix_blob` 采用 `float64` 小端连续存储，另存 `dimension/unit`，避免 JSON 浮点膨胀。

### 4.6 DesignSnapshot 结构示例

```json
{
  "schema_version": "2.0",
  "snapshot_id": "01J...",
  "network": {
    "id": "net-1",
    "kind": "planar",
    "dimension": 2,
    "crs": {"type": "local_engineering", "epsg": null, "wkt_hash": "..."},
    "datum": {"kind": "fixed", "constraints": [{"point": "A", "component": "E"}, {"point": "A", "component": "N"}, {"point": "B", "component": "E"}, {"point": "B", "component": "N"}]}
  },
  "parameter_order": ["C:E", "C:N", "D:E", "D:N"],
  "points": [
    {"id": "A", "label": "A", "e": 0.0, "n": 0.0, "role": "fixed"},
    {"id": "B", "label": "B", "e": 100.0, "n": 0.0, "role": "fixed"},
    {"id": "C", "label": "C", "e": 0.0, "n": 100.0, "role": "unknown"},
    {"id": "D", "label": "D", "e": 100.0, "n": 100.0, "role": "unknown"}
  ],
  "observations": [
    {"id": "d1", "type": "distance", "from": "A", "to": "C", "value_m": 100.0,
     "sigma": {"model": "a_b", "a_m": 0.002, "b_ppm": 2.0}},
    {"id": "a1", "type": "angle", "rear": "C", "station": "A", "front": "B",
     "value_rad": 1.5707963267948966, "sigma_rad": 4.84813681109536e-06}
  ],
  "stochastic_model": {"kind": "diagonal", "sigma0": 1.0, "groups": []},
  "engine": {"name": "adjustment", "version": "1.0.0", "options": {"rank_tol": null, "confidence": 0.95}}
}
```

> 生产实现中 `snapshot_id`、坐标、观测值由服务端生成；示例仅表达结构。`payload_json` 必须做规范化序列化（键排序、浮点格式化）后再哈希。

### 4.7 迁移与兼容

- 使用 Alembic 管理 `schema_version`；每个版本提供 `upgrade()`/`downgrade()`，迁移前自动备份 SQLite。
- 旧模型映射：
  - `Project` → `project`（保留 id）。
  - `Point` → `point` + `network_point`（按原 role 生成平面网节点）。
  - `Observation` → `observation` + 对应明细；原 `distance/angle` 字段拆到 `distance_obs/angle_obs`。
  - `PrecisionModel` → `stochastic_model` + `distance_obs.sigma`/`angle_obs.sigma_rad`。
  - `Scenario` → `design_snapshot`（原 `input_hash` 保留为 `legacy_hash`）。
  - `Calculation` → `calculation`（旧结果只读，标记 `engine_version=legacy`）。
- 导入旧工程时执行完整校验：外键、单位、CRS、协方差正定性、观测拓扑；校验失败给出逐条错误，不静默修复。
- 导出保持向后兼容：提供 `schema_version=1.x` 的降级导出（只含平面边角网字段），并明确告知丢失的扩展信息。

### 4.8 数据质量规则

| 规则 | 处理 |
|---|---|
| 数值有限性 | 拒绝 NaN/Inf；DB 层 REAL + 应用层校验 |
| 标准差/方差 | 必须 > 0；协方差矩阵对称、正定（Cholesky） |
| 几何退化 | 同点、零长度、三点共线、近 0°/180° 角给出警告或错误 |
| 单位 | 内部 SI；API/报告带单位；禁止隐式换算 |
| 外键 | 同工程/同网校验；跨工程引用拒绝 |
| 快照 | 只插入；哈希唯一；payload 规范化 |
| 版本 | 更新带 `expected_version`；冲突 409 |
| 删除 | 软删除；关联观测级联提示；审计记录 |
| 大矩阵 | 不入 JSON；走 `result_artifact` 文件 + 元数据 |

## 5. 数学与算法设计

### 5.1 统一观测模型与解算流程

#### 5.1.1 模型

设观测向量为 `l`，未知参数为 `x`，观测方程为：

```text
l + v = f(x)
```

在近似值 `x0` 处线性化，令 `δx = x − x0`，`A = ∂f/∂x |x0`，`w = l − f(x0)`，则：

```text
v = A δx − w
```

最小二乘解：

```text
N = Aᵀ Ql⁻¹ A
δx = N⁻¹ Aᵀ Ql⁻¹ w
Qxx = N⁻¹
Cx = σ0² Qxx        （Ql 为相对协方差时）
Cx = Qxx            （Ql 为绝对协方差、σ0²=1 时）
```

其中 `Ql` 是观测协方差（即原方案的 `Cl`，不是权阵），`σ0²` 是单位权方差。**必须明确当前处于哪一种约定**，并在结果中记录 `covariance_mode = absolute | relative`，防止把 `σ0²` 重复乘入。

#### 5.1.2 设计态与实测态

| 模式 | 输入 | 计算 | 输出 |
|---|---|---|---|
| 设计态（先验） | 近似坐标、计划观测、先验 `Ql`、基准 | 只算 `A`、`N`、`Qxx`；不需要 `l` | 先验精度、可靠性、优化指标 |
| 实测态（后验） | 近似坐标、实测 `l`、`Ql`、基准 | 迭代求解 `δx`、残差 `v`、`σ0²`、w-test | 平差坐标、后验精度、粗差诊断 |
| 混合态 | 部分实测、部分计划 | 实测参与解算，计划只参与设计矩阵 | 带不确定性的方案评估 |

设计态与实测态共用 `A`、`N`、`Qxx` 代码路径，但**结果字段分开**：`prior_precision` 与 `posterior_precision` 不混用；报告必须标注“设计精度”或“实测精度”。

#### 5.1.3 解算步骤

1. **构建参数索引**：按 `parameter_order` 为每个未知分量分配列号；固定点不占列；约束点占列并附伪观测。
2. **计算近似观测值**：按当前坐标计算距离、方位角、角度、基线向量、高差。
3. **组装设计矩阵 `A`**：逐观测调用方程注册表；只写非零列；记录观测行号。
4. **组装 `Ql`**：对角/分块/完整 VCV；校验对称正定；单位统一为米/弧度。
5. **白化**：`Ql = L Lᵀ`，`Aw = L⁻¹A`，`lw = L⁻¹w`。
6. **秩与条件检查**：SVD/QR；检查 `rank(A)`、奇异值范围、零空间；基准缺陷在此暴露。
7. **求解**：`δx`；迭代直到 `||δx||` 小于阈值（实测态）；设计态一次线性化即可。
8. **协方差**：`Qxx`；按需提取点位/边/相对位置协方差；避免显式求逆。
9. **残差与后验**：实测态计算 `v`、`σ0²`、w-test；设计态跳过。
10. **可靠性**：由 `Qv`、`R` 计算 `r_i`、MDB、外部可靠性；与精度结果一起发布。
11. **诊断**：秩、条件数、最大残差、最弱点、最弱边、错误/警告列表。
12. **序列化**：结果、参数顺序、观测顺序、引擎版本、快照哈希写入 `calculation`。

#### 5.1.4 约束处理

- **固定点**：从参数向量删除对应列；近似坐标仍参与 `f(x0)`。
- **加权约束**：增加伪观测行，如 `E_i = E_i^known + v`，方差取已知协方差；可把 2×2/3×3 块作为一个相关组。
- **最小约束**：选择刚好消除秩亏的约束（如平面网固定一点 + 一条方位 + 一条边长），并记录选择理由。
- **自由网**：使用广义逆/内约束；报告基准定义；不同基准下的 `Qxx` 不可直接比较。
- **不等式约束**：MVP 不做；优化阶段的可靠性/精度门槛通过候选筛选或后验检查处理。

#### 5.1.5 非线性与迭代

- 设计态：近似坐标通常由地图选点得到，误差可能较大；建议先做一次“几何检查”，若角度接近 0°/180°、边长接近 0、三角形极度狭长，先提示用户。
- 实测态：Gauss-Newton 迭代；每轮更新 `x0`、`A`、`w`；收敛阈值按坐标 0.1 mm、角度 0.001″ 量级配置；最多 20 次，失败返回 `NON_CONVERGENCE`。
- 粗差存在时，普通最小二乘可能不收敛或残差被掩盖；先做稳健初值或人工剔除，再进入数据 snooping。

#### 5.1.6 常用观测的偏导（设计矩阵系数）

| 观测 | 方程 | 对点 j 的偏导 | 对点 i 的偏导 |
|---|---|---|---|
| 距离 | `s = sqrt(ΔE² + ΔN²)` | `∂s/∂E_j = ΔE/s`，`∂s/∂N_j = ΔN/s` | 取相反数 |
| 方向/方位 | `α = atan2(ΔE, ΔN)` | `∂α/∂E_j = ΔN/s²`，`∂α/∂N_j = −ΔE/s²` | 取相反数 |
| 水平角 | `β = α_jk − α_ji` | 由两条方向行相减；同一测站贡献相加 | 三角点之外为 0 |
| GNSS 基线 | `l = X_j − X_i` | `+I₃` | `−I₃` |
| 水准 | `Δh = H_j − H_i` | `+1` | `−1` |
| 高度伪观测 | `H_i = H_i^known` | `+1` | — |

其中 `ΔE = E_j − E_i`、`ΔN = N_j − N_i`、`s² = ΔE² + ΔN²`。角度/方向以弧度参与求导；跨 0° 时按包裹差值处理。若含测站定向未知数 `ω`，方向行再加 `−1` 到 `ω` 列；由方向派生角度时，不要把原方向与派生角同时作为独立观测。

### 5.2 坐标、投影与归算

#### 5.2.1 坐标框架

系统显式支持四类坐标：

| 框架 | 表达 | 用途 |
|---|---|---|
| 地理坐标 | 经度 λ、纬度 φ、椭球高 h | GNSS、DEM、地图配准 |
| 地心地固 ECEF | X、Y、Z | GNSS 基线平差 |
| 局部 ENU | E、N、U | 工程平面、通视、短边归算 |
| 投影平面 | E、N（加高程 H） | 平面控制网设计、成果表达 |

禁止“看起来都是米”就混用。每个 `network` 必须声明 `crs`、`projection`、`height_type`、`epoch`；每个坐标转换必须记录 `coordinate_operation`。

#### 5.2.2 距离归算管线

对地面斜距 `D`、竖直角 `α`、仪器高 `i`、目标高 `t`：

```text
1) 斜距 → 地面平距：s_g = D cos α
   （或用两端高差：s_g = sqrt(D² − Δh²)）
2) 地面平距 → 椭球面平距：s_e ≈ s_g · R/(R + H_m)
   其中 H_m 为测线平均大地高，R 取当地平均曲率半径；
   高精度实现用椭球法线曲率半径，不用单一 R。
3) 椭球面平距 → 投影平面：s_p = s_e · k_prj
   k_prj 为投影尺度因子，取两端点平均值或沿线积分；
4) 综合尺度：k_comb = s_p / s_g ≈ k_prj · R/(R + H_m)
```

对方向/角度：

```text
网格方位角 = 真北方位角 − 子午线收敛角 γ
```

`γ` 的符号随投影和象限定义不同，系统必须把符号约定写入 `ProjectionService` 的契约，并用已知点/已知方位角做单元测试；不得在 UI 层临时加减。

**实现建议**：优先调用 PROJ（`pyproj`）做 CRS 转换和尺度因子计算；对 Gauss-Krüger/UTM 提供 `point_scale_factor(lon, lat)`、`convergence(lon, lat)`、`grid_to_ground(...)` 封装。设计阶段可用近似公式，成果阶段用严格公式，二者在报告中注明。

#### 5.2.3 三种平面模式

| 模式 | 坐标含义 | 适用 | 注意 |
|---|---|---|---|
| `grid`（默认） | 投影平面坐标，距离已归算到投影面 | 常规工程控制网、与国家/地方坐标衔接 | 必须记录投影、中央经线、尺度因子 |
| `ground` | 测区平均高程面的地面平距坐标 | 小范围、高海拔、要求“地面米” | 与国家坐标转换需显式尺度/平移 |
| `local_enu` | 以测区原点建立的 ENU 切平面 | GNSS、通视、短边、三维 | 远离原点时需重新设站/分区 |

**选择规则**：

- 测区跨度小、精度要求一般：`grid`，直接使用项目 CRS。
- 高海拔或投影变形大：`ground`，并记录“地面坐标系”与国家坐标系的转换参数。
- GNSS 基线/三维：`local_enu` 或 ECEF；平面成果再投影。
- 同一工程禁止把 `grid` 与 `ground` 观测混算而不加尺度改正。

#### 5.2.4 变形检查与阈值

计算网内 `k_prj` 的变化范围、`k_comb` 的变化范围、子午线收敛角范围：

```text
Δk_prj = max(k_prj) − min(k_prj)
```

建议默认提示阈值（可按项目精度目标配置）：

- `|k_prj − 1| > 10 ppm` 或 `Δk_prj > 10 ppm`：提示投影变形不可忽略。
- 综合尺度偏差 `|k_comb − 1| > 25 ppm`（约 2.5 cm/km）：建议改用地面坐标/分区/低变形投影。
- 跨带或 `γ` 变化 > 30′：提示分区或改用 3D/ENU。
- 测区边缘与中央子午线距离过大：提示重新选择中央经线。

超过阈值不是“报错禁止计算”，而是**强制警告 + 报告中记录**；是否接受由项目精度目标决定。

#### 5.2.5 跨带、变形与历元

- **跨带**：优先按带分区建模，分别平差后通过公共点转换；或采用 3D/ENU 统一处理。禁止直接把两带坐标当同一平面。
- **坐标变形/地壳运动**：支持 `coordinate_operation` 链（相似变换、仿射、七参数、格网改正）；记录历元、速度场/变形模型、精度；不支持时明确标记“未改正”。
- **高程基准**：区分大地高 `h`、正高 `H`、正常高 `H_N`；`H = h − N`（N 为 geoid 起伏）。高程观测必须带 `height_type`；跨基准比较前先转换。
- **投影参数**：保存 EPSG 或完整 WKT、中央经线、原点、比例因子、假东/假北；不只存一个 EPSG 代码。

#### 5.2.6 归算参数与成果追溯

每条距离观测保存：原始斜距/平距、竖直角、仪器高、目标高、归算方法、使用的高程、投影参数版本、归算后的 `value_m`。报告中给出“从 raw 到 model”的链路，便于复核。

#### 5.2.7 地图/地形图配准

扫描地形图或无名影像进入工程前，需建立像素坐标 `(u,v)` 到工程坐标 `(E,N)` 的仿射模型：

```text
E = a0 + a1·u + a2·v
N = b0 + b1·u + b2·v
```

- 至少 3 个不共线同名点可解 6 个参数；工程应用建议 ≥6 个，覆盖四角与中部。
- 对 k 个配准点构造 `k×3` 矩阵 `M`（每行 `[1,u,v]`），分别对 E、N 做最小二乘；有权时用加权最小二乘。
- 用 QR/SVD 检查退化（点共线、分布过窄）；输出参数协方差与条件数。
- 逐点残差 `ΔE、ΔN`；平面残差 RMS 可用 `sqrt(Σ(ΔE²+ΔN²)/k)`，并报告最大残差。
- 独立检查点不参与求解，单独报告 RMS/最大误差；超过项目阈值时阻止发布。
- 记录像素原点、v 轴方向、单位、源 CRS、配准模型、控制点/检查点、适用范围；图像切换时按工程坐标重定位。

### 5.3 基准与秩

#### 5.3.1 基准类型

| 类型 | 做法 | 协方差 | 适用 |
|---|---|---|---|
| `fixed` | 删除固定点未知数 | 固定点协方差为 0 | 已知点可靠、设计阶段常用 |
| `weighted` | 坐标伪观测，带 1×1/2×2/3×3 协方差 | 保留未知数，先验协方差进入 `Ql` | 已知点有精度但非精确 |
| `minimal` | 施加刚好消除秩亏的约束 | 取决于约束 | 自由网/缺少足够已知点 |
| `free` | 内约束或广义逆 | 基准相关，需报告 | 变形监测、网形分析 |
| `helmert` | 七参数转换 + 公共点 | 转换参数协方差传播 | 多期/GNSS/不同坐标系 |

#### 5.3.2 秩亏诊断

平面自由网的基准缺陷数量取决于观测类型：角度对尺度不变，纯测角网通常有 4 个缺陷（2 平移、1 旋转、1 尺度）；距离和边角网由距离提供尺度，通常有 3 个缺陷（2 平移、1 旋转），但仍需方位/已知点消除旋转。GNSS 三维自由网为 7 个（3 平移、3 旋转、1 尺度）；水准网为 1 个（高程平移）。实际数量以 SVD 零空间为准，不能只按类型计数。

诊断方法：

1. 对 `A` 或 `Aw` 做 SVD，检查接近零的奇异值数量。
2. 提取零空间向量 `v_k`，观察其对应的坐标分量模式：整体平移、绕某点旋转、整体缩放。
3. 检查观测图连通性：孤立点、孤立子网、只有单一连接的点。
4. 检查约束是否重复/矛盾：同一分量多个固定值、协方差奇异。
5. 返回 `RANK_DEFICIENT`，并给出“缺哪种基准”的可读诊断，而不是只报“矩阵奇异”。

#### 5.3.3 自由网与基准相关协方差

自由网解不唯一。实现上：

- 使用 `N⁺`（Moore-Penrose 伪逆）或加入内约束 `G` 后求解；
- 明确报告基准：原点、方位、尺度如何定义；
- `Qxx` 是基准相关的，不能与固定基准结果直接比较；
- 相对精度/相对椭圆在自由网中通常比绝对坐标更有意义。

#### 5.3.4 GNSS 与水准基准

- GNSS：至少 1 个固定三维基准站（或 3 个分量约束）；无固定站时用最小约束/自由网；多期用 Helmert。
- 水准：至少 1 个固定高程基准点；闭合环提供检核但不提供基准；无固定点时秩亏 1。
- 平面 + 高程联合：平面基准与高程基准分别定义，除非做 3D 联合；不要用一个点的三维坐标同时“固定”平面和高程而不说明。

### 5.4 可靠性指标

可靠性回答两个问题：**这个网能发现多大的粗差？发现不了时，会对坐标造成多大影响？**

#### 5.4.1 多余观测分量

定义：

```text
Qv = Ql − A Qxx Aᵀ
R  = Qv Ql⁻¹ = I − A Qxx Aᵀ Ql⁻¹
r_i = R_ii = (Qv Ql⁻¹)_ii
```

性质：

- `trace(R) = m − rank(A)`；满秩时 `= m − u`，即冗余数。
- 独立观测时 `r_i = qv_ii / σ_i² = 1 − a_iᵀ Qxx a_i / σ_i²`，且 `0 ≤ r_i ≤ 1`。
- 相关观测时 `R` 不是对称矩阵，`r_i` 仍按对角元定义，但可能超出 `[0,1]`；解释时要结合 `R` 的整体性质，不能简单说“负冗余”。
- `r_i` 接近 0：该观测几乎不被检核，粗差会“直接进坐标”；`r_i` 接近 1：该观测主要由其他观测检核。
- `r_i` 小不等于精度差；它衡量的是**检核能力**，必须与 `mp`、MDB 一起看。

#### 5.4.2 内部可靠性（MDB）

对第 i 个观测做 w-test：

```text
u = Ql⁻¹ v
w_i = u_i / sqrt((Ql⁻¹ Qv Ql⁻¹)_ii)
```

原假设下 `w_i ~ N(0,1)`。若该观测存在粗差 `∇_i`，非中心参数为：

```text
δ_i = ∇_i · sqrt((Ql⁻¹ Qv Ql⁻¹)_ii)
```

给定显著性 `α`、检验功效 `1−β`，非中心参数门槛：

```text
λ0 = (z_{1−α/2} + z_{1−β})²
```

则最小可探测粗差：

```text
∇0_i = sqrt(λ0 / (Ql⁻¹ Qv Ql⁻¹)_ii)
```

独立观测时简化为：

```text
∇0_i = σ_i · sqrt(λ0 / r_i)
```

常用 `λ0`：

| α（双侧） | 功效 | `z_{1−α/2}` | `z_{1−β}` | `λ0` |
|---|---|---|---|---|
| 0.05 | 0.80 | 1.960 | 0.842 | 7.849 |
| 0.05 | 0.90 | 1.960 | 1.282 | 10.507 |
| 0.05 | 0.95 | 1.960 | 1.645 | 12.995 |

`∇0_i` 的单位与观测相同：距离为 mm，角度为角秒，基线为 mm/ppm（按分量）。报告时同时给出“观测值单位”和“相对其中误差的倍数”（`∇0_i/σ_i`）。

若 `r_i` 接近 0（例如 <1×10⁻⁶），MDB 趋于无穷，说明该观测几乎不可检核；此时报告 `undetectable`，不要输出一个巨大的有限值误导用户。

#### 5.4.3 外部可靠性

若 `∇0_i` 未被发现，它对参数的影响：

```text
δx_i = Qxx Aᵀ Ql⁻¹ e_i ∇0_i
```

独立观测时：

```text
δx_i = Qxx a_i ∇0_i / σ_i²
```

报告：

- 受影响最大的点位与分量；
- `max |δx_i|`（mm）与 `||δx_i||`（mm）；
- 对关键边/相对位置的影响（可选）；
- 多个粗差同时存在时不能用单粗差结果简单相加，需模拟或稳健估计。

#### 5.4.4 粗差可探测性与数据 snooping

- 设计阶段没有实测残差，只能给 MDB；不能声称“已经发现粗差”。
- 实测阶段：
  1. 平差，计算 `w_i`；
  2. 取 `|w_i|` 最大者，与 `z_{1−α/2}`（或 t 分布）比较；
  3. 超限则标记/剔除，重算；
  4. 重复直到无超限，或达到最大迭代次数；
  5. 记录每次剔除的观测、检验量、`σ0²` 变化。
- 多重检验：观测多时建议 Bonferroni 校正 `α' = α/m`，或在报告中说明未校正的风险。
- 遮蔽/淹没：多个粗差可能互相掩盖；数据 snooping 不是万能的，需结合稳健估计和人工核查。
- 稳健估计（V1 后期）：Huber/IGG3 权函数、L1 平差；输出稳健权、残差、异常观测；稳健结果不能替代可靠性指标，二者互补。

#### 5.4.5 可靠性阈值与报告

阈值应可配置，并按项目精度目标设定。建议默认提示值：

| 指标 | 提示阈值 | 说明 |
|---|---|---|
| `r_i` | < 0.10 | 检核能力弱；关键观测可要求 ≥ 0.2～0.3 |
| `MDB_i / σ_i` | > 5 | 只能发现 5 倍中误差以上的粗差 |
| 外部可靠性 | > 0.5 × 目标 `mp` | 未发现粗差可能显著污染坐标 |
| `abs(w_i)` | > 2.5～3.0 | 实测阶段；按 α 配置 |

这些不是规范强制值，而是“设计警示线”；报告必须列出所用阈值和理由。

#### 5.4.6 第 13 节可靠性回归基准

在 `λ0=7.849（α=0.05，功效 0.80）`、独立观测、`σ0=1` 假设下，按上述公式复算：

**基准方案（7 观测，4 未知，冗余 3）**

| 观测 | σ | `r_i` | MDB | 外部最大影响/mm |
|---|---|---|---|---|
| AC | 2.010 mm | 0.3252 | 9.875 mm | 6.663 |
| BC | 2.020 mm | 0.6569 | 6.982 mm | 3.211 |
| AD | 2.020 mm | 0.6569 | 6.982 mm | 3.211 |
| BD | 2.010 mm | 0.3252 | 9.875 mm | 6.663 |
| CD | 2.010 mm | 0.8975 | 5.944 mm | 0.305 |
| ∠C-A-B | 1.000″ | 0.0692 | 10.653″ | 4.807 |
| ∠A-B-D | 1.000″ | 0.0692 | 10.653″ | 4.807 |

**增补角方案（8 观测，4 未知，冗余 4）**

| 观测 | σ | `r_i` | MDB | 外部最大影响/mm |
|---|---|---|---|---|
| AC | 2.010 mm | 0.6283 | 7.104 mm | 2.640 |
| BC | 2.020 mm | 0.8235 | 6.236 mm | 1.474 |
| AD | 2.020 mm | 0.8074 | 6.298 mm | 1.523 |
| BD | 2.010 mm | 0.6442 | 7.016 mm | 2.496 |
| CD | 2.010 mm | 0.8994 | 5.938 mm | 0.301 |
| ∠C-A-B | 1.000″ | 0.0842 | 9.657″ | 4.288 |
| ∠A-B-D | 1.000″ | 0.0722 | 10.423″ | 4.688 |
| ∠D-C-A | 1.000″ | 0.0408 | 13.864″ | 3.180 |

**解读**：增加一个角度后，点位精度改善（`mp` 从 1.716 mm 降到 1.310/1.287 mm），但新增角度的 `r_i` 仅 0.0408，MDB 反而较大；两个原角度的 MDB 仍约 10″。这说明“精度变好”不等于“可靠性变好”，优化目标必须同时考虑二者。该表应作为 V1 可靠性功能的黄金回归，容差建议 `r_i ±1×10⁻³`、MDB 相对误差 ±1×10⁻³、外部影响 ±0.002 mm。

### 5.5 精度指标与协方差传播

#### 5.5.1 点位精度

二维：

```text
σ_E = sqrt(Cp11)
σ_N = sqrt(Cp22)
m_p = sqrt(Cp11 + Cp22)
```

三维：

```text
m_3D = sqrt(trace(Cp))
m_H = sqrt(Cp11 + Cp22)      （水平）
σ_U = sqrt(Cp33)             （垂直）
```

报告同时给水平/垂直分量；GNSS 成果应区分 ECEF、ENU、投影平面三种协方差，并注明转换关系。

#### 5.5.2 误差椭圆/椭球

二维协方差特征分解：

```text
Cp = V diag(λ1, λ2) Vᵀ,  λ1 ≥ λ2
a = sqrt(λ1), b = sqrt(λ2)
方位角 = atan2(v_E, v_N) 归化到 [0, 180°)
```

置信度 `p` 的半轴：

```text
a_p = a · sqrt(χ²(2, p))
b_p = b · sqrt(χ²(2, p))
```

95% 时 `sqrt(χ²(2,0.95)) ≈ 2.448`；标准椭圆（39.35%）不乘系数。近圆椭圆（`|λ1−λ2|/λ1 < 1e-3`）的主轴方向标记为“不稳定”，不要给出确定方位。

三维误差椭球：对 3×3 协方差特征分解，半轴 `sqrt(λ_i)`；置信椭球用 `χ²(3,p)`。报告需说明是“标准椭球”还是“置信椭球”。

#### 5.5.3 相对精度

边长 `s_ij` 的梯度 `g_s` 只在两端点参数列非零：

```text
g_s = [∂s/∂E_i, ∂s/∂N_i, ∂s/∂E_j, ∂s/∂N_j]
σ_s² = g_s Cx g_sᵀ
相对精度 = σ_s / s = 1 : (s/σ_s)
```

两点相对位置：

```text
C_Δ = C_ii + C_jj − C_ij − C_ji
```

对 `C_Δ` 再做特征分解，得到相对误差椭圆。固定点按基准协方差补齐（固定点为零；加权约束用其先验协方差）。

#### 5.5.4 方位角、高差与派生量

- 方位角：`σ_α² = g_α Cx g_αᵀ`，`g_α` 按 `∂α/∂E = ΔN/s²`、`∂α/∂N = −ΔE/s²` 组装。
- 高差：水准网直接取 `C_H` 对应分量；三角高程按斜距/竖直角/曲率折光传播。
- 面积、体积等派生量：用梯度传播或蒙特卡洛（非线性强时）；报告方法和样本数。
- 相对指标与绝对指标分别排序；最弱点按 `mp`，最弱边按 `σ_s/s`，最弱方位按 `σ_α`。

#### 5.5.5 数值与显示

- 内部一律双精度、SI 单位；显示按项目配置（mm、cm、度分秒、ppm）。
- 排序使用舍入前数值；显示值不参与排序，避免“显示并列、排序不同”。
- 协方差输出保留完整矩阵（或按需子块），报告中的椭圆参数由完整协方差计算，不由已舍入的 `σ_E/σ_N` 反算。
- 所有精度结果附 `confidence_level`、`ellipse_scale`、`unit`、`datum`、`snapshot_hash`。

### 5.6 观测方案优化

#### 5.6.1 问题定义

给定：

- 必选观测集合 `M`（已建或规范要求）；
- 候选观测集合 `E`，每个候选有设计行 `a_e`、方差 `σ_e²`、成本 `c_e`、可见性/可行性标记；
- 预算 `B`、关键点精度门槛、关键边相对精度门槛、可靠性门槛；
- 目标准则（A/D/E 或直接最小化最大点位误差）。

选择 `x_e ∈ {0,1}`，使：

```text
N(x) = N0 + Σ_e x_e · a_e a_eᵀ / σ_e²
N0 = Σ_{e∈M} a_e a_eᵀ / σ_e²
```

在约束下最优化。相关观测时，`N(x)` 用分块矩阵组装，不能简单按单行秩一更新；MVP 优化可先假设独立，V1 再支持分块。

#### 5.6.2 A/D/E 最优准则

| 准则 | 数学表达 | 含义 | 注意 |
|---|---|---|---|
| A-最优 | `min trace(Qxx) = min trace(N⁻¹)` | 参数平均方差最小 | 对参数单位/尺度敏感，必须做尺度归一化 |
| D-最优 | `max det(N)` 或 `min log det(Qxx)` | 置信椭球体积最小 | 对参数缩放不变，适合总体网形 |
| E-最优 | `max λ_min(N)` 或 `min λ_max(Qxx)` | 最坏方向方差最小 | 对尺度敏感；适合稳健性要求高的网 |
| 直接准则 | `min max_i m_p_i`、`min max_e σ_s/s` | 直接对应工程验收指标 | 非光滑；可用贪心/启发式，或转化为约束 |

**尺度归一化**：令 `S = diag(s_1,…,s_u)` 为各参数典型尺度（如坐标用 1 m，角度用 1 rad），对 `A_s = A S` 计算 `Qxx_s`；A/E 准则在归一化空间比较，报告时再换回原单位。D 准则对非奇异 `S` 不变，但数值上仍建议归一化。

#### 5.6.3 约束

- **预算**：`Σ c_e x_e ≤ B`；成本按设站、方向、距离、GNSS 时段、水准公里、交通/设备分解。
- **必选**：`x_e = 1, e ∈ M`。
- **互斥/依赖**：同一测站至多一个方向组；某观测需要对应设站；同一边不重复。
- **精度**：关键点 `m_p ≤ t_p`；关键边 `σ_s/s ≤ t_s`；最弱点/最弱边全局门槛。
- **可靠性**：`r_i ≥ r_min`；`MDB_i ≤ mdb_max`；外部可靠性 ≤ 阈值。
- **可行性**：通视/天空视图/道路可达/设备能力；不可行候选直接排除。
- **整数/离散**：观测次数、测回数、仪器类型属于离散选择；可建模为多候选或整数变量。

#### 5.6.4 贪心算法（MVP/V1 默认）

**前向选择**：

```python
S = set(M)
N = assemble_normal(M)
while budget_left > 0 and not meets_targets(S):
    best = None
    for e in candidates - S:
        if not feasible(e) or cost(e) > budget_left:
            continue
        N_try = N + rank_one(e)
        gain = objective(N_try) - objective(N)   # A/D/E 或综合评分
        utility = gain / cost(e)
        if best is None or utility > best.utility:
            best = (e, N_try, utility)
    if best is None or best.utility <= 0:
        break
    add best.e; N = best.N_try; budget_left -= cost(best.e)
```

**后向剔除**：从全候选集开始，每次删除“单位成本损失最小”的观测，直到预算/约束边界；适合候选多、预算紧的场景。

**局部搜索**：在贪心解上做 1-opt/2-opt 交换（删一个加一个、删两个加两个），只接受目标改善且可行的解；设置迭代上限，保证交互响应。

**加速**：

- 用 Cholesky  rank-one 更新 `N`，避免每次全量分解；
- 缓存 `objective` 与 `Qxx` 子块；
- 候选按“上界收益/成本”排序，使用 lazy greedy；
- 只对受影响的点位/边重算指标；
- 多线程/进程并行评估候选（注意 BLAS 线程与确定性）。

**停止条件**：预算用尽、达到精度/可靠性目标、无正收益候选、达到最大迭代/时间。

#### 5.6.5 整数规划/MICP 模型（V2，小规模精确/近似）

对独立观测，`N(x)` 对 `x` 是线性的：

```text
N(x) = N0 + Σ_e x_e · a_e a_eᵀ / σ_e²
```

下面用 MICP（Mixed-Integer Convex Programming，混合整数凸规划）统称；具体子类包括 MISOCP（混合整数二阶锥）和 MISDP（混合整数半定）。

**A-最优**（最小化 `trace(N⁻¹)`）可写为混合整数半定/二阶锥模型：

```text
min t
s.t.  Σ_e c_e x_e ≤ B
      N(x) ⪰ εI
      [[N(x), I], [I, Z]] ⪰ 0
      trace(Z) ≤ t
      x_e ∈ {0,1}
```

由 Schur 补，`Z ⪰ N(x)⁻¹`，故 `trace(Z) ≥ trace(N(x)⁻¹)`；最小化 `t` 逼近 A-最优。`εI` 避免 `N` 奇异。

**D-最优**：

```text
max log det N(x)
s.t. 预算、互斥、必选、x_e ∈ {0,1}
```

`log det` 是凹函数，连续域最大化是凸问题；加入二元变量后属于混合整数非线性/凸规划，通常用 SDP/指数锥建模，或先求连续权重松弛（`0≤x_e≤1`）得到上界，再 rounding + 局部搜索。它不能直接当作普通 MILP 求解。

**E-最优**：

```text
max t
s.t. N(x) − t I ⪰ 0
     t ≥ 0
     预算、互斥、必选、x_e ∈ {0,1}
```

这是混合整数 SDP；小规模可用 Mosek 等支持 SDP 的求解器，A-opt 的 MISOCP 可用 SCIP；规模大时用贪心/连续松弛。

**可靠性约束**：`r_i(x)`、`MDB_i(x)` 对 `x` 非线性且非凸。工程做法：

1. 先忽略可靠性求精度最优；
2. 计算 `r_i`/MDB，对不满足的观测加“割”或惩罚；
3. 重新求解，迭代 2～3 次；
4. 最终方案必须逐条核验，不能只信求解器状态。

**求解器选择**：

| 规模 | 建议 |
|---|---|
| 候选 ≤ 30 | 枚举/分支定界/MICP，追求精确或高置信近似 |
| 30～150 | MICP + 时间上限；贪心解作为 warm start |
| > 150 | 贪心 + 局部搜索 + Pareto 前沿；不做精确整数规划 |
| 相关观测 | 分块组装；MICP 变量按“组”而非单观测，避免组合爆炸 |

#### 5.6.6 成本模型与多目标

成本项建议：

```text
cost = 设站费 × 设站数
     + 方向观测费 × 方向数 × 测回数
     + 距离观测费 × 边数 × 测回数
     + GNSS 时段费 × 时段数
     + 水准费 × 公里数
     + 交通/住宿/设备折旧
```

成本表版本化（`cost_model.version`），不同方案必须用同一版本比较。

多目标处理：

- **ε-约束**：固定预算，最小化 `mp_max`；或固定精度，最小化成本；扫描得到 Pareto 前沿。
- **加权和**：`J = w1·精度指标 + w2·成本 + w3·可靠性惩罚`；权重必须公开、可追溯。
- **分层**：先满足关键精度/可靠性硬约束，再在达标方案中比较成本。
- **报告**：每个推荐方案给出成本、`mp_max`、最弱边、最小 `r_i`、最大 MDB、相对基准的改善率、边际成本（每毫米/每 ppm 的成本）。

#### 5.6.7 优化结果的可解释性

- 为什么选这条边：边际精度增益、成本、可靠性贡献；
- 为什么没选：收益低、超预算、不可通视、与其他观测冗余；
- 与基准方案差异：新增/删除/改次数；
- 敏感性：成本 ±20%、先验 σ ±20% 时方案是否稳定；
- 人工否决入口：允许锁定/排除某些观测，重新优化。

#### 5.6.8 优化验证

- 小规模（≤ 20 候选）与暴力枚举对比，验证贪心/MICP 的最优性或 gap；
- 增加独立正权观测，目标不应变差（数值容差内）；
- 预算增加，最优目标单调不劣；
- 同一输入、同一随机种子，结果可复现；
- 推荐方案必须通过独立精度/可靠性复算，不能只信优化器内部指标。

### 5.7 基于 DEM 的通视分析与地球曲率/折光改正

#### 5.7.1 DEM 数据语义

| 属性 | 要求 |
|---|---|
| 格式 | GeoTIFF（优先）、GeoPackage raster、本地瓦片高程 |
| 水平 CRS | 必须明确；与工程 CRS 可转换 |
| 垂直基准 | 大地高/正高/正常高必须声明；与工程高程基准可转换 |
| 表面类型 | DSM（含植被/建筑）或 DTM（裸地）；报告必须标注 |
| 分辨率 | 记录源分辨率；采样步长不得大于分辨率的一半 |
| NoData | 单独识别；不能当 0 米 |
| 精度 | 记录来源、垂直精度、年份；必要时给保守误差 |

#### 5.7.2 剖面采样

1. 将起终点转换到 DEM CRS；若跨投影带，按 geodesic 线采样后再转 DEM 坐标。
2. 沿线等距采样：`step = clamp(0.5 × resolution, 0.5 m, 10 m)`；长边可自适应加密。
3. 双线性插值读取高程；记录每个采样点的 `x`、`h_terrain`、`nodata` 标记。
4. 将 DEM 高程转换到工程高程基准；若 DEM 为正高、工程为大地高，加/减 geoid 起伏 `N`。
5. 加上仪器高/目标高：`h1 = ground1 + instrument_height`，`h2 = ground2 + target_height`。
6. 计算视线高度与净空；输出最小净空、发生位置、遮挡段。

#### 5.7.3 曲率与折光改正

把两点间的视线视为直线。地球曲率使地表在中部相对弦线凸起，视线净空减小；折光使视线向下弯曲，部分抵消这一效应。设计阶段采用等效地球半径模型：

```text
R_eff = R / (1 − k)
h_LOS(x) = h1 + (h2 − h1) · x/d − (1 − k) · x(d − x)/(2R)
```

其中：

- `R = 6 371 000 m`（设计近似；高精度用当地曲率半径）；
- `k` 为折光系数，默认 `0.13`，可按季节/地区/高度配置（常见 0.12～0.14）；
- `x` 为距起点的水平距离，`d` 为总距离；
- 端点 `x=0`、`x=d` 时改正项为 0，保证视线过两端；
- 负号表示曲率使视线相对两端连线向下偏移；`k` 越大，偏移越小。该式等价于把地球半径换成 `R_eff = R/(1−k)` 后的弦线公式。

**净空**：

```text
clearance(x) = h_LOS(x) − h_terrain(x)
min_clearance = min_x clearance(x)
```

判定：

- `min_clearance ≥ clearance_threshold`：通视；
- `min_clearance < 0`：明确遮挡；
- `0 ≤ min_clearance < threshold`：临界/需现场复核；
- 存在 NoData 或 DSM 地物不确定：标记“不确定”，不得直接判为通视。

默认 `clearance_threshold = 0.5 m`（光学观测），可配置；重要边建议 1.0～1.5 m 并现场核查。

**三角高程**：由斜距 `S`、竖直角 `α`、仪器高 `i`、目标高 `t`：

```text
Δh = S sin α + i − t + (1 − k) · S²/(2R)
```

曲率/折光项符号必须与 `h_LOS` 模型一致，并用已知高差/往返观测校验；对向观测可显著削弱折光影响。

#### 5.7.4 通视矩阵与批量分析

- 对每个候选光学观测（距离/角度/方向）计算 `visibility`；
- 输出 `visible / blocked / marginal / unknown` 四态，不用简单布尔；
- 记录 `min_clearance`、位置（距起点距离）、遮挡点高程、DEM 版本、`k`、阈值；
- 角度观测涉及三条边：后视—测站、测站—前视；任一不通视则角度不可观测；
- 设站可行性还要考虑仪器架设空间、道路、安全，DEM 只能给地形约束，不能替代现场。

#### 5.7.5 GNSS 的特殊处理

**GNSS 基线不需要两台接收机之间通视**。不要把“DEM 两点连线通视”作为 GNSS 基线的硬约束。GNSS 设计应关注：

- 测站天空视图/遮挡（可用 DSM 做天空视图/方位-高度遮蔽图）；
- 多路径、电磁环境、卫星几何（PDOP）；
- 基线长度、时段、星历、电离层/对流层；
- 基线解算质量（fixed/float、RMS、ratio）。

因此数据模型把 `visibility_domain` 分为 `optical` 与 `gnss_skyview`，优化约束按观测类型选择。

#### 5.7.6 性能与缓存

- 剖面按 `(from, to, dem_version, k, step)` 缓存；同一对点不重复采样；
- 批量通视用网格空间索引/瓦片分块，避免一次读入整幅 DEM；
- 并行采样；结果写入 `visibility_result`；
- 1000 对 1 km 边、30 m DEM 的目标：单机 < 10 s（需基准测试）；
- 大范围分析可预生成“可通视候选图”，但最终以逐边剖面为准。

#### 5.7.7 局限与报告

- 30 m DEM 无法反映围墙、电杆、树木、车辆等小障碍；DSM 也不等于施工后地形。
- 折光系数随气象变化；长边应做敏感性分析（k=0.10/0.13/0.16）。
- 报告必须写明 DEM 来源/版本/分辨率/垂直基准、曲率折光公式与参数、阈值、NoData 比例。
- 结论用“按当前 DEM 判定”，并建议关键边现场复测。

### 5.8 GNSS 基线向量网

#### 5.8.1 观测模型

在 ECEF 中，基线向量观测：

```text
l_ij = X_j − X_i + v_ij
```

设计矩阵：对 `X_i` 为 `−I₃`，对 `X_j` 为 `+I₃`；其余为 0。若使用 ENU 基线 `l_ENU`，可先转到 ECEF：

```text
l_ECEF = R_iᵀ · l_ENU
C_ECEF = R_iᵀ · C_ENU · R_i
```

`R_i` 为测站 i 的 ECEF→ENU 旋转矩阵（由经纬度确定）。**建议在 ECEF 中平差**，平差后再转 ENU/经纬度；避免在 ENU 中把旋转矩阵当常数导致短基线误差。

#### 5.8.2 协方差与相关基线

- 每条基线至少 3×3 协方差；`vcv_block` 存完整矩阵，单位 m²。
- 同一时段/同一网解的多条基线可能相关：存 `3n×3n` 分块矩阵，`session_id` 标识；不能只取对角 3×3 而忽略相关。
- 若上游只给每条基线的 3×3、不给跨基线相关：按块对角处理，并在报告中标记“相关性未知，精度可能偏乐观”。
- 若连 3×3 都没有：用长度经验模型 `σ = a + b·ppm` 生成对角协方差，标记 `covariance_source = empirical`，不得与实测协方差混用。

#### 5.8.3 基准与平差

- 固定 3D 基准站：删除其未知数；至少 1 个点（3 分量），或按最小约束。
- 无固定站：GNSS 自由网有 7 个基准缺陷（3 平移、3 旋转、1 尺度）；用最小约束/自由网，报告基准。
- 多期/不同坐标系：Helmert 七参数；公共点协方差参与传播；转换参数不确定性不能忽略。
- 基线网平差后，检查：
  - 基线残差（向量分量）；
  - 环闭合差（三角形/多边形）；
  - `σ0²` 与先验协方差是否一致；
  - 粗差/异常基线（w-test、稳健估计）；
  - 点位 `mp`/`m3D` 与可靠性。

#### 5.8.4 与平面网的集成

两条路线：

1. **3D 平差后投影（推荐）**：GNSS 网在 ECEF 平差，得到 `C_XYZ`；转到 ENU/经纬度，再投影到工程平面，按雅可比传播 `C_grid`。平面成果与 GNSS 成果同源，避免重复平差。
2. **基线投影后 2D 平差**：把每条基线投影为 `ΔE, ΔN`，用 `J C_XYZ Jᵀ` 传播协方差，再进入 2D 网。实现简单，但会损失高程-平面相关性；只在平面精度为主、基线较短时使用。

**禁止**：把 GNSS 基线当“高精度距离”只取水平分量、丢掉 3×3 协方差和高度相关；这会让精度评估虚高。

#### 5.8.5 与全站仪联合

- 优先 3D 联合平差：GNSS 基线（3D）+ 全站仪方向/距离/天顶距（3D 或带高程） + 水准/高程；分观测组估计方差分量。
- 若只做 2D：GNSS 提供平面基准/控制点，全站仪加密；先固定 GNSS 点（带协方差），再做 2D 网；或联合 2D 平差，GNSS 点用 2×2 边缘协方差。
- 坐标系/历元/高程基准必须统一；GNSS 大地高转正高需 geoid。

#### 5.8.6 输出与测试

输出：基线残差、环闭合、点位 3D 协方差、ENU/平面精度、可靠性、MDB、基线质量表、天空视图（可选）。

测试：

- 已知坐标的合成基线网，验证 `Cx` 与解析结果；
- ECEF↔ENU 协方差往返变换；
- 单环闭合差；
- 无固定站时的 7 个零奇异值；
- 相关基线块与块对角结果的差异；
- 与独立软件/已知算例对比。

### 5.9 高程/水准网

#### 5.9.1 观测模型

水准路线 `i→j` 的高差观测：

```text
Δh_ij = H_j − H_i + v_ij
```

设计矩阵：对 `H_j` 为 `+1`，对 `H_i` 为 `−1`。若为闭合环，环内高差之和应接近 0；闭合差用于检核，不额外增加独立观测（除非作为约束）。

#### 5.9.2 随机模型

按路线长度 `L`（km）：

```text
σ_ij = σ_km · sqrt(L_ij)
```

`σ_km` 单位为 mm/√km，按仪器/等级/方法配置；也可直接给每段方差。重复观测取均值时按 `σ/√n`，但必须明确“单次”还是“均值”，避免重复折减。跨河/长视线/特殊环境可单独给方差。

#### 5.9.3 网形、基准与环闭合

- 水准网是 1D 图：节点（水准点）、边（测段）、环（闭合环）。
- 至少 1 个固定高程基准点；无固定点则秩亏 1。
- 闭合环提供冗余：`r = 边数 − 节点数 + 1`（连通图）；用于检核和可靠性。
- 环闭合差：`w = Σ Δh`；按环长计算限差；超限定位到测段。
- 支线/孤立点：无检核，`r_i` 可能接近 0，报告中警示。

#### 5.9.4 高程类型与 geoid

| 类型 | 符号 | 说明 |
|---|---|---|
| 大地高 | `h` | 相对参考椭球；GNSS 直接得到 |
| 正高 | `H` | 相对大地水准面；水准/重力得到 |
| 正常高 | `H_N` | 相对似大地水准面；常见国家高程基准 |

转换：

```text
H = h − N
```

`N` 为 geoid 起伏（或高程异常）。必须记录 geoid 模型/版本/精度；转换后的协方差：

```text
σ_H² = σ_h² + σ_N² − 2Cov(h,N)
```

若无协方差，按独立处理并保守估计。**禁止**把 GNSS 大地高直接当正常高使用。

#### 5.9.5 三角高程

由斜距 `S`、竖直角 `α`、仪器高 `i`、目标高 `t`：

```text
Δh = S sin α + i − t + (1 − k) S²/(2R)
```

对向观测：

```text
Δh = (Δh_forward + Δh_backward)/2
```

可削弱折光/仪器高误差；但仍需曲率改正。三角高程的精度通常低于水准，报告中单独标注方法。

#### 5.9.6 与 GNSS/平面网集成

- GNSS 大地高 + geoid → 正常高，作为水准网的约束/检核；必须传播 geoid 不确定度。
- 水准点与平面点共用 `point` 身份，通过 `network_point` 关联；避免“平面点 A”和“水准点 A”两条记录。
- 3D 联合平差（V2）：GNSS 基线 + 水准 + 三角高程 + 平面观测，统一参数 `X,Y,Z` 或 `E,N,H`；分观测组估计方差分量；基准统一。

#### 5.9.7 输出与测试

输出：高程平差值、`σ_H`、环闭合差、测段残差、`r_i`/MDB、水准路线图、基准说明。

测试：

- 已知高差的水准环，验证闭合差与平差；
- 单固定点 + 一条支线：秩 1、`r_i=0`；
- 两条路线闭合：冗余 1，`r_i` 之和为 1；
- `σ_km` 变化对 `σ_H` 的影响；
- GNSS 大地高 + 已知 geoid 转正常高；
- 三角高程往返与曲率改正符号。

### 5.10 粗差探测与稳健估计

#### 5.10.1 设计阶段与实测阶段的边界

- **设计阶段**：没有实测残差，不能“探测粗差”；只能计算 MDB、外部可靠性和 `r_i`，回答“这个方案理论上能发现多大粗差、发现不了会影响多少”。
- **实测阶段**：有观测值和残差，才能做 w-test、数据 snooping、稳健估计。
- 产品文案必须区分两者，避免用户把 MDB 当成“已发现粗差”。

#### 5.10.2 数据 snooping 流程

```text
1. 用全部观测平差，得到 v、Qv、σ0²、w_i
2. 选择 |w_i| 最大的观测
3. 与阈值（z_{1−α/2} 或 t 分布）比较
4. 若超限：标记/剔除该观测，重算；记录迭代
5. 重复 2–4，直到无超限或达到最大迭代
6. 输出：保留观测、剔除观测、每步 w_i、σ0²、对坐标的影响
```

注意事项：

- 一次只剔除一个，避免“一次删太多”掩盖问题；
- 剔除后自由度减少，阈值和 `σ0²` 要重算；
- 多个粗差可能互相遮蔽（masking）或把好观测推成异常（swamping）；
- 相关观测的 w-test 用 5.4 的矩阵公式，不能简单用 `v_i/σ_i`；
- 观测数多时做 Bonferroni 或其他多重检验校正，并报告所用 α。

#### 5.10.3 稳健估计

V1 后期/ V2 引入：

- **Huber**：残差小于 `kσ` 时用原权，大于时降权；`k` 常取 1.345（95% 效率）。
- **IGG3**：三段权函数，区分正常/可疑/淘汰；适合测量数据。
- **L1 平差**：最小化残差绝对值和；对粗差稳健，但效率略低，需线性规划。
- **RANSAC/随机采样**：候选观测多、粗差比例高时做一致性筛选；计算量大，适合小规模。

稳健结果输出：稳健权、残差、异常候选、与最小二乘结果的差异。稳健估计不能替代可靠性指标；它降低粗差影响，但不告诉你“能发现多大粗差”。

#### 5.10.4 粗差可探测性报告

每条观测给：

- `r_i`；
- `MDB_i`（观测单位 + 相对 σ 倍数）；
- 外部可靠性（最大坐标影响）；
- 实测阶段的 `w_i`、是否剔除；
- 结论：`good / weak_redundancy / large_mdb / outlier / undetectable`。

方案级汇总：

- 最小 `r_i`、最大 MDB、最大外部影响；
- 不可探测观测清单；
- 建议：增加独立观测、改变网形、提高观测精度、增加检核条件。

### 5.11 数值实现与性能

#### 5.11.1 稠密与稀疏

| 规模 | 方法 | 说明 |
|---|---|---|
| u ≤ 1000 | 稠密 Cholesky/SVD | MVP；实现简单、诊断充分 |
| 1000 < u ≤ 5000 | 稀疏 Cholesky/QR | V2；利用 `A` 的稀疏结构 |
| u > 5000 | 稀疏 + 迭代/分块 | 分区平差、子网、分布式；需专门设计 |

MVP 默认：

- `A` 用 `numpy.ndarray`（m×u）；
- `N` 用 `A.T @ (W @ A)`；
- 用 `scipy.linalg.cho_factor/cho_solve` 求 `Qxx`；
- 秩/条件用 SVD（小规模）或 `scipy.linalg.qr`（经济型）；
- 不显式求 `N⁻¹`；按需解 `N X = I` 的列子集。

V2 稀疏：

- `scipy.sparse` 组装 `A`；
- `sksparse.cholmod` 或 `scipy.sparse.linalg.splu`；
- 稀疏 QR（`scipy.sparse.linalg.svds` 仅用于诊断，不用于完整协方差）；
- 分区/子网平差，边界点用协方差压缩。

#### 5.11.2 秩、条件与尺度

- 先做列尺度归一化：`A_s = A S`，`S` 取参数典型尺度；在归一化空间判秩，再还原 `Qxx = S Qxx_s Sᵀ`。
- 秩阈值：`tol = max(m,u) * eps * smax`；另设“病态提示”阈值（如 `smax/smin > 1e12`），但不自动判失败。
- 条件数：报告 `cond(N)`、`cond(A)`；条件数大不等于结果一定错，但提示对先验误差/舍入敏感。
- 负特征值：`Cx` 对称化后做特征分解；`λ_min < -tol` 报 `COVARIANCE_NOT_POSITIVE_DEFINITE`；`-tol ≤ λ_min < 0` 截断到 0 并记录。
- 单位/量纲：坐标米、角度弧度、方差对应平方；任何跨单位运算前显式转换。

#### 5.11.3 协方差传播与存储

- 只提取需要的子块：点位 2×2/3×3、边梯度、相对位置 2×2。
- 大矩阵不入 JSON；`result_artifact` 存 `.npz`（`A`、`Cl`、`Cx`、索引）或 Parquet（稀疏三元组），带 `sha256`、`dtype`、`shape`、`unit`。
- 报告中的数值表由结果对象生成，不由前端二次计算。
- 结果版本：`engine_version`、`options_hash`、`snapshot_hash` 三者共同标识。

#### 5.11.4 性能目标与优化

| 场景 | 目标 | 手段 |
|---|---|---|
| 300 点平面网 | < 2 s | 稠密 Cholesky；避免重复组装；缓存 |
| 1000 点平面网 | < 10 s | 稀疏/分块；并行候选评估 |
| 2000 点 GNSS/水准 | < 30 s | 稀疏；按连通子网分解 |
| 1000 对通视 | < 10 s | 剖面缓存、瓦片采样、并行 |
| 优化 150 候选 | < 30 s | 贪心 + 局部搜索；Cholesky 更新 |

优化手段：

- 预分配数组；避免 Python 循环组装（用向量化/坐标列表）；
- 观测行按类型分组，批量计算；
- 候选优化用增量 `N` 更新；
- 多进程用于独立方案/候选；BLAS 线程数与进程数协调，避免过度订阅；
- 前端分页/虚拟滚动，地图只渲染视窗内元素。

#### 5.11.5 确定性

- 同一输入、同一引擎版本、同一 BLAS 配置，结果应在 1e-9 相对容差内一致；
- 浮点求和顺序会影响末位；报告/回归测试用容差而非字符串相等；
- 优化器若用随机算法，固定随机种子并记录；
- 并行归约要固定顺序或使用确定性算法。

## 6. 技术栈选择及理由

### 6.1 选型总表

| 层次 | 选择 | 理由 | 备选/风险 |
|---|---|---|---|
| 语言（计算/后端） | Python 3.12 | 大地测量、栅格、优化、科学计算生态最成熟；开发效率高；GDAL/PROJ 绑定好 | 大规模性能不如 C++/Rust；用 NumPy/SciPy/稀疏/原生扩展补 |
| Web 框架 | FastAPI + Pydantic 2 | 类型化请求/响应、OpenAPI 自动生成、异步任务友好 | Django 较重；Flask 类型弱 |
| 数据访问 | SQLAlchemy 2 + Alembic | 事务、迁移、SQLite/PostGIS 双适配 | 手写 SQL 更轻，但迁移/可维护性差 |
| 数据库（MVP） | SQLite（WAL）+ SpatiaLite 可选 | 单文件、离线、零运维、工程包易分发 | 多用户并发弱；V2 换 PostGIS |
| 数据库（V2） | PostgreSQL 16 + PostGIS | 并发、空间索引、权限、备份 | 运维成本；本地优先仍保留 SQLite |
| 科学计算 | NumPy 2 + SciPy | 线性代数、稀疏、优化基础 | 版本兼容；锁依赖 |
| 投影/大地 | pyproj（PROJ 9）+ GeographicLib | 权威 CRS/投影/ geodesic；尺度因子/收敛角 | 原生库打包；需固定 PROJ datum grid |
| 栅格/DEM | rasterio + GDAL | GeoTIFF/GeoPackage/重采样/NoData | 安装包大；许可（GDAL/MIT/X） |
| 矢量 | Shapely 2 + Fiona | 几何校验、导入导出 | 大几何性能一般 |
| 瓦片 | SQLite MBTiles + PMTiles + MapLibre | 离线、单文件、前端成熟 | 全国包体积；需按需分发 |
| 优化建模 | CVXPY + SCIP（开源）/ Mosek（商业可选） | 建模快；SCIP 适合 MISOCP，Mosek 适合含 SDP 的模型 | 求解器许可/性能；大规模需启发式 |
| 组合优化 | OR-Tools CP-SAT | 预算/互斥/设站选择等离散约束 | 不直接处理协方差；与 MICP 分工 |
| 前端 | React 18 + TypeScript 5 + Vite | 生态成熟、类型安全、构建快 | 包体积；需状态管理规范 |
| 地图前端 | MapLibre GL JS | 离线矢量瓦片、WebGL、开源 | 样式/字体需本地化 |
| UI 组件 | Ant Design 5 | 表格/表单/树/弹窗齐全，适合工程软件 | 定制主题成本 |
| 图表 | ECharts 5 | 误差椭圆、Pareto、剖面、热力图 | 大数据量需降采样 |
| 表格 | TanStack Table | 虚拟滚动、排序、筛选 | 需自建样式 |
| 状态 | Zustand + TanStack Query | 轻量、服务端状态缓存 | 复杂跨页状态需约定 |
| 桌面壳 | Electron + electron-builder | 成熟、Python sidecar 集成简单、Windows 兼容好 | 安装包大/内存高；V2 可评估 Tauri |
| Python 打包 | PyInstaller | 单文件/目录 sidecar，配合 Electron | GDAL/PROJ 数据文件需显式收集 |
| 报告 | Jinja2 + WeasyPrint（PDF）+ python-docx（DOCX） | HTML/CSS 排版灵活；中文需字体；DOCX 可编辑 | WeasyPrint 复杂表格分页；需模板测试 |
| 测试 | pytest + Hypothesis + Playwright + pytest-benchmark | 单测/属性测试/E2E/性能 | 需维护 fixture |
| CI | GitHub Actions/GitLab CI | 自动测试、打包、签名 | 原生依赖缓存 |
| 日志 | structlog + 文件轮转 | 结构化、可定位实体 | 本地日志隐私 |
| 监控（可选） | OpenTelemetry | 性能/错误追踪 | 离线环境默认关闭 |

### 6.2 为什么以 Python 为计算核心

- **数学生态**：NumPy/SciPy 提供 Cholesky、SVD、稀疏、最小二乘；CVXPY/SCIP 提供 MICP；statsmodels 可做检验。
- **地理生态**：pyproj/PROJ、rasterio/GDAL、Shapely/Fiona 是事实标准；用 TypeScript 重写成本高且容易出错。
- **可验证**：纯 Python 内核可用 pytest、Hypothesis、有限差分快速验证；也方便与高校/第三方复算。
- **性能可接受**：控制网规模通常几百到几千参数；NumPy 稠密/SciPy 稀疏足够；真到万级再考虑 C++/Rust 扩展或分区。

**不选全 TypeScript 的原因**：前端生态强，但大地测量/栅格/凸优化库弱；把投影、平差、DEM 都放 Node 会增加数值风险。**不选 C++ 为主的原因**：开发慢、部署复杂、算法迭代成本高；性能瓶颈可用局部扩展解决。

### 6.3 桌面壳与部署

**MVP 推荐 Electron + Python sidecar**：

- Electron 负责窗口、菜单、文件对话框、自动更新；
- 启动时拉起 `python -m app.serve --port 0`，通过随机端口/令牌通信；
- 退出时优雅关闭 sidecar；
- `electron-builder` 生成 Windows/macOS/Linux 安装包；
- PyInstaller 收集 Python、GDAL/PROJ 数据、字体、模板；
- 首次启动检查地图/DEM 资源，缺失给下载/导入指引。

**V2 可选 Tauri 2**：安装包更小、内存更低，但需要 Rust 工具链和 sidecar 管理；业务/API 不变。是否切换由安装包体积、启动时间、团队技能决定。

**服务器模式**：同一 FastAPI 应用 + PostGIS/Redis；前端静态资源由 Nginx 提供；适合内网多人。桌面与服务器共用 `engine/` 和 `application/`。

### 6.4 关键依赖与许可

| 依赖 | 许可 | 备注 |
|---|---|---|
| PROJ / GDAL | MIT/X 风格 | 需保留版权声明；datum grid 许可 |
| NumPy / SciPy | BSD | 可商用 |
| FastAPI / React / MapLibre | MIT/BSD | 可商用 |
| SCIP | Apache 2.0（SCIP 8+） | 需确认版本/二进制分发条款 |
| Mosek | 商业 | 可选，不强制 |
| 地图数据 | 按来源 | 全国地图/OSM/天地图等许可不同；必须做许可清单与署名 |
| 字体 | 按字体许可 | 离线嵌入需授权 |

**原则**：核心功能不依赖商业求解器；Mosek 只作为“可选加速”，默认用 SCIP/启发式。地图数据许可在“关于/成果来源”中展示。

## 7. 接口调整

### 7.1 设计原则

1. **资源化**：Project / Network / Point / Observation / Snapshot / Calculation / Optimization 都是资源；动作放在子资源上（如 `/snapshots/{id}/calculations`）。
2. **版本化**：URL 带 `/api/v1`；破坏性变更升 v2；字段只增不删，废弃字段标注 `deprecated_at`。
3. **不可变计算**：计算输入是 `snapshot_id`，不是“当前工程状态”；避免“算的时候数据又变了”。
4. **异步优先**：重计算返回 `202 Accepted + Location`；进度用 SSE；结果用 GET 轮询/事件。
5. **幂等**：创建计算/优化支持 `Idempotency-Key`；同一快照 + 引擎版本 + 选项直接复用。
6. **并发控制**：更新带 `If-Match`/`expected_version`；冲突 409。
7. **错误可定位**：统一错误体，带 `code/entity/field/hint/trace_id`。
8. **单位显式**：请求/响应字段名带单位后缀（`_m`、`_rad`、`_mm`、`_ppm`），或在 schema 中声明 `unit`。

### 7.2 端点总表

| 方法 | 路径 | 用途 | 关键输入/返回 |
|---|---|---|---|
| GET | `/api/v1/projects` | 工程列表 | 分页、名称过滤 |
| POST | `/api/v1/projects` | 新建工程 | 名称、CRS、单位、目标精度 → 工程 |
| GET | `/api/v1/projects/{id}` | 工程详情 | 含网络、资源、版本 |
| PATCH | `/api/v1/projects/{id}` | 修改工程 | `If-Match`；CRS 变更需显式确认 |
| DELETE | `/api/v1/projects/{id}` | 归档/删除 | 软删除；返回审计 id |
| GET | `/api/v1/projects/{id}/networks` | 网列表 | 平面/GNSS/水准 |
| POST | `/api/v1/projects/{id}/networks` | 建网 | kind、dimension、datum → 网 |
| GET | `/api/v1/networks/{id}` | 网详情 | 点、观测、基准摘要 |
| PATCH | `/api/v1/networks/{id}` | 修改网 | 名称、状态、基准 |
| GET | `/api/v1/networks/{id}/points` | 点列表 | 分页、角色过滤 |
| POST | `/api/v1/networks/{id}/points` | 建点 | label、坐标、role、来源 |
| PATCH | `/api/v1/networks/{id}/points/{pid}` | 改点 | 坐标/角色；`expected_version` |
| DELETE | `/api/v1/networks/{id}/points/{pid}` | 删点 | 返回关联观测清单，需 `cascade=true` |
| GET | `/api/v1/networks/{id}/observations` | 观测列表 | 类型、启用、组 |
| POST | `/api/v1/networks/{id}/observations` | 建观测 | 类型 + 明细 + 精度 |
| POST | `/api/v1/networks/{id}/observations:batch` | 批量建/改 | 原子事务；逐条校验 |
| PATCH | `/api/v1/networks/{id}/observations/{oid}` | 改观测 | 启用、精度、明细 |
| DELETE | `/api/v1/networks/{id}/observations/{oid}` | 删观测 | 软删除 |
| GET | `/api/v1/networks/{id}/datum` | 基准 | 类型、约束、秩诊断 |
| PUT | `/api/v1/networks/{id}/datum` | 设基准 | 约束列表；返回秩检查 |
| GET | `/api/v1/networks/{id}/stochastic-model` | 随机模型 | 类型、σ0、相关组 |
| PUT | `/api/v1/networks/{id}/stochastic-model` | 设随机模型 | 校验正定 |
| POST | `/api/v1/networks/{id}/snapshots` | 创建快照 | 规范化输入 → `snapshot_id/hash` |
| GET | `/api/v1/snapshots/{id}` | 快照详情 | 只读；含参数/观测顺序 |
| POST | `/api/v1/snapshots/{id}/calculations` | 提交计算 | 选项 → `202` + 计算 id |
| GET | `/api/v1/calculations/{id}` | 计算状态 | 状态、进度、诊断 |
| GET | `/api/v1/calculations/{id}/results` | 精度结果 | 点/边/椭圆/矩阵引用 |
| GET | `/api/v1/calculations/{id}/reliability` | 可靠性 | `r_i`、MDB、外部可靠性 |
| POST | `/api/v1/calculations/{id}/cancel` | 取消 | 幂等 |
| POST | `/api/v1/comparisons` | 方案比较 | 多个 calculation id、指标、成本 |
| POST | `/api/v1/networks/{id}/optimizations` | 提交优化 | 候选集、目标、预算、约束 |
| GET | `/api/v1/optimizations/{id}` | 优化状态 | 进度、gap、日志摘要 |
| GET | `/api/v1/optimizations/{id}/candidates` | 候选方案 | 排序、成本、指标、解释 |
| POST | `/api/v1/optimizations/{id}/cancel` | 取消优化 | 幂等 |
| POST | `/api/v1/terrain/profiles` | 批量剖面 | 点对、DEM、步长 → 剖面/净空 |
| POST | `/api/v1/terrain/visibility` | 批量通视 | 光学观测候选 → 四态矩阵 |
| GET | `/api/v1/terrain/elevation` | 高程查询 | lon/lat、采样方法 → 高程/NoData |
| POST | `/api/v1/networks/{id}/imports/gnss-baselines` | 导入基线 | CSV/LandXML；返回校验报告 |
| POST | `/api/v1/networks/{id}/imports/leveling` | 导入水准 | CSV；路线/测段 |
| POST | `/api/v1/calculations/{id}/reports` | 生成报告 | 模板、格式（PDF/DOCX/HTML） |
| GET | `/api/v1/reports/{id}` | 报告下载 | 文件流/签名 URL |
| POST | `/api/v1/projects/{id}/exports` | 导出工程包 | 版本、资源策略 |
| GET | `/api/v1/exports/{id}` | 下载工程包 | zip + manifest |
| GET | `/api/v1/events` | SSE 事件 | `project_id`、`job_id` |
| GET | `/api/v1/projects/{id}/map-resources` | 地图/地形图资源 | 类型、格式、范围、版本、许可 |
| POST | `/api/v1/projects/{id}/map-resources` | 导入资源 | 路径/上传、CRS 校验 → 资源 id |
| POST | `/api/v1/map-resources/{id}/registrations` | 创建配准 | 仿射模型、控制点/检查点 → 参数/残差 |
| GET | `/api/v1/registrations/{id}` | 配准详情 | 参数、残差、检查点精度、范围 |
| GET | `/api/v1/layers` | 图层清单 | 类型、范围、CRS、版本 |
| GET | `/api/v1/tiles/{source}/{z}/{x}/{y}` | 瓦片 | PBF/PNG；404 空瓦片语义 |

> `:batch` 采用 Google AIP 风格的动作后缀；若团队偏好纯 REST，可改为 `POST /observations/bulk`。

### 7.3 关键请求/响应示例

**创建快照**

```http
POST /api/v1/networks/net-1/snapshots
Content-Type: application/json

{
  "expected_version": 12,
  "options": {"confidence": 0.95, "rank_tol": null}
}
```

```json
{
  "snapshot_id": "snap-01J...",
  "hash": "9f2c...e1",
  "parameter_order": ["C:E", "C:N", "D:E", "D:N"],
  "observation_count": 7,
  "unknown_count": 4,
  "created_at": "2026-01-01T00:00:00Z"
}
```

**提交计算**

```http
POST /api/v1/snapshots/snap-01J.../calculations
Idempotency-Key: calc-snap-01J-v1
Content-Type: application/json

{"engine": "adjustment", "options": {"reliability": true, "confidence": 0.95}}
```

```http
202 Accepted
Location: /api/v1/calculations/calc-01J...
```

**计算结果（节选）**

```json
{
  "id": "calc-01J...",
  "snapshot_hash": "9f2c...e1",
  "status": "succeeded",
  "rank": 4,
  "unknowns": 4,
  "redundancy": 3,
  "condition_number": 13.31,
  "points": [
    {"point_id": "C", "sigma_e_mm": 0.468, "sigma_n_mm": 1.651, "mp_mm": 1.716,
     "ellipse": {"a_mm": 1.652, "b_mm": 0.466, "azimuth_deg": 90.0, "confidence": 0.3935}}
  ],
  "edges": [
    {"from": "A", "to": "C", "sigma_s_mm": 1.651, "relative": "1:60565"}
  ],
  "reliability_summary": {"min_r": 0.0692, "max_mdb_arcsec": 10.653},
  "artifacts": [{"kind": "matrix", "name": "Cx.npz", "sha256": "..."}]
}
```

**提交优化**

```json
{
  "objective": "A",
  "candidate_observation_ids": ["d6", "d7", "a3", "a4"],
  "budget": 12.0,
  "constraints": {
    "key_points": [{"point_id": "C", "mp_max_mm": 1.5}],
    "min_r": 0.1,
    "max_mdb_arcsec": 12.0,
    "visibility": "required"
  },
  "cost_model_id": "cost-1",
  "algorithm": "greedy_local_search",
  "time_limit_s": 30
}
```

```json
{
  "optimization_id": "opt-01J...",
  "status": "queued",
  "algorithm": "greedy_local_search"
}
```

**候选结果**

```json
{
  "candidates": [
    {
      "rank": 1,
      "selected": ["d6", "a3"],
      "cost": 5.0,
      "metrics": {"mp_max_mm": 1.22, "min_r": 0.12, "max_mdb_arcsec": 10.1},
      "feasible": true,
      "explanation": "满足精度与可靠性约束；增加一条距离改善检核，边际成本 2.0/0.09mm"
    },
    {
      "rank": 2,
      "selected": ["a3"],
      "cost": 3.0,
      "metrics": {"mp_max_mm": 1.31, "min_r": 0.0408, "max_mdb_arcsec": 13.86},
      "feasible": false,
      "explanation": "精度改善但新增角度 r_i=0.041 < 0.1，可靠性约束不满足，列为不可行候选"
    }
  ]
}
```

### 7.4 统一错误模型

采用 RFC 7807 扩展：

```json
{
  "type": "https://example.local/errors/rank-deficient",
  "title": "基准约束不足",
  "status": 422,
  "code": "RANK_DEFICIENT",
  "detail": "设计矩阵秩为 2，未知参数 4；检测到 2 个平移零空间向量。",
  "entity": {"type": "network", "id": "net-1"},
  "field": "datum.constraints",
  "hint": "增加一个固定点或两个分量约束，或切换到自由网并声明基准。",
  "trace_id": "01J..."
}
```

| 错误码 | HTTP | 含义 | 前端动作 |
|---|---|---|---|
| `CRS_MISSING` | 422 | 缺坐标参考/投影参数 | 打开 CRS 配置 |
| `RESOURCE_MISSING` | 404 | 地图/DEM/字体/模板缺失 | 资源检查向导 |
| `INVALID_GEOMETRY` | 422 | 同点、零长、共线、角退化 | 地图定位到实体 |
| `INVALID_PRECISION` | 422 | σ≤0、次数非正、单位错 | 属性面板定位 |
| `COVARIANCE_NOT_POSITIVE_DEFINITE` | 422 | VCV 非正定 | 显示矩阵/相关组 |
| `RANK_DEFICIENT` | 422 | 基准/连通性不足 | 显示零空间诊断 |
| `VERSION_CONFLICT` | 409 | 乐观锁冲突 | 刷新/合并 |
| `SNAPSHOT_MISMATCH` | 409 | 计算输入与当前方案不一致 | 重算/查看历史 |
| `VCV_DIMENSION_MISMATCH` | 422 | 基线/观测维度不匹配 | 导入映射 |
| `DATUM_CONFLICT` | 422 | 固定值矛盾/重复约束 | 约束表定位 |
| `NON_CONVERGENCE` | 422 | 实测平差不收敛 | 查看残差/初值 |
| `SOLVER_TIMEOUT` | 504 | 优化超时 | 返回当前最优/放宽 |
| `VISIBILITY_NO_DATA` | 422 | DEM 覆盖不足 | 显示缺口/换源 |
| `IMPORT_FORMAT_ERROR` | 422 | 导入格式错误 | 行号/字段提示 |
| `JOB_CANCELED` | 409 | 任务已取消 | 恢复/重跑 |

### 7.5 异步、事件与幂等

- 重计算/优化/批量通视/报告生成：`202 + Location`；响应体含 `job_id`。
- 进度：SSE `/events?project_id=...`，事件类型：
  - `job.queued`、`job.started`、`job.progress`（百分比/阶段）、`job.succeeded`、`job.failed`、`job.canceled`。
- 事件只带最小载荷（id/status/progress），详情走 GET，避免 SSE 消息过大。
- 幂等键：`Idempotency-Key`；服务端保存 24 h；重复请求返回同一资源。
- 取消：`POST .../cancel` 幂等；已完成的取消返回 409 或 200（按团队约定）。
- 超时：计算/优化分别配置；超时返回部分结果（若可用）+ `SOLVER_TIMEOUT`。

### 7.6 与原有接口的兼容映射

| 原接口 | 新接口 | 说明 |
|---|---|---|
| `GET /layers` | `GET /api/v1/layers` | 增加 CRS/版本/可用状态 |
| `GET /tiles/{source}/{z}/{x}/{y}` | `GET /api/v1/tiles/{source}/{z}/{x}/{y}` | 增加缓存头/ETag |
| `GET /elevation` | `GET /api/v1/terrain/elevation` | 增加采样方法/垂直基准/NoData 原因 |
| `POST /projects/{id}/points` | `POST /api/v1/networks/{nid}/points` | 点归属到网；全局点身份 |
| `POST /scenarios/{id}/calculate` | `POST /api/v1/snapshots/{sid}/calculations` | 显式快照；异步 |
| `GET /calculations/{id}` | `GET /api/v1/calculations/{id}` | 增加可靠性/诊断 |
| `POST /comparisons` | `POST /api/v1/comparisons` | 增加可比性检查/差异 |

旧接口保留一个版本周期，响应加 `Deprecation`/`Sunset` 头；前端逐步迁移。

### 7.7 导入导出格式

| 类型 | 格式 | 说明 |
|---|---|---|
| 工程包 | `.zip`（manifest.json + SQLite + resources） | 版本、校验和、依赖清单 |
| 点/观测 | CSV、GeoJSON | 列名/单位映射；UTF-8 BOM 可选 |
| 矩阵 | `.npz`、CSV 三元组 | 含 shape/dtype/索引/单位 |
| GNSS 基线 | CSV（from,to,dx,dy,dz,vcv…）、LandXML（如支持） | 校验维度、单位、协方差 |
| 水准 | CSV（from,to,Δh,length,σ_km） | 路线/环标识 |
| 报告 | PDF、DOCX、HTML | 模板版本、字体嵌入 |
| 图件 | PNG、SVG、GeoTIFF | 带 CRS/比例尺/图例 |

导入必须“先预览、再校验、后提交”：显示行数、坐标系、单位、异常行；不静默跳过。

## 8. 界面与交互调整

### 8.1 总体布局

```text
┌ 顶部：工程名 / 工作流步骤 / 计算状态 / 保存 / 帮助 ┐
├ 左：工程树（网、点、观测、方案、图层） ┬ 中：地图 ┬ 右：属性/诊断 ┤
│                                        │          │                 │
├ 底部：点表 / 观测表 / 精度表 / 可靠性表 / 错误表 / 优化候选          ┤
└ 状态栏：CRS / 单位 / 选择对象 / 坐标 / 比例尺 / 快照哈希             ┘
```

- **工作流步骤**：工程 → 底图 → 选点 → 观测 → 基准/精度 → 计算 → 比较 → 导出。步骤可跳转，但未完成的校验用黄色提示。
- **左侧工程树**：按网类型分组；点/观测/方案/图层可折叠；支持搜索、过滤、批量选择。
- **地图**：MapLibre GL JS；点、线、角、误差椭圆、通视结果、优化候选分层；图层顺序与原方案一致（海陆→土地利用→地形→水系→道路建筑→地名→控制网→结果）。
- **右侧属性**：随选择变化；点显示坐标/角色/协方差；观测显示类型/点序/精度/归算/可靠性；方案显示差异。
- **底部表格**：虚拟滚动；列可配置；点击行地图定位；支持多选对比。

### 8.2 关键工作台

1. **选点/构网**：吸附阈值（默认 8 px）、重叠点列表、临时预览、Esc 取消；固定点锁定；拖动只改临时几何，松开提交并标记 `stale`。
2. **观测表**：距离/角度/方向/基线/水准分页；显示近似值、先验 σ、`r_i`、MDB、状态；支持批量改精度/启用/删除。
3. **诊断面板**：秩、条件数、最弱点、最弱边、最小 `r_i`、最大 MDB、外部可靠性；点击跳转到实体。
4. **可靠性热力图**：地图上按 `r_i` 着色（红<0.1，黄 0.1～0.3，绿≥0.3）；边表显示 MDB；可切换“精度/可靠性/成本”视图。
5. **优化工作台**：
   - 选择候选观测（地图框选/表选）；
   - 设目标（A/D/E/最弱边）、预算、关键点门槛、可靠性门槛；
   - 运行贪心/整数规划；显示 Pareto 前沿、候选排名、成本/精度/可靠性；
   - 点击候选，地图高亮新增观测；一键“采纳为方案”生成新快照。
6. **方案比较**：并排显示基准/候选的点位、边、椭圆、可靠性、成本；差异表可导出；可比性检查（CRS/基准/点集/精度定义）置顶。
7. **GNSS 视图**：基线表（from/to/ΔX/ΔY/ΔZ/σ/质量/时段）、环闭合、天空视图（可选）、3D 点位协方差。
8. **水准视图**：路线示意图、节点高程、环闭合、测段残差、`r_i`/MDB；支持按路线长度着色。
9. **地形/通视**：点击边显示剖面图（地形线、视线、净空、遮挡点）；参数面板调 `k`、阈值、DEM 源；结果四态着色。
10. **报告预览**：模板选择、章节开关、图表分辨率、单位/置信度；导出前显示“数据版本/快照哈希/引擎版本”。

### 8.3 交互与可用性

- **撤销/重做**：命令模式；跨点/观测/约束；计算状态随撤销恢复。
- **自动保存**：编辑后 2 s 防抖；崩溃恢复；快照只在显式“计算”时创建。
- **校验前置**：表单即时校验 + 提交事务校验；错误定位到字段/实体。
- **键盘**：常用工具快捷键；表格支持方向键/复制粘贴；地图支持 Esc/Enter。
- **无障碍**：颜色不是唯一编码；表格/图表有文字摘要；焦点可见；对比度符合 WCAG AA。
- **大网性能**：点/边聚合、视窗裁剪、WebGL 图层、表格虚拟滚动；超过 5000 个图形要素时默认聚合。
- **离线提示**：地图/DEM/字体缺失时给出资源检查清单，不白屏。
- **误导防护**：设计精度显著标识“先验”；未设置基准/投影时禁止发布“有效”结果；导出前强制检查。

## 9. 分阶段路线图（含里程碑）

### 9.1 前提与团队

假设核心团队 4～5 人：

- 1 名架构/技术负责人（兼后端）；
- 1～2 名测绘算法/后端工程师；
- 1 名前端工程师；
- 0.5 名 GIS/数据工程师；
- 0.5 名测试/质量工程师；
- 1 名测绘领域专家（兼职评审，不参与日常开发）。

总周期约 8～9 个月；若只有 2～3 人，建议把 V1 拆成两个发布，周期顺延 30%～50%。

### 9.2 阶段总表

| 阶段 | 周期 | 范围 | 主要交付 | 里程碑/退出条件 |
|---|---|---|---|---|
| P0 基线/架构 | 2 周 | 现状梳理、ADR、数据模型、§13 fixture、技术 spike | 架构文档、schema v2 草案、黄金用例、风险清单 | M0：§13 基准脚本可复现；架构评审通过 |
| P1 MVP | 10 周 | 平面边角/方向、固定/加权基准、对角/分块 VCV、SVD、精度、可靠性、投影/归算基础、地图/配准、工程包、报告 | 可运行 MVP、API v1、用户手册、回归测试 | M1：MVP 验收 9 条全过；内部试用 |
| P2 GNSS/水准 | 8 周 | 基线向量网、3D ECEF/ENU、完整 VCV、水准/高程网、geoid 接口、导入 | V1.5、GNSS/水准回归、导入模板 | M2：合成网+实测网通过；与独立软件对比 |
| P3 地形/投影 | 6 周 | DEM 剖面、通视、曲率折光、投影归算、变形检查、跨带提示 | V1.8、通视/投影回归、剖面 UI | M3：已知遮挡/通视用例通过；投影尺度误差 < 1 ppm |
| P4 优化 | 8 周 | 贪心/局部搜索、A/D/E、成本模型、MICP（小规模）、Pareto | V2.0、优化工作台、候选解释 | M4：小规模与暴力枚举对比；预算/精度约束满足 |
| P5 硬化/试点 | 5 周 | 性能、打包、安全、备份、文档、试点 | 安装包、运维手册、试点报告 | M5：试点项目通过；P0/P1 缺陷清零 |

> 总计约 39 周（含缓冲）。P2 与 P3 可部分并行（GIS/前端先行），但 P4 必须在 P1 的可靠性/协方差稳定后开始。

### 9.3 各阶段详细任务

#### P0：基线与架构（2 周）

- 复现第 13 节：用独立脚本计算 `Cx`、`mp`、椭圆、边精度；冻结 `fixtures/section13_base.json`、`section13_added.json`。
- 确认符号/单位约定：距离偏导、方位角偏导、角度包裹、投影收敛角、曲率折光。
- 完成 ADR-01～08；确定 schema v2 与旧数据映射。
- 技术 spike：FastAPI + SQLite + MapLibre + MBTiles + PyInstaller sidecar 最小闭环。
- 产出：架构文档、风险清单、MVP backlog、验收标准。

**M0 退出**：§13 数值与原文表格一致（≤0.001 mm）；团队对“设计态/实测态、绝对/相对协方差、固定/加权基准”理解一致。

#### P1：MVP（10 周）

- 领域模型：Project/Network/Point/NetworkPoint/Observation/Snapshot/Calculation。
- 平面引擎：距离、方向、角度、固定/加权基准、对角/分块 VCV、Cholesky/SVD、秩诊断。
- 投影/归算基础：CRS 校验、投影尺度因子、距离归算、`grid/ground` 模式、已知点/已知边单测。
- 可靠性：`Qv`、`R`、`r_i`、MDB、外部可靠性、报告。
- 精度：`mp`、椭圆、相对边、方位角。
- 地图/配准：MBTiles、GeoTIFF/扫描图仿射配准、图层管理、独立检查点。
- UI：工程树、地图选点、距离/角度编辑、观测表、诊断面板、简单报告。
- 数据：SQLite、快照、导入导出、旧工程迁移。
- 测试：§13 黄金、偏导有限差分、基准/退化、API/E2E。

**M1 退出**：MVP 验收 9 条全过；300 点性能达标；内部试用 2 周无 P0 缺陷。

#### P2：GNSS 与水准（8 周）

- GNSS：基线数据模型、3×3/跨基线 VCV、ECEF 平差、ENU/经纬度转换、基准/Helmert、环闭合、质量表。
- 水准：1D 网、路线/环、`σ_km`、固定基准、闭合差、geoid 接口、三角高程。
- 导入：CSV/LandXML（按实际数据源裁剪）；校验/预览。
- UI：GNSS 基线表/天空视图（可选）、水准路线图。
- 测试：合成 GNSS 网、7 个零奇异值、协方差变换、水准环、geoid 转换。

**M2 退出**：至少 1 个合成网 + 1 个实测网通过；与独立软件点位/高程差异在项目容差内；导入错误可定位。

#### P3：地形与投影（6 周）

- DEM 服务：GeoTIFF 读取、双线性采样、NoData、垂直基准转换、缓存。
- 剖面/通视：曲率折光、四态判定、批量矩阵、剖面图。
- 投影：尺度因子、收敛角、距离归算、`grid/ground/local_enu`、跨带/变形警告。
- 测试：合成 DEM 遮挡、已知曲率公式、投影已知点、DSM/DTM 差异。

**M3 退出**：已知通视/遮挡用例判定正确；投影尺度误差 < 1 ppm；长边曲率改正与手算一致。

#### P4：优化（8 周）

- 成本模型、候选集、预算/关键点/可靠性约束。
- 贪心前向/后向、局部搜索、A/D/E 评分、Pareto。
- 小规模 MICP（A/E/D）与求解器适配；超时/回退。
- UI：优化工作台、候选解释、一键采纳。
- 测试：暴力枚举对比、单调性、预算、可靠性约束、可复现。

**M4 退出**：≤20 候选与枚举一致或 gap 可解释；推荐方案独立复算通过；优化 150 候选 < 30 s。

#### P5：硬化与试点（5 周）

- 性能：1000 点稀疏、批量通视、前端大数据。
- 打包：Windows 安装包、sidecar、字体/GDAL/PROJ 数据、自动更新。
- 安全：本地令牌、路径校验、导入文件大小/类型限制、日志脱敏。
- 备份/恢复：SQLite 备份、工程包校验、崩溃恢复。
- 文档：用户手册、管理员手册、API 文档、已知限制。
- 试点：1～2 个真实项目，收集问题，修复 P0/P1。

**M5 退出**：试点验收；安装/升级/回滚演练通过；发布检查表全绿。

### 9.4 发布计划

| 版本 | 内容 | 目标用户 |
|---|---|---|
| 0.9 alpha | 平面引擎 + §13 + 内部 UI | 内部/种子用户 |
| 1.0 | MVP：平面 + 可靠性 + 地图 + 报告 | 设计人员 |
| 1.5 | GNSS + 水准 + 导入 | 多源控制网项目 |
| 1.8 | 通视 + 投影 + 剖面 | 复杂地形/长边项目 |
| 2.0 | 优化工作台 + MICP + Pareto | 方案优化/投标 |
| 2.x | 3D 联合、稳健/VCE、多用户 | 企业/监测 |

### 9.5 关键依赖与缓冲

- P2 依赖 P1 的 `NetworkPoint`/`Observation` 抽象稳定；若 P1 数据模型反复，P2 会连锁延期。
- P4 依赖 P1 的 `Qxx` 与可靠性结果稳定；优化器必须调用同一引擎复算，不能另写一套。
- 外部依赖：地图/DEM 数据许可、GNSS 基线样本、水准样本、geoid 模型；P0 就要落实，避免 P2 卡住。
- 每个阶段预留 15%～20% 缓冲；优先砍范围（如先不做天空视图），不砍测试与数据校验。

## 10. 测试与验证计划

### 10.1 测试策略

采用“测试金字塔 + 黄金回归 + 现场验证”：

```text
        ┌ 现场/第三方验证（少量、高价值） ┐
        │ E2E/可用性（Playwright）          │
        │ 集成/API/数据库                   │
        │ 黄金回归（第 13 节等）            │
        │ 单元/属性测试（大量）             │
        └──────────────────────────────────┘
```

| 层次 | 工具 | 覆盖 |
|---|---|---|
| 单元 | pytest | 偏导、协方差、可靠性、投影、曲率、优化评分 |
| 属性 | Hypothesis | 对称/正定、单位换算、加观测单调性、快照往返 |
| 黄金 | pytest + JSON fixture | 第 13 节、GNSS/水准/通视固定算例 |
| 集成 | pytest + httpx | API、事务、迁移、导入导出 |
| E2E | Playwright | 建工程→选点→计算→导出→回读 |
| 性能 | pytest-benchmark | 300/1000/2000 点、1000 对通视、优化 |
| 现场 | 实测网/第三方软件 | 真实数据盲测 |

**覆盖率目标**：计算内核分支 ≥ 90%；API ≥ 80%；前端关键流程 E2E 全覆盖；不追求数字面子，关键路径必须有断言。

### 10.2 第 13 节黄金回归（必须保留）

#### 10.2.1 Fixture

- `fixtures/section13_base.json`：A/B 固定，C/D 待定，5 距离 + 2 角度，`a=0.002 m`、`b=2 ppm`、角度 1″。
- `fixtures/section13_added.json`：在基准上增加角 D-C-A。
- 固定 `parameter_order = [EC, NC, ED, ND]`；观测顺序固定；引擎选项固定（`confidence=0.95` 只影响显示，不影响标准椭圆）。
- 快照哈希写入 fixture，防止无意改输入。

#### 10.2.2 精度断言

| 方案 | 点 | `σ_E`/mm | `σ_N`/mm | `mp`/mm | `a`/`b`/mm |
|---|---|---|---|---|---|
| 基准 | C | 0.468 | 1.651 | 1.716 | 1.652 / 0.466 |
| 基准 | D | 0.468 | 1.651 | 1.716 | 1.652 / 0.466 |
| 增补 | C | 0.464 | 1.225 | 1.310 | 1.231 / 0.448 |
| 增补 | D | 0.467 | 1.199 | 1.287 | 1.200 / 0.465 |

| 边 | 基准 `σ_s`/mm | 基准相对 | 增补 `σ_s`/mm | 增补相对 |
|---|---|---|---|---|
| AC | 1.651 | 1:60565 | 1.225 | 1:81608 |
| BC | 1.183 | 1:119522 | 0.849 | 1:166638 |
| AD | 1.183 | 1:119522 | 0.886 | 1:159530 |
| BD | 1.651 | 1:60565 | 1.199 | 1:83407 |
| CD | 0.643 | 1:155427 | 0.638 | 1:156844 |

**容差**：绝对量 `±0.001 mm`；相对精度按 `σ_s` 反算，`±1×10⁻⁶` 相对；椭圆半轴 `±0.001 mm`；排序用舍入前值。

#### 10.2.3 结构/数值断言

- `rank(A) = 4`；基准 `redundancy = 3`，增补 `4`。
- `Cx` 对称：`max|Cx−Cxᵀ| < 1e-12`；最小特征值 ≥ `-1e-12`。
- `trace(Qv Ql⁻¹) = 3 / 4`（容差 1e-9）。
- `Cx` 与独立实现（手写矩阵/第二语言/符号推导）一致。
- 角度偏导用中心差分校验：步长 1e-6 rad，相对误差 < 1e-6；距离偏导同理。
- 参数顺序改变时，结果按索引重排后一致；观测顺序改变时，结果不变。
- 固定点协方差为 0；约束点协方差进入结果。

#### 10.2.4 可靠性断言

精度表来自原方案第 13 节；可靠性表是按本方案公式新增的回归期望（原文未给出），不是原文表格。在 `λ0=7.849、α=0.05、power=0.80` 下（完整表见 §5.4.6）：

| 方案 | 观测 | `r_i` | MDB | 外部最大/mm |
|---|---|---|---|---|
| 基准 | AC | 0.3252 | 9.875 mm | 6.663 |
| 基准 | BC | 0.6569 | 6.982 mm | 3.211 |
| 基准 | CD | 0.8975 | 5.944 mm | 0.305 |
| 基准 | ∠C-A-B | 0.0692 | 10.653″ | 4.807 |
| 增补 | AC | 0.6283 | 7.104 mm | 2.640 |
| 增补 | CD | 0.8994 | 5.938 mm | 0.301 |
| 增补 | ∠D-C-A | 0.0408 | 13.864″ | 3.180 |

**容差**：`r_i ±1×10⁻³`；MDB 相对 `±1×10⁻³`；外部影响 `±0.002 mm`。若更换 `λ0/α/power`，fixture 必须显式记录新参数并生成新期望值，不能悄悄改默认。

#### 10.2.5 禁止事项

- 不允许用“结果表四舍五入后相等”代替矩阵断言。
- 不允许为了让新算法通过而修改 §13 输入/参数顺序；如确需修改，走“基准变更评审”，同时保留旧 fixture。
- 不允许只在 UI 层做回归；CI 必须直接跑引擎。

### 10.3 分模块验证矩阵

| 模块 | 测试点 | 判定 |
|---|---|---|
| 坐标/投影 | 已知点 CRS 转换、尺度因子、收敛角符号、距离归算 | 与 PROJ/手算一致；尺度误差 < 1 ppm |
| 设计矩阵 | 距离/方向/角度/基线/水准偏导 | 与中心差分相对误差 < 1e-6 |
| 随机模型 | 对角/分块/完整 VCV；非正定拒绝；σ0 约定 | 正定校验；不重复乘 σ0² |
| 基准 | 固定/加权/最小/自由；秩亏诊断 | 零空间数量/类型正确；错误可定位 |
| 精度 | `mp`、椭圆、相对边、相对椭圆 | 与解析/独立实现一致 |
| 可靠性 | `r_i`、trace、MDB、外部 | 第 13 节 + 随机网与蒙特卡洛/公式对照 |
| 粗差 | w-test、数据 snooping、稳健 | 已知粗差可检出；无粗差误报率符合 α |
| GNSS | 基线方程、ECEF/ENU、相关 VCV、7 个零奇异值 | 合成网坐标/协方差正确 |
| 水准 | 高差方程、路线/环、秩 1、geoid | 闭合差/高程正确 |
| 通视 | 合成 DEM 遮挡、曲率折光、NoData | 判定与手算一致；四态正确 |
| 优化 | 贪心 vs 枚举、预算、可靠性约束、单调性 | ≤20 候选一致或 gap 可解释 |
| 持久化 | 快照往返、旧数据迁移、工程包 | ID/拓扑/哈希/数值一致 |
| API | 状态码、错误体、幂等、并发、取消 | 合约测试通过 |
| UI | 建网→计算→导出→回读 | Playwright 全流程 |

### 10.4 属性测试与不变量

- **协方差**：任意合法 `Ql` 生成的 `Cx` 对称、半正定；`Qv` 半正定。
- **加观测**：在相同条件下增加独立正权观测，`trace(Cx)` 不增（数值容差内）；若实现出现变差，报警。
- **单位**：米/毫米、弧度/角秒、ppm 换算往返一致。
- **旋转/平移**：自由网/相对精度在整体平移、旋转下不变（固定基准结果不适用）。
- **快照**：序列化→反序列化→再哈希一致；字段顺序不影响哈希。
- **优化**：预算增加，最优目标不劣；强制加入一个观测，目标不劣；删除一个观测，目标不应改善（或保持不变）。
- **可靠性**：`sum(r_i) = m − rank(A)`；独立观测 `0≤r_i≤1`；相关观测只断言 trace，不断言范围。

### 10.5 现场与第三方验证

1. **已知坐标测试场**：选取 5～10 个已知点，布设边角/导线/GNSS/水准，比较坐标、边长、方位、高程。
2. **独立软件对比**：至少与 1 套成熟平差软件/库对比（如学术软件、商业软件），比较 `Cx`、`mp`、残差、可靠性；差异要能解释。
3. **盲测**：外业数据不告诉算法“真值”，按流程设计→观测→平差→比较。
4. **第三方复算**：把 §13/典型网导出为 CSV/矩阵，由未参与开发的人员按文档复算。
5. **现场通视**：选 3～5 条长边，DEM 判定 vs 实际观测；记录误判原因（植被、建筑、气象）。

### 10.6 性能、安全与可用性测试

- **性能**：300/1000/2000 点；1000 对通视；150 候选优化；记录 P50/P95、内存峰值。
- **稳定性**：连续计算 100 次、取消/重启/断电恢复；无临时文件泄漏。
- **安全**：路径穿越、恶意 GeoJSON/TIFF、超大方差/坐标、SQL 注入、XSS；导入文件大小/类型限制。
- **可用性**：5 名目标用户完成“建网→计算→比较→导出”，记录步骤/错误/耗时；SUS 问卷目标 ≥ 75。
- **离线**：断网安装/启动/计算/导出；无外部 CDN 请求。

### 10.7 质量门禁

- 合并请求：单测 + lint + 类型检查 + §13 黄金必须过；核心引擎覆盖率不降。
- 发布：P0/P1 缺陷清零；性能达标；安装/升级/回滚演练；文档更新；许可清单更新。
- 数据迁移：旧工程样本 20 个，迁移成功率 100%；失败可回滚。

## 11. 风险与对策

| 风险 | 概率 | 影响 | 对策 | 触发/负责人 |
|---|---|---|---|---|
| 范围蔓延（GNSS/3D/优化一起上） | 高 | 高 | 按 MVP/V1/V2 切分；变更评审；每阶段只承诺一个垂直切片 | 项目经理/技术负责人 |
| 数学/协方差约定错误 | 中 | 高 | §13 黄金、有限差分、独立复算、代码评审；单位/σ0 显式 | 算法负责人 |
| 投影/基准混用 | 中 | 高 | CRS/基准必填；`coordinate_operation` 追溯；阈值警告；培训 | GIS/算法 |
| DEM 质量不足（DSM/NoData/分辨率） | 高 | 中 | 元数据/置信度；多源对比；关键边现场核验；四态而非布尔 | GIS |
| GNSS 基线协方差/相关性缺失 | 高 | 高 | 要求 3×3/跨基线 VCV；缺失时标记 empirical 并保守；独立软件对比 | GNSS 负责人 |
| 水准/geoid 基准不一致 | 中 | 高 | `height_type` 必填；geoid 版本/精度；转换协方差；禁止直接混用 | 高程负责人 |
| 优化非凸/求解器不可用 | 高 | 中 | 贪心兜底；MICP 只小规模；超时返回当前最优；不承诺全局最优 | 优化负责人 |
| 大规模性能不达标 | 中 | 中 | 稀疏/分区；性能基准；限制单网规模；后台任务 | 后端 |
| 桌面打包/GDAL/PROJ 体积与兼容 | 中 | 中 | CI 多平台打包；固定版本；sidecar 日志；安装包瘦身 | 构建负责人 |
| 地图/DEM 版权与体积 | 中 | 高 | 许可清单；按需分包；署名；企业版可选自有数据 | 产品/法务 |
| 数据丢失/版本错乱 | 低 | 高 | 快照不可变；WAL；自动备份；导出校验；审计 | 后端 |
| 单用户本地安全 | 低 | 中 | 本地令牌；路径限制；导入校验；日志脱敏 | 安全 |
| 团队测绘/优化能力不足 | 中 | 高 | 领域专家评审；pair review；培训；先做小规模原型 | 技术负责人 |
| 进度延期 | 高 | 中 | 15%～20% 缓冲；砍范围不砍质量；双周演示 | 项目经理 |
| 用户不接受新流程 | 中 | 中 | 试点共创；保留旧导入/导出；快捷键/批量；培训 | 产品 |
| 规范/资质要求变化 | 低 | 中 | 精度/限差可配置；报告留出版本；不硬编码规范值 | 领域专家 |

**最高优先级的三件事**：

1. 先把第 13 节和可靠性基准做成 CI 黄金，任何算法改动必须过。
2. 先把“投影/基准/单位”做成强约束和可追溯，否则后面所有精度都不可信。
3. 优化先做贪心 + 人工确认，不要一上来追求全局最优而拖垮交付。

## 12. 结论与下一步

### 12.1 结论

原方案的**业务闭环、版本机制、数学主干和第 13 节算例**值得完整保留；主要问题不是“公式不对”，而是**架构边界、数据模型、可靠性、优化和多源网型**没有展开。重设计的核心不是重写公式，而是：

- 用**不可变快照 + 纯计算内核**把“设计/计算/发布”解耦；
- 用**类型化观测 + 全局点身份**支撑 GNSS/水准/平面多网型；
- 用**`r_i`/MDB/外部可靠性**把“精度”升级为“精度 + 检核能力”；
- 用**贪心/整数规划 + A/D/E**把“手工试算”升级为“可解释的优化”；
- 用**投影归算 + DEM 通视 + 曲率折光**把“地图上好看”升级为“外业可实施”；
- 用**第 13 节 + 分模块回归 + 现场验证**保证每一步都可复现。

### 12.2 未来两周可执行清单

1. 建 `fixtures/section13_*.json`，用独立脚本复算并冻结期望值（精度 + 可靠性）。
2. 评审并定稿 `DesignSnapshot` schema、`Observation` 类型注册、`NetworkPoint` 关系。
3. 搭 FastAPI + SQLite + MapLibre + MBTiles 最小闭环，跑通“选点→建观测→快照→计算→结果”。
4. 定稿投影/基准/单位契约，写 5 个已知点/已知边的投影与归算单测。
5. 选 1 个真实小测区做试点，收集地图/DEM/GNSS/水准样本，验证数据模型。
6. 建 CI：lint + 单测 + §13 黄金 + 构建安装包；把“黄金不过不能合并”设为硬门禁。

### 12.3 成功标准（项目级）

- 设计人员能在 30 分钟内完成一个 20～50 点平面网的设计、计算、比较和导出。
- 第 13 节及扩展基准在 CI 中稳定通过；任何精度结果都能追溯到快照/引擎/参数。
- 至少 1 个真实项目用本系统完成“平面 + GNSS/水准 + 通视”联合设计，结果与独立软件/现场观测在项目容差内一致。
- 用户能看懂“为什么这个方案更优/为什么不满足可靠性”，而不是只看到一个分数。

