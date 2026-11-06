# 底图与坐标策略

用户本轮要求覆盖旧 target_spec 的禁止一切在线瓦片条款：默认离线 DEM，可选公开 XYZ，无商业 SDK，无百度私有 token，不提供 BD-09 底图。

- 道路：[OSM 标准 XYZ 使用政策](https://operations.osmfoundation.org/policies/tiles/)。浏览器正常请求、保留 Referer/缓存与可见署名，不批量下载或预抓取。
- 影像：[Esri World Imagery 服务元数据](https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer?f=pjson)。公开无 key 端点，不保证永久可用；署名 Esri/Vantor/Earthstar/GIS User Community。具体使用遵守源条款。
- 仅用户选择网络层后创建实际请求，后端不代理、不联网探测、不存储凭据。单瓦片错误立即回退 DEM；首次请求 12 秒无成功瓦片回退。状态不会把失败说成已加载。
- 离线 MBTiles 元数据含经纬度范围、真实 zoom，Leaflet 在 EPSG:3857 下使用现有 XYZ 路由。样本位于北京约 116°E/40°N，不覆盖徐州；范围外保留 DEM，不伪称该处存在瓦片。
- 论文页地图经纬度使用 WGS84 交换，WebMercator 显示；精度计算使用工程所选 CGCS2000 高斯或 WGS84 UTM（k0=0.9996）x北/y东；可编辑中央子午线、3°/6°、假东。未应用 WGS84→CGCS2000 七参数，不把显示点位作为测量成果。局部算例 2 按徐州锚点在所选投影中的坐标平移；演示默认仍为117°。
- 仪表盘 `/`、`/dashboard` 已原地支持四类底图。离线 DEM 保留 EPSG:32650 米制 CRS.Simple；MBTiles/OSM/Esri 使用独立 EPSG:3857 视图，UTM→经纬度复用现有 Krüger 反算与 UTM k0，不依赖可选 pyproj。控制点、观测线和放大椭圆重投影；地图可见 CRS 状态及署名，方案切换同步网络图形。
- XYZ 视图不叠加原生米制 DEM 栅格、等高线或配准图；对应控件禁用并提示切回离线 DEM，两点剖面也保留在离线模式。旧米制 MBTiles 预览入口仍保留，新的底图选择则走真实 XYZ。MBTiles 选择展示覆盖范围/原生级别，初始视窗无覆盖或瓦片缺失也回退 DEM。
- 当前仪表盘的示例测区本身位于北京，真实本地 MBTiles 覆盖该测区；论文默认徐州不在该覆盖内。batch2 Chromium 验证了真实本地瓦片成功、公开源路由 mock 成功、mock 请求错误和真实等待12秒超时；没有宣称本批实际验证公网 OSM/Esri 可用性。
- 本批不是百度地图适配；未使用百度 token、BD-09/GCJ-02，也未引入默认 BD-09 转换。投影参数编辑不是基准七参数转换或任意 EPSG 导入。
