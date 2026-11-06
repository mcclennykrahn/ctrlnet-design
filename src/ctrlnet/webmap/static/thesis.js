/* 离线优先；仅显式选择网络底图后请求公开 XYZ。 */
(function () {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const state = {
    data: null,
    map: null,
    layers: {},
    examples: [],
    lastResult: null,
    gradeTouched: false,
    nameDirty: false,
    busy: false,
    toastTimer: null,
    baseBounds: [117.1, 34.15, 117.3, 34.25],
  };

  function escapeHtml(value) {
    return String(value)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function num(value, digits) {
    const number = Number(value);
    return Number.isFinite(number) ? number.toFixed(digits) : "—";
  }

  const undoStack = [];
  let restoring = false;
  async function api(path, options) {
    const opts = Object.assign({}, options || {});
    const headers = Object.assign({ Accept: "application/json" }, opts.headers || {});
    if (opts.body && typeof opts.body !== "string") {
      opts.body = JSON.stringify(opts.body);
    }
    if (opts.body) headers["Content-Type"] = "application/json";
    opts.headers = headers;
    const response = await fetch(path, opts);
    const text = await response.text();
    let payload = null;
    if (text) {
      try { payload = JSON.parse(text); } catch (err) { payload = null; }
    }
    if (!response.ok) {
      let detail = payload && payload.detail;
      if (Array.isArray(detail)) {
        detail = detail.map((item) => item.msg || JSON.stringify(item)).join("；");
      }
      throw new Error(detail || text || `请求失败（HTTP ${response.status}）`);
    }
    if (opts.method && opts.method !== "GET" && state.data && !restoring &&
        !path.includes("calculate") && !path.includes("projects/save")) {
      undoStack.push(JSON.parse(JSON.stringify(state.data)));
      if (undoStack.length > 20) undoStack.shift();
    }
    return payload;
  }

  function toast(message, isError) {
    const node = $("toast");
    node.textContent = message;
    node.classList.toggle("error", Boolean(isError));
    node.classList.remove("hidden");
    clearTimeout(state.toastTimer);
    state.toastTimer = setTimeout(() => node.classList.add("hidden"), isError ? 5200 : 2800);
  }

  function setBusy(busy) {
    state.busy = busy;
    document.querySelectorAll("button").forEach((button) => {
      if (button.dataset.keepEnabled === "1") return;
      if (busy) button.dataset.wasDisabled = button.disabled ? "1" : "0";
      if (busy) button.disabled = true;
      else if (button.dataset.wasDisabled !== undefined) {
        button.disabled = button.dataset.wasDisabled === "1";
        delete button.dataset.wasDisabled;
      }
    });
  }

  // ------------------------------------------------------------------
  // 地图
  // ------------------------------------------------------------------
  function initMap() {
    const bounds = (state.data && state.data.basemap && state.data.basemap.bounds) || state.baseBounds;
    state.baseBounds = bounds.slice(0, 4).map(Number);
    const map = L.map("map", {
      zoomControl: false,
      attributionControl: false,
      minZoom: 2,
      maxZoom: 20,
      preferCanvas: false,
    });
    state.map = map;

    L.control.zoom({ position: "topleft" }).addTo(map);
    L.control
      .scale({ position: "bottomleft", metric: true, imperial: false, maxWidth: 170 })
      .addTo(map);
    L.control
      .attribution({ position: "bottomright", prefix: false })
      .addAttribution("Copernicus DEM · 本地离线渲染")
      .addTo(map);

    const south = state.baseBounds[1];
    const west = state.baseBounds[0];
    const north = state.baseBounds[3];
    const east = state.baseBounds[2];
    const imageBounds = [[south, west], [north, east]];
    if (!state.data || !state.data.basemap || state.data.basemap.png_exists !== false) {
      state.offlineBase = L.imageOverlay("/api/thesis/basemap.png", imageBounds, {
        opacity: 1,
        interactive: false,
        crossOrigin: false,
      }).addTo(map);
    }
    map.fitBounds(imageBounds);

    const badge = L.DomUtil.create("div", "map-badge-map");
    badge.textContent = "离线 DEM";
    map.getContainer().appendChild(badge);

    // 轻量经纬网，帮助辨认徐州示例区域。
    const grid = L.layerGroup().addTo(map);
    for (let lon = Math.ceil(west * 20) / 20; lon < east; lon += 0.05) {
      L.polyline([[south, lon], [north, lon]], {
        color: "#c5cec0", weight: 0.6, opacity: 0.5, dashArray: "2 5", interactive: false,
      }).addTo(grid);
    }
    for (let lat = Math.ceil(south * 20) / 20; lat < north; lat += 0.05) {
      L.polyline([[lat, west], [lat, east]], {
        color: "#c5cec0", weight: 0.6, opacity: 0.5, dashArray: "2 5", interactive: false,
      }).addTo(grid);
    }
    state.layers.grid = grid;
    setupBasemaps();

    state.layers.ellipses = L.layerGroup().addTo(map);
    state.layers.angles = L.layerGroup().addTo(map);
    state.layers.lines = L.layerGroup().addTo(map);
    state.layers.points = L.layerGroup().addTo(map);

    map.on("click", onMapClick);
    map.on("mousemove", (event) => {
      $("map-coord").textContent = `${event.latlng.lng.toFixed(6)}°E, ${event.latlng.lat.toFixed(6)}°N`;
    });
    map.on("zoomend", drawAngles);
  }

  async function setupBasemaps() {
    const select = $("basemap-select"), status = $("basemap-status");
    const bases = { offline: state.offlineBase };
    let active = "offline", timer;
    function activate(id, failure) {
      clearTimeout(timer);
      if (bases[active]) state.map.removeLayer(bases[active]);
      active = id;
      select.value = id;
      state.map.getContainer().querySelector(".map-badge-map").textContent = select.selectedOptions[0].textContent.split("（")[0];
      if (bases[id]) bases[id].addTo(state.map);
      const online = id === "road" || id === "satellite";
      status.textContent = failure || (online ? "正在加载网络瓦片…（WGS84 / EPSG:3857）" : id === "offline" ? "离线 DEM · 不请求网络" : "离线 MBTiles；范围外无数据，已保留 DEM 回退");
      if (online) timer = setTimeout(() => activate("offline", "瓦片未加载（超时），已回退离线 DEM"), 12000);
    }
    try {
      const [config, tiles] = await Promise.all([api("/api/basemaps"), api("/api/tiles")]);
      for (const source of config.sources) {
        const layer = L.tileLayer(source.url, { maxNativeZoom: source.maxNativeZoom, maxZoom: 20, attribution: source.attribution });
        bases[source.id] = layer;
        layer.on("tileerror", () => { if (active === source.id) activate("offline", "瓦片未加载（网络错误），已回退离线 DEM"); });
        layer.on("loading", () => { if (active === source.id) { clearTimeout(timer); status.textContent = "正在加载网络瓦片…"; timer = setTimeout(() => activate("offline", "瓦片未加载（超时），已回退离线 DEM"), 12000); } });
        layer.on("load", () => { if (active === source.id) { clearTimeout(timer); status.textContent = source.label + " · 当前视窗瓦片已加载 · WGS84 / EPSG:3857"; } });
        select.add(new Option(source.label, source.id));
      }
      for (const resource of tiles.resources) {
        const m = resource.metadata, bounds = (m.bounds || "").split(",").map(Number);
        if (bounds.length !== 4 || !bounds.every(Number.isFinite)) continue;
        const id = "mbtiles:" + resource.name;
        bases[id] = L.layerGroup([L.imageOverlay("/api/thesis/basemap.png", [[state.baseBounds[1],state.baseBounds[0]],[state.baseBounds[3],state.baseBounds[2]]]),
          L.tileLayer("/tiles/" + encodeURIComponent(resource.name) + "/{z}/{x}/{y}.png", { minNativeZoom: Number(m.minzoom || 0), maxNativeZoom: Number(m.maxzoom || 18), maxZoom: 20, bounds: [[bounds[1],bounds[0]],[bounds[3],bounds[2]]], attribution: "本地 MBTiles · " + escapeHtml(resource.name) })]);
        select.add(new Option("离线 MBTiles · " + resource.name + "（" + bounds.map(v => v.toFixed(2)).join(",") + "；z" + m.minzoom + "–" + m.maxzoom + "）", id));
      }
      select.addEventListener("change", () => activate(select.value));
    } catch (err) { status.textContent = "底图配置失败；保留离线 DEM：" + err.message; }
  }

  async function importCoordinateFile(event) {
    const file = event.target.files[0];
    if (!file) return;
    try {
      if (file.size > 1000000) throw new Error("文件不得超过 1 MB");
      const text = await file.text();
      if (!window.confirm("导入将覆盖当前点/线/角/观测；请先命名保存。继续？")) return;
      setBusy(true);
      const payload = await api("/api/thesis/import/coordinates", {method: "POST", body: {text, name: file.name}});
      state.nameDirty = false;
      state.gradeTouched = false;
      applyState(payload, {fit:true});
      toast("已导入 " + payload.points.length + " 点；请设置已知点并构线构角");
    } catch (err) { toast(err.message, true); }
    finally { setBusy(false); event.target.value = ""; }
  }

  async function onMapClick(event) {
    if (state.busy) return;
    try {
      setBusy(true);
      const payload = await api("/api/thesis/points", {
        method: "POST",
        body: { lon: event.latlng.lng, lat: event.latlng.lat },
      });
      applyState(payload);
      toast(`已添加点 ${payload.points[payload.points.length - 1].name}`);
    } catch (err) {
      toast(err.message, true);
    } finally {
      setBusy(false);
    }
  }

  function fitToPoints() {
    if (!state.map) return;
    const points = state.data && state.data.points ? state.data.points : [];
    if (!points.length) {
      state.map.fitBounds([
        [state.baseBounds[1], state.baseBounds[0]],
        [state.baseBounds[3], state.baseBounds[2]],
      ]);
      return;
    }
    const bounds = L.latLngBounds(points.map((point) => [point.lat, point.lon]));
    state.map.fitBounds(bounds.pad(0.35), { maxZoom: points.length > 1 ? 16 : 15 });
  }

  function pointIcon(point) {
    const fixed = point.fixed ? "fixed" : "";
    const ring = point.fixed
      ? '<circle class="fixed-ring" cx="17" cy="15.5" r="9.2"></circle>'
      : "";
    return L.divIcon({
      className: "point-icon-wrap",
      html:
        `<div class="point-marker ${fixed}">` +
        '<svg viewBox="0 0 34 46" aria-hidden="true">' +
        '<path class="body" d="M17 2.1C9.5 2.1 3.5 8 3.5 15.3c0 9.7 13.5 26.4 13.5 26.4s13.5-16.7 13.5-26.4C30.5 8 24.5 2.1 17 2.1z" ' +
        'fill="#e53935" stroke="#ffffff" stroke-width="2.1" stroke-linejoin="round"></path>' +
        ring +
        "</svg>" +
        `<span class="point-num">${escapeHtml(point.name)}</span>` +
        "</div>",
      iconSize: [34, 46],
      iconAnchor: [17, 45],
      popupAnchor: [0, -40],
    });
  }

  function drawPoints() {
    if (!state.map || !state.data) return;
    const layer = state.layers.points;
    layer.clearLayers();
    state.data.points.forEach((point) => {
      const marker = L.marker([point.lat, point.lon], {
        icon: pointIcon(point),
        title: `点 ${point.name}`,
        riseOnHover: true,
      });
      const type = point.fixed ? "已知点" : "未知点";
      marker.bindPopup(
        `<strong>点 ${escapeHtml(point.name)}</strong>（${type}）<br>` +
          `经度 ${num(point.lon, 6)}°<br>纬度 ${num(point.lat, 6)}°<br>` +
          `x=${num(point.x, 3)} m，y=${num(point.y, 3)} m`
      );
      marker.addTo(layer);
    });
  }

  function drawLines() {
    if (!state.map || !state.data) return;
    const layer = state.layers.lines;
    layer.clearLayers();
    const byId = new Map(state.data.points.map((point) => [point.id, point]));
    state.data.lines.forEach((line) => {
      const a = byId.get(line.from);
      const b = byId.get(line.to);
      if (!a || !b) return;
      let style;
      if (line.status === "added") {
        style = { color: "#f2b705", weight: 3.2, opacity: 1, dashArray: null };
      } else if (line.status === "observed") {
        style = { color: "#e53935", weight: 3, opacity: 1, dashArray: null };
      } else {
        style = { color: "#3c9a4a", weight: 1.7, opacity: 0.95, dashArray: "7 5" };
      }
      L.polyline([[a.lat, a.lon], [b.lat, b.lon]], Object.assign({
        lineCap: "round",
        interactive: true,
      }, style))
        .bindTooltip(
          `线 ${line.name}：${escapeHtml(line.from_name)}–${escapeHtml(line.to_name)}<br>` +
            `距离 ${num(line.length, 4)} m，方位 ${num(line.azimuth, 4)}°`,
          { sticky: true }
        )
        .addTo(layer);
    });
  }

  function bearing(a, b) {
    const meanLat = ((a.lat + b.lat) / 2) * Math.PI / 180;
    const dEast = (b.lon - a.lon) * Math.cos(meanLat);
    const dNorth = b.lat - a.lat;
    return (Math.atan2(dEast, dNorth) * 180 / Math.PI + 360) % 360;
  }

  function angleRadiusMeters() {
    if (!state.map) return 24;
    const lat = state.map.getCenter().lat;
    const metresPerPixel =
      (156543.03392 * Math.cos(lat * Math.PI / 180)) / Math.pow(2, state.map.getZoom());
    return Math.max(10, Math.min(260, 17 * metresPerPixel));
  }

  function destination(lat, lon, bearingDeg, distanceM) {
    const theta = bearingDeg * Math.PI / 180;
    const dLat = (distanceM * Math.cos(theta)) / 110574.0;
    const dLon = (distanceM * Math.sin(theta)) / (111320.0 * Math.cos(lat * Math.PI / 180));
    return [lat + dLat, lon + dLon];
  }

  function drawAngles() {
    if (!state.map || !state.data) return;
    const layer = state.layers.angles;
    layer.clearLayers();
    const byId = new Map(state.data.points.map((point) => [point.id, point]));
    const radius = angleRadiusMeters();
    state.data.angles.forEach((angle) => {
      const backsight = byId.get(angle.backsight);
      const station = byId.get(angle.station);
      const foresight = byId.get(angle.foresight);
      if (!backsight || !station || !foresight) return;
      const azBack = bearing(station, backsight);
      const azFore = bearing(station, foresight);
      let delta = ((azFore - azBack + 540) % 360) - 180;
      const steps = 18;
      const arc = [];
      for (let index = 0; index <= steps; index += 1) {
        const theta = azBack + (delta * index) / steps;
        arc.push(destination(station.lat, station.lon, theta, radius));
      }
      let color = "#8b9489";
      let dashArray = "4 4";
      let weight = 1.6;
      if (angle.status === "added") {
        color = "#f2b705";
        dashArray = null;
        weight = 2.4;
      } else if (angle.status === "observed") {
        color = "#ef7d22";
        dashArray = null;
        weight = 2.2;
      }
      L.polyline(arc, {
        color, weight, opacity: 0.95, dashArray, interactive: false, lineCap: "round",
      }).addTo(layer);
      const start = destination(station.lat, station.lon, azBack, radius);
      const end = destination(station.lat, station.lon, azFore, radius);
      L.polyline([[station.lat, station.lon], start], {
        color, weight: Math.max(0.8, weight - 0.9), opacity: 0.6, dashArray: "3 4", interactive: false,
      }).addTo(layer);
      L.polyline([[station.lat, station.lon], end], {
        color, weight: Math.max(0.8, weight - 0.9), opacity: 0.6, dashArray: "3 4", interactive: false,
      }).addTo(layer);
      L.circleMarker([station.lat, station.lon], {
        radius: 2.2, color, weight: 1, fillColor: color, fillOpacity: 0.9, interactive: false,
      }).addTo(layer);
      L.circleMarker([station.lat, station.lon], {
        radius: Math.max(8, radius / state.map.distance([station.lat, station.lon], [arc[0][0], arc[0][1]]) * 0.9),
        color: "transparent", fillColor: "transparent", interactive: false,
      }).bindTooltip(
        `角 ${angle.name}：${escapeHtml(angle.backsight_name)}–${escapeHtml(angle.station_name)}–${escapeHtml(angle.foresight_name)} = ${num(angle.value, 4)}°`,
        { sticky: true }
      ).addTo(layer);
    });
  }

  function drawEllipses() {
    if (!state.map || !state.data) return;
    const layer = state.layers.ellipses;
    layer.clearLayers();
    if (!state.lastResult || !$("show-ellipses").checked) return;
    const scale = Math.max(1, Number($("ellipse-scale").value) || 1);
    const byName = new Map(state.data.points.map((point) => [point.name, point]));
    const phiColor = "#6f3a91";
    (state.lastResult.ellipses || []).forEach((item) => {
      const point = byName.get(item.name);
      if (!point) return;
      const a = (Number(item.E_mm) / 1000) * scale;
      const b = (Number(item.F_mm) / 1000) * scale;
      if (!(a > 0) || !(b > 0)) return;
      const phi = (Number(item.phi_E_deg) * Math.PI) / 180;
      const cosLat = Math.cos((point.lat * Math.PI) / 180);
      const coords = [];
      for (let index = 0; index < 72; index += 1) {
        const theta = (index / 72) * Math.PI * 2;
        const east = a * Math.cos(theta) * Math.sin(phi) + b * Math.sin(theta) * Math.cos(phi);
        const north = a * Math.cos(theta) * Math.cos(phi) - b * Math.sin(theta) * Math.sin(phi);
        coords.push([
          point.lat + north / 110574.0,
          point.lon + east / (111320.0 * cosLat),
        ]);
      }
      L.polygon(coords, {
        color: phiColor, weight: 1.1, opacity: 0.9,
        fillColor: phiColor, fillOpacity: 0.045, dashArray: "3 3",
      }).bindTooltip(
        `点 ${escapeHtml(item.name)} 误差椭圆：E=${num(item.E_mm, 2)} mm，F=${num(item.F_mm, 2)} mm，φE=${num(item.phi_E_deg, 2)}°`,
        { sticky: true }
      ).addTo(layer);
      const tip = destination(point.lat, point.lon, Number(item.phi_E_deg) || 0, a);
      L.polyline([[point.lat, point.lon], tip], {
        color: phiColor, weight: 0.8, opacity: 0.55, dashArray: "2 3", interactive: false,
      }).addTo(layer);
    });
  }

  // ------------------------------------------------------------------
  // 右侧四库渲染
  // ------------------------------------------------------------------
  function setEmpty(id, empty) {
    const node = $(id);
    if (node) node.classList.toggle("hidden", !empty);
  }

  function renderPoints() {
    const body = $("point-body");
    const points = state.data.points || [];
    body.innerHTML = points
      .map((point) => {
        const selected = point.fixed ? "known" : "unknown";
        return (
          `<tr data-id="${escapeHtml(point.id)}">` +
          `<td>${escapeHtml(point.name)}</td>` +
          `<td class="num">${num(point.lon, 6)}</td>` +
          `<td class="num">${num(point.lat, 6)}</td>` +
          `<td class="num">${num(point.x, 3)}</td><td class="num">${num(point.y, 3)}</td>` +
          `<td><select class="fixed-select ${point.fixed ? "known" : ""}" data-action="toggle-fixed" data-id="${escapeHtml(point.id)}">` +
          `<option value="unknown" ${selected === "unknown" ? "selected" : ""}>未知</option>` +
          `<option value="known" ${selected === "known" ? "selected" : ""}>已知</option>` +
          `</select></td>` +
          `<td><button class="link-button" type="button" data-action="delete-point" data-id="${escapeHtml(point.id)}">删除</button></td>` +
          `</tr>`
        );
      })
      .join("");
    $("point-count").textContent = String(points.length);
    setEmpty("point-empty", points.length === 0);
    $("point-summary").textContent = points.length
      ? `共 ${points.length} 点，已知 ${points.filter((p) => p.fixed).length}，未知 ${points.filter((p) => !p.fixed).length}`
      : "";
  }

  function renderLines() {
    const body = $("line-body");
    const lines = state.data.lines || [];
    body.innerHTML = lines
      .map(
        (line) =>
          `<tr data-id="${escapeHtml(line.id)}">` +
          `<td>${line.name}</td>` +
          `<td class="endpoint">${escapeHtml(line.from_name)}</td>` +
          `<td class="endpoint">${escapeHtml(line.to_name)}</td>` +
          `<td class="num">${num(line.length, 4)}</td>` +
          `<td class="num">${num(line.azimuth, 4)}</td>` +
          `<td><button class="link-button" type="button" data-action="delete-line" data-id="${escapeHtml(line.id)}">删除</button></td>` +
          `</tr>`
      )
      .join("");
    $("line-count").textContent = String(lines.length);
    setEmpty("line-empty", lines.length === 0);
  }

  function renderAngles() {
    const body = $("angle-body");
    const angles = state.data.angles || [];
    body.innerHTML = angles
      .map(
        (angle) =>
          `<tr data-id="${escapeHtml(angle.id)}">` +
          `<td>${angle.name}</td>` +
          `<td class="endpoint">${escapeHtml(angle.backsight_name)}</td>` +
          `<td class="endpoint">${escapeHtml(angle.station_name)}</td>` +
          `<td class="endpoint">${escapeHtml(angle.foresight_name)}</td>` +
          `<td class="num">${num(angle.value, 4)}</td>` +
          `<td><button class="link-button" type="button" data-action="delete-angle" data-id="${escapeHtml(angle.id)}">删除</button></td>` +
          `</tr>`
      )
      .join("");
    $("angle-count").textContent = String(angles.length);
    setEmpty("angle-empty", angles.length === 0);
  }

  function chipLabel(item, kind) {
    if (kind.endsWith("edge")) {
      return `${item.name}. ${item.from_name}–${item.to_name}`;
    }
    return `${item.name}. ${item.backsight_name}–${item.station_name}–${item.foresight_name}`;
  }

  function statusText(item, mode) {
    if (mode === "added") {
      return item.status === "added" ? "新增" : "";
    }
    if (item.status === "observed") return "已观测";
    if (item.status === "added") return "新增";
    return "图形";
  }

  function renderCheckList(containerId, items, selectedIds, kind, mode) {
    const container = $(containerId);
    const selected = new Set(selectedIds || []);
    container.classList.toggle("empty", !items.length);
    if (!items.length) {
      container.innerHTML = '<span class="muted">暂无条目</span>';
      return;
    }
    container.innerHTML = items
      .map((item) => {
        const checked = selected.has(item.id) ? "checked" : "";
        const status = statusText(item, mode);
        const statusClass = item.status === "added" ? "added" : item.status === "observed" ? "observed" : "";
        return (
          `<label title="${escapeHtml(chipLabel(item, kind))}">` +
          `<input type="checkbox" data-kind="${kind}" data-id="${escapeHtml(item.id)}" ${checked} />` +
          `<span>${escapeHtml(chipLabel(item, kind))}</span>` +
          (status ? `<span class="chip-status ${statusClass}">${status}</span>` : "") +
          `</label>`
        );
      })
      .join("");
  }

  function renderNetwork() {
    const network = state.data.network || {};
    const summary = state.data.summary || {};
    $("network-count").textContent = `${summary.n_lines || 0} 边 / ${summary.n_angles || 0} 角`;
    const gradeSelect = $("grade-select");
    if (document.activeElement !== gradeSelect) {
      gradeSelect.value = network.grade || "二级";
    }
    if (!state.gradeTouched && (state.data.lines || []).length && summary.suggested_grade) {
      gradeSelect.value = summary.suggested_grade;
    }
    $("tolerance-input").value = network.tolerance_mm || 20;
    $("show-ellipses").checked = network.show_ellipses !== false;
    if (document.activeElement !== $("ellipse-scale")) {
      $("ellipse-scale").value = network.ellipse_scale || 2000;
    }
    const avg = Number(summary.avg_side_m) || 0;
    const km = avg / 1000;
    $("grade-suggestion").innerHTML =
      `平均边长 <strong>${num(avg, 1)} m</strong>（${num(km, 3)} km），` +
      `建议等级 <strong>${escapeHtml(summary.suggested_grade || "—")}</strong>` +
      (state.gradeTouched ? ' <span class="muted">（已手动选择）</span>' : "") +
      (avg > 0 ? ' <button class="link-button" type="button" data-action="apply-suggest">采用建议</button>' : "");

    const lines = state.data.lines || [];
    const angles = state.data.angles || [];
    renderCheckList("observed-edge-list", lines, network.observed_edges, "observed-edge", "observed");
    renderCheckList("observed-angle-list", angles, network.observed_angles, "observed-angle", "observed");
    // 新增观测只能从未观测的边/角中选择，保证优化对比的基准网仍然满秩。
    const observedEdgeSet = new Set(network.observed_edges || []);
    const observedAngleSet = new Set(network.observed_angles || []);
    renderCheckList(
      "added-edge-list",
      lines.filter((line) => !observedEdgeSet.has(line.id)),
      network.added_edges,
      "added-edge",
      "added"
    );
    renderCheckList(
      "added-angle-list",
      angles.filter((angle) => !observedAngleSet.has(angle.id)),
      network.added_angles,
      "added-angle",
      "added"
    );
  }

  function applyState(payload, options) {
    const opts = options || {};
    state.data = payload;
    const projection = payload.projection;
    if (projection) {
      $("projection-cm").value = projection.central_meridian;
      $("projection-width").value = projection.zone_width;
      $("projection-convention").value = projection.convention || "gauss";
      $("projection-fe").value = projection.false_easting_m;
    }
    $("projection-summary").textContent = projection ? `${projection.ellipsoid} · ${projection.convention || "gauss"} · 中央子午线 ${projection.central_meridian}°E · ${projection.zone_width}°带 / 带号 ${projection.zone_number} · 假东 ${projection.false_easting_m} m · ${projection.axis}。${projection.note}。不使用 BD-09。` : "";
    state.lastResult = opts.keepResult ? state.lastResult : null;
    if (!state.nameDirty && payload.name) $("project-name").value = payload.name;
    renderPoints();
    renderLines();
    renderAngles();
    renderNetwork();
    document.body.classList.toggle(
      "empty-project",
      !(payload.points || []).length &&
        !(payload.lines || []).length &&
        !(payload.angles || []).length
    );
    if (state.map) {
      drawPoints();
      drawLines();
      drawAngles();
      if (opts.fit) fitToPoints();
      if (opts.keepResult) drawEllipses();
      else state.layers.ellipses.clearLayers();
    }
    if (!opts.keepResult) hideResult();
  }

  // ------------------------------------------------------------------
  // 表单操作
  // ------------------------------------------------------------------
  function collectChecks(containerId) {
    return Array.from($(containerId).querySelectorAll('input[type="checkbox"]:checked')).map(
      (input) => input.dataset.id
    );
  }

  async function syncNetwork(extra) {
    const payload = Object.assign(
      {
        grade: $("grade-select").value,
        observed_edges: collectChecks("observed-edge-list"),
        observed_angles: collectChecks("observed-angle-list"),
        added_edges: collectChecks("added-edge-list"),
        added_angles: collectChecks("added-angle-list"),
        tolerance_mm: Number($("tolerance-input").value) || 20,
        ellipse_scale: Number($("ellipse-scale").value) || 2000,
        show_ellipses: $("show-ellipses").checked,
      },
      extra || {}
    );
    const payloadState = await api("/api/thesis/network", { method: "POST", body: payload });
    const keep = Boolean(state.lastResult);
    applyState(payloadState, { keepResult: keep });
    if (keep) drawEllipses();
  }

  async function addLine() {
    const from = Number($("line-start").value);
    const to = Number($("line-end").value);
    if (!Number.isInteger(from) || !Number.isInteger(to)) {
      toast("请输入起点/终点编号", true);
      return;
    }
    try {
      setBusy(true);
      const payload = await api("/api/thesis/lines", {
        method: "POST",
        body: { from: String(from), to: String(to) },
      });
      applyState(payload);
      $("line-start").value = from + 1 <= payload.points.length ? from + 1 : "";
      $("line-end").value = "";
      if (!state.gradeTouched) await autoApplySuggestedGrade();
      toast(`已构线 ${from}–${to}`);
    } catch (err) {
      toast(err.message, true);
    } finally {
      setBusy(false);
    }
  }

  async function addAngle() {
    const backsight = Number($("angle-back").value);
    const station = Number($("angle-station").value);
    const foresight = Number($("angle-fore").value);
    if (![backsight, station, foresight].every(Number.isInteger)) {
      toast("请输入后视/测站/前视编号", true);
      return;
    }
    try {
      setBusy(true);
      const payload = await api("/api/thesis/angles", {
        method: "POST",
        body: {
          backsight: String(backsight),
          station: String(station),
          foresight: String(foresight),
        },
      });
      applyState(payload);
      $("angle-back").value = "";
      $("angle-station").value = "";
      $("angle-fore").value = "";
      toast(`已构角 ${backsight}–${station}–${foresight}`);
    } catch (err) {
      toast(err.message, true);
    } finally {
      setBusy(false);
    }
  }

  async function autoApplySuggestedGrade() {
    const suggested = state.data && state.data.summary ? state.data.summary.suggested_grade : null;
    if (!suggested) return;
    const select = $("grade-select");
    if (select.value === suggested) return;
    select.value = suggested;
    try {
      await syncNetwork({ grade: suggested });
    } catch (err) {
      // 自动建议失败不应打断主操作。
      console.warn(err);
    }
  }

  async function toggleFixed(id, fixed) {
    try {
      setBusy(true);
      const payload = await api(`/api/thesis/points/${encodeURIComponent(id)}`, {
        method: "PATCH",
        body: { fixed },
      });
      applyState(payload);
    } catch (err) {
      toast(err.message, true);
    } finally {
      setBusy(false);
    }
  }

  async function deletePoint(id) {
    try {
      setBusy(true);
      const payload = await api(`/api/thesis/points/${encodeURIComponent(id)}`, { method: "DELETE" });
      applyState(payload);
      toast("已删除点及关联线、角");
    } catch (err) {
      toast(err.message, true);
    } finally {
      setBusy(false);
    }
  }

  async function deleteLine(id) {
    try {
      setBusy(true);
      const payload = await api(`/api/thesis/lines/${encodeURIComponent(id)}`, { method: "DELETE" });
      applyState(payload);
      toast("已删除线");
    } catch (err) {
      toast(err.message, true);
    } finally {
      setBusy(false);
    }
  }

  async function deleteAngle(id) {
    try {
      setBusy(true);
      const payload = await api(`/api/thesis/angles/${encodeURIComponent(id)}`, { method: "DELETE" });
      applyState(payload);
      toast("已删除角");
    } catch (err) {
      toast(err.message, true);
    } finally {
      setBusy(false);
    }
  }

  // ------------------------------------------------------------------
  // 计算与结果
  // ------------------------------------------------------------------
  function hideResult() {
    $("result-box").classList.add("hidden");
    $("calc-error").classList.add("hidden");
  }

  function showCalcError(message) {
    $("result-box").classList.add("hidden");
    const node = $("calc-error");
    node.textContent = message;
    node.classList.remove("hidden");
  }

  function renderResult(result) {
    state.lastResult = result;
    $("calc-error").classList.add("hidden");
    $("result-box").classList.remove("hidden");
    const badge = $("result-badge");
    badge.textContent = result.satisfied ? "满足精度要求" : "不满足精度要求";
    badge.classList.toggle("fail", !result.satisfied);
    $("result-weakest").textContent = `最弱点 ${result.weakest_point}`;
    $("result-qxx").textContent = num(result.qxx, 4);
    $("result-qyy").textContent = num(result.qyy, 4);
    $("result-m").textContent = `${num(result.mp_paper_mm, 2)} mm / ${num(result.mp_cm, 2)} cm`;
    $("result-nobs").textContent = String(result.n_observations);
    let message = result.message || "";
    if (result.comparison) {
      message += `；优化前最弱点 ${result.comparison.base_weakest_point} ` +
        `${num(result.comparison.base_mp_cm, 2)} cm → 优化后 ${num(result.comparison.optimized_mp_cm, 2)} cm`;
    }
    $("result-message").textContent = message;
    $("result-note").textContent =
      `Qxx/Qyy 为论文截图数值口径；严格 mm²：Qxx=${num(result.qxx_mm2, 4)}，` +
      `Qyy=${num(result.qyy_mm2, 4)}，M=${num(result.mp_mm, 2)} mm。` +
      `B 矩阵 ${result.B_shape[0]}×${result.B_shape[1]}，秩 ${result.rank}。`;

    const body = $("denom-body");
    body.innerHTML = (result.edge_denominators || [])
      .map((row) => {
        const denominator = row.denominator === null ? "∞" : num(row.denominator, 1);
        return (
          `<tr>` +
          `<td>${row.number}</td>` +
          `<td class="endpoint">${escapeHtml(row.from)}–${escapeHtml(row.to)}${row.status === "observed" ? " · 观测" : row.status === "added" ? " · 新增" : ""}</td>` +
          `<td class="num">${num(row.length, 4)}</td>` +
          `<td class="num ${row.passes ? "denom-pass" : "denom-fail"}">${denominator}</td>` +
          `<td class="num">${row.passes ? "≥" : "<"} 1/${row.limit}</td>` +
          `</tr>`
        );
      })
      .join("");
    if (result.weakest_edge) {
      const edge = result.weakest_edge;
      const stateText = edge.passes ? "满足" : "不满足";
      $("weakest-edge").textContent =
        `最弱边 ${edge.number}（${edge.from}–${edge.to}）：分母 ${num(edge.denominator, 1)}，` +
        `${stateText} ${result.grade} 限差 1/${edge.limit}。`;
    } else {
      $("weakest-edge").textContent = "";
    }
    drawEllipses();
  }

  async function calculate() {
    try {
      setBusy(true);
      hideResult();
      await syncNetwork();
      const result = await api("/api/thesis/calculate", { method: "POST" });
      renderResult(result);
      toast(result.message || "精度计算完成");
    } catch (err) {
      showCalcError(err.message);
      toast(err.message, true);
    } finally {
      setBusy(false);
    }
  }

  // ------------------------------------------------------------------
  // 导出、工程与算例
  // ------------------------------------------------------------------
  async function openExport(kind) {
    try {
      setBusy(true);
      const payload = await api(
        kind === "coords" ? "/api/thesis/export/coordinates" : "/api/thesis/export/angles"
      );
      $("export-title").textContent = payload.format || "导出文本";
      $("export-text").textContent = payload.text || "";
      $("export-modal").classList.remove("hidden");
    } catch (err) {
      toast(err.message, true);
    } finally {
      setBusy(false);
    }
  }

  async function copyExport() {
    const text = $("export-text").textContent;
    try {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        await navigator.clipboard.writeText(text);
      } else {
        const area = document.createElement("textarea");
        area.value = text;
        document.body.appendChild(area);
        area.select();
        document.execCommand("copy");
        document.body.removeChild(area);
      }
      toast("已复制到剪贴板");
    } catch (err) {
      toast("复制失败，请手动选择文本", true);
    }
  }

  async function refreshProjects(selectName) {
    try {
      const payload = await api("/api/thesis/projects");
      const select = $("project-select");
      const current = selectName || select.value;
      select.innerHTML = '<option value="">已存工程…</option>';
      (payload.projects || []).forEach((item) => {
        const option = document.createElement("option");
        option.value = item.name;
        option.textContent = `${item.name}（${item.n_points} 点 / ${item.n_lines} 线 / ${item.n_angles} 角）`;
        select.appendChild(option);
      });
      if (current) select.value = current;
    } catch (err) {
      toast(err.message, true);
    }
  }

  async function saveProject() {
    const name = ($("project-name").value || "").trim();
    if (!name) {
      toast("请先输入工程名", true);
      return;
    }
    try {
      setBusy(true);
      const payload = await api("/api/thesis/projects/save", {
        method: "POST",
        body: { name },
      });
      state.nameDirty = false;
      $("project-name").value = payload.name;
      applyState(payload.state, { keepResult: Boolean(state.lastResult) });
      if (state.lastResult) drawEllipses();
      await refreshProjects(payload.name);
      toast(`工程已保存到本地 SQLite：${payload.name}`);
    } catch (err) {
      toast(err.message, true);
    } finally {
      setBusy(false);
    }
  }

  async function loadProject() {
    if (state.data.points.length && !window.confirm("读取将覆盖当前工程；请先保存。继续？")) return;
    const name = $("project-select").value;
    if (!name) {
      toast("请选择一个已保存工程", true);
      return;
    }
    try {
      setBusy(true);
      const payload = await api("/api/thesis/projects/load", {
        method: "POST",
        body: { name },
      });
      state.nameDirty = false;
      state.gradeTouched = false;
      applyState(payload, { fit: true });
      toast(`已读取工程：${name}`);
    } catch (err) {
      toast(err.message, true);
    } finally {
      setBusy(false);
    }
  }

  async function loadExample(key) {
    try {
      setBusy(true);
      hideResult();
      state.lastResult = null;
      state.nameDirty = false;
      state.gradeTouched = false;
      const payload = await api(`/api/thesis/examples/${encodeURIComponent(key)}`, {
        method: "POST",
      });
      applyState(payload, { fit: true });
      await refreshProjects();
      toast(`已载入论文算例 ${key}`);
    } catch (err) {
      toast(err.message, true);
    } finally {
      setBusy(false);
    }
  }

  async function newProject() {
    if (state.data.points.length && !window.confirm("新建将清空当前四库；请先保存。继续？")) return;
    try {
      setBusy(true);
      state.lastResult = null;
      state.nameDirty = false;
      state.gradeTouched = false;
      const payload = await api("/api/thesis/new", {
        method: "POST",
        body: { name: "未命名论文工程" },
      });
      applyState(payload, { fit: true });
      toast("已新建空白工程");
    } catch (err) {
      toast(err.message, true);
    } finally {
      setBusy(false);
    }
  }

  // ------------------------------------------------------------------
  // 论文步骤视图
  // ------------------------------------------------------------------
  const STAGES = ["full", "map", "points", "lines", "angles"];

  function applyStage(stage, options) {
    const opts = options || {};
    const next = STAGES.includes(stage) ? stage : "full";
    document.body.dataset.stage = next;
    const select = $("stage-select");
    if (select) select.value = next;
    if (opts.updateUrl !== false) {
      const url = new URL(window.location.href);
      if (next === "full") url.searchParams.delete("stage");
      else url.searchParams.set("stage", next);
      window.history.replaceState(null, "", url.toString());
    }
    if (state.map) {
      window.setTimeout(() => state.map.invalidateSize({ pan: false }), 60);
    }
  }

  function stageFromUrl() {
    try {
      const stage = new URL(window.location.href).searchParams.get("stage");
      return STAGES.includes(stage) ? stage : "full";
    } catch (err) {
      return "full";
    }
  }

  // ------------------------------------------------------------------
  // 事件绑定
  // ------------------------------------------------------------------
  function bindEvents() {
    $("apply-projection").addEventListener("click", async () => {
      try {
        applyState(await api("/api/thesis/projection", {method:"POST", body:{
          central_meridian:Number($("projection-cm").value), zone_width:Number($("projection-width").value),
          convention:$("projection-convention").value, false_easting_m:Number($("projection-fe").value)}}));
        toast("投影已更新；平面坐标已重算");
      } catch (err) { toast(err.message, true); }
    });
    $("export-json").addEventListener("click", () => {
      const blob = new Blob([JSON.stringify(state.data, null, 2)], {type:"application/json"});
      const a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = "thesis-project.json";
      a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 1000);
    });
    $("topology-file").addEventListener("change", async event => {
      const file = event.target.files[0];
      if (!file) return;
      try {
        if (file.size > 4000000) throw new Error("JSON 不得超过 4 MB");
        const body = JSON.parse(await file.text());
        if (!window.confirm("完整 JSON 将覆盖当前工程四库及观测。继续？")) return;
        const payload = await api("/api/thesis/import/json", {method:"POST", body});
        state.nameDirty = false; state.gradeTouched = true;
        applyState(payload, {fit:true});
        toast("JSON 拓扑导入成功");
      } catch (err) { toast("导入失败：" + err.message, true); }
      finally { event.target.value = ""; }
    });
    $("undo-mutation").addEventListener("click", async () => {
      if (!undoStack.length) return toast("没有可撤销的修改");
      restoring = true;
      try {
        const payload = await api("/api/thesis/import/json", {method:"POST", body:undoStack[undoStack.length-1]});
        state.nameDirty = false; state.gradeTouched = true;
        applyState(payload, {fit:true});
        undoStack.pop(); toast("已撤销");
      } catch (err) { toast(err.message, true); }
      finally { restoring = false; }
    });
    $("coordinate-file").addEventListener("change", importCoordinateFile);
    $("project-name").addEventListener("input", () => {
      state.nameDirty = true;
    });
    $("stage-select").addEventListener("change", () => applyStage($("stage-select").value));

    $("point-body").addEventListener("change", (event) => {
      const select = event.target.closest("select[data-action='toggle-fixed']");
      if (!select) return;
      toggleFixed(select.dataset.id, select.value === "known");
    });
    $("point-body").addEventListener("click", (event) => {
      const button = event.target.closest("button[data-action='delete-point']");
      if (button) deletePoint(button.dataset.id);
    });
    $("line-body").addEventListener("click", (event) => {
      const button = event.target.closest("button[data-action='delete-line']");
      if (button) deleteLine(button.dataset.id);
    });
    $("angle-body").addEventListener("click", (event) => {
      const button = event.target.closest("button[data-action='delete-angle']");
      if (button) deleteAngle(button.dataset.id);
    });

    $("add-line").addEventListener("click", addLine);
    $("add-angle").addEventListener("click", addAngle);
    $("calculate").addEventListener("click", calculate);
    $("export-coords").addEventListener("click", () => openExport("coords"));
    $("export-angles").addEventListener("click", () => openExport("angles"));
    $("new-project").addEventListener("click", newProject);
    $("save-project").addEventListener("click", saveProject);
    $("load-project").addEventListener("click", loadProject);
    $("refresh-projects").addEventListener("click", () => refreshProjects());
    document.querySelectorAll(".btn-example").forEach((button) => {
      button.addEventListener("click", () => loadExample(button.dataset.example));
    });

    $("grade-select").addEventListener("change", async () => {
      state.gradeTouched = true;
      try {
        setBusy(true);
        await syncNetwork();
      } catch (err) {
        toast(err.message, true);
      } finally {
        setBusy(false);
      }
    });
    $("tolerance-input").addEventListener("change", async () => {
      try {
        setBusy(true);
        await syncNetwork();
        if (state.lastResult) await calculate();
      } catch (err) {
        toast(err.message, true);
      } finally {
        setBusy(false);
      }
    });
    $("ellipse-scale").addEventListener("change", async () => {
      try {
        setBusy(true);
        await syncNetwork();
        drawEllipses();
      } catch (err) {
        toast(err.message, true);
      } finally {
        setBusy(false);
      }
    });
    $("show-ellipses").addEventListener("change", async () => {
      try {
        setBusy(true);
        await syncNetwork();
        drawEllipses();
      } catch (err) {
        toast(err.message, true);
      } finally {
        setBusy(false);
      }
    });

    // 观测勾选：观测与新增互斥，更新后立即保存到后端并重绘颜色。
    document.querySelectorAll(".check-list").forEach((list) => {
      list.addEventListener("change", async (event) => {
        const input = event.target.closest("input[type='checkbox']");
        if (!input) return;
        const kind = input.dataset.kind || "";
        const id = input.dataset.id;
        let observeList = null;
        let addedList = null;
        if (kind === "observed-edge") {
          observeList = $("observed-edge-list");
          addedList = $("added-edge-list");
        } else if (kind === "added-edge") {
          observeList = $("observed-edge-list");
          addedList = $("added-edge-list");
        } else if (kind === "observed-angle") {
          observeList = $("observed-angle-list");
          addedList = $("added-angle-list");
        } else if (kind === "added-angle") {
          observeList = $("observed-angle-list");
          addedList = $("added-angle-list");
        }
        if (!observeList || !addedList) return;
        // 新增只能从未观测项中选择；勾选观测项时把它从新增列表移除。
        if (input.checked && !kind.startsWith("added")) {
          const other = addedList.querySelector(`input[data-id="${CSS.escape(id)}"]`);
          if (other) other.checked = false;
        }
        try {
          setBusy(true);
          await syncNetwork();
          if (state.lastResult) await calculate();
        } catch (err) {
          toast(err.message, true);
        } finally {
          setBusy(false);
        }
      });
    });

    $("grade-suggestion").addEventListener("click", async (event) => {
      const button = event.target.closest("button[data-action='apply-suggest']");
      if (!button) return;
      const suggested = state.data.summary.suggested_grade;
      if (!suggested) return;
      state.gradeTouched = false;
      $("grade-select").value = suggested;
      try {
        setBusy(true);
        await syncNetwork({ grade: suggested });
        toast(`已采用建议等级：${suggested}`);
      } catch (err) {
        toast(err.message, true);
      } finally {
        setBusy(false);
      }
    });

    $("close-export").addEventListener("click", () => $("export-modal").classList.add("hidden"));
    $("close-export-2").addEventListener("click", () => $("export-modal").classList.add("hidden"));
    $("copy-export").addEventListener("click", copyExport);
    $("export-modal").addEventListener("click", (event) => {
      if (event.target === $("export-modal")) $("export-modal").classList.add("hidden");
    });
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") $("export-modal").classList.add("hidden");
    });
  }

  async function boot() {
    try {
      const [payload, examples] = await Promise.all([
        api("/api/thesis/state"),
        api("/api/thesis/examples").catch(() => ({ examples: [] })),
      ]);
      state.data = payload;
      state.examples = examples.examples || [];
      state.gradeTouched = false;
      if (payload.name) $("project-name").value = payload.name;
      initMap();
      applyState(payload, { fit: false });
      bindEvents();
      applyStage(stageFromUrl(), { updateUrl: false });
      // 只读调试句柄：供本地 Playwright 截图脚本把经纬度换算成像素后点击，
      // 不发起任何网络请求，也不绕过页面的正常交互流程。
      window.ctrlnetThesis = {
        map: state.map,
        state,
        applyStage,
        fitToPoints,
      };
      await refreshProjects();
    } catch (err) {
      const mapNode = $("map");
      if (mapNode) {
        mapNode.innerHTML =
          `<div style="padding:18px;color:#8e2e26;font-size:13px">页面初始化失败：${escapeHtml(err.message)}</div>`;
      }
      toast(err.message, true);
    }
  }

  window.addEventListener("DOMContentLoaded", boot);
})();
