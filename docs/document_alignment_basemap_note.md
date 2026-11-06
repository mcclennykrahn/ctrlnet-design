# 底图与坐标策略

用户本轮要求覆盖旧 target_spec 的禁止一切在线瓦片条款：默认离线 DEM，可选公开 XYZ，无商业 SDK，无百度私有 token，不提供 BD-09 底图。

- 道路：[OSM 标准 XYZ 使用政策](https://operations.osmfoundation.org/policies/tiles/)。浏览器正常请求、保留 Referer/缓存与可见署名，不批量下载或预抓取。
- 影像：[Esri World Imagery 服务元数据](https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer?f=pjson)。公开无 key 端点，不保证永久可用；署名 Esri/Vantor/Earthstar/GIS User Community。具体使用遵守源条款。
- 仅用户选择网络层后创建实际请求，后端不代理、不联网探测、不存储凭据。单瓦片错误立即回退 DEM；首次请求 12 秒无成功瓦片回退。状态不会把失败说成已加载。
- 离线 MBTiles 元数据含经纬度范围、真实 zoom，Leaflet 在 EPSG:3857 下使用现有 XYZ 路由。样本位于北京约 116°E/40°N，不覆盖徐州；范围外保留 DEM，不伪称该处存在瓦片。
- 论文页地图经纬度使用 WGS84 交换，WebMercator 显示；精度计算使用 CGCS2000 三度带高斯 x北/y东。未应用 WGS84→CGCS2000 七参数，不把显示点位作为测量成果。局部算例 2 按固定高斯原点平移。
- 仪表盘是 EPSG:32650 米制 CRS.Simple；本批提供论文页入口，未强塞 WebMercator 瓦片。统一投影视图迁移、任意中央子午线编辑与 BD-09 配置仍未完成。
