/* CTRLNET 本地离线网页地图：Leaflet + 原生 JS，无外部网络请求。 */
(function () {
  "use strict";

  const state = {
    project: null,
    layers: null,
    registration: null,
    groups: {},
    profilePoints: [],
    tempLayer: null,
    profileLayer: null,
    lastProfile: null,
    controlsBound: false,
  };

  const map = L.map("map", {
    crs: L.CRS.Simple,
    minZoom: -5,
    maxZoom: 7,
    zoomControl: false,
    attributionControl: false,
    preferCanvas: false,
  });
  L.control.zoom({ position: "bottomright" }).addTo(map);

  function makePane(name, zIndex) {
    const pane = map.createPane(name);
    pane.style.zIndex = String(zIndex);
    return pane;
  }
  ["hillshadePane", "scanPane", "contourPane", "ellipsePane", "obsPane", "pointPane", "gcpPane", "profilePane"].forEach(
    function (name, index) {
      makePane(name, 210 + index * 10);
    }
  );
  const profilePane = map.getPane("profilePane");
  if (profilePane) profilePane.style.pointerEvents = "none";

  function fmt(value, digits) {
    if (value === null || value === undefined || Number.isNaN(Number(value))) return "—";
    return Number(value).toLocaleString("zh-CN", {
      minimumFractionDigits: digits === undefined ? 2 : digits,
      maximumFractionDigits: digits === undefined ? 2 : digits,
    });
  }
  function fmtInt(value) {
    if (value === null || value === undefined) return "—";
    return Number(value).toLocaleString("zh-CN");
  }
  function esc(text) {
    return String(text === null || text === undefined ? "" : text).replace(/[&<>"']/g, function (ch) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch];
    });
  }
  async function getJSON(url) {
    const response = await fetch(url, { headers: { Accept: "application/json" } });
    if (!response.ok) {
      let detail = response.statusText;
      try {
        const body = await response.json();
        detail = body.detail || detail;
      } catch (err) { /* ignore */ }
      throw new Error(url + " → " + response.status + " " + detail);
    }
    return response.json();
  }

  function showError(message) {
    const banner = document.getElementById("error-banner");
    banner.textContent = message;
    banner.hidden = false;
    window.setTimeout(function () { banner.hidden = true; }, 12000);
  }

  function setInspector(html) {
    const node = document.getElementById("inspector");
    node.classList.remove("muted");
    node.innerHTML = html;
  }

  function setInspectorMuted(text) {
    const node = document.getElementById("inspector");
    node.classList.add("muted");
    node.textContent = text;
  }

  function renderTopStats(summary) {
    const stats = [
      [summary.n_points, "控制点"],
      [summary.n_visible + " / " + summary.n_pairs, "通视点对"],
      [summary.n_observations, "设计观测"],
      [fmt(summary.max_mp_mm, 2) + " mm", "最大 mp"],
    ];
    document.getElementById("top-stats").innerHTML = stats
      .map(function (item) {
        return '<div class="stat"><b>' + esc(item[0]) + "</b><span>" + esc(item[1]) + "</span></div>";
      })
      .join("");
    document.getElementById("project-sub").textContent =
      summary.name + " · CRS " + summary.crs + " · DEM " + summary.dem.shape.join("×") +
      " @ " + fmt(summary.dem.resolution_m[0], 0) + " m";
  }

  function styleContours(feature) {
    const major = feature.properties && feature.properties.index;
    return {
      pane: "contourPane",
      color: major ? "#8a5a22" : "#a97a42",
      weight: major ? 1.1 : 0.55,
      opacity: major ? 0.82 : 0.52,
      interactive: false,
    };
  }

  function styleObservations(feature) {
    const visible = feature.properties.visible;
    return {
      pane: "obsPane",
      color: visible ? "#16a34a" : "#dc2626",
      weight: visible ? 2.2 : 2.0,
      opacity: 0.92,
      dashArray: visible ? null : "7 5",
    };
  }

  function styleEllipses() {
    return {
      pane: "ellipsePane",
      color: "#8b5cf6",
      weight: 1.5,
      opacity: 0.94,
      fillColor: "#a78bfa",
      fillOpacity: 0.09,
      dashArray: "3 3",
    };
  }

  function pointPopup(props) {
    const fixedTag = props.fixed
      ? '<span class="tag tag-fixed">固定</span>'
      : '<span class="tag tag-free">待定</span>';
    const ellipse = props.ellipse_a_mm > 0
      ? "<span>95% 椭圆</span><span>" + fmt(props.ellipse_a_mm, 2) + " × " +
        fmt(props.ellipse_b_mm, 2) + " mm / " + fmt(props.ellipse_azimuth_deg, 1) + "°</span>"
      : "<span>95% 椭圆</span><span>固定点协方差为 0</span>";
    return '<h3>' + esc(props.name) + fixedTag + "</h3>" +
      '<div class="kv">' +
      "<span>E / N</span><span>" + fmt(props.E, 3) + " / " + fmt(props.N, 3) + " m</span>" +
      "<span>高程</span><span>" + fmt(props.elevation_m, 2) + " m</span>" +
      "<span>σE / σN</span><span>" + fmt(props.sigma_E_mm, 2) + " / " + fmt(props.sigma_N_mm, 2) + " mm</span>" +
      "<span>点位 mp</span><span>" + fmt(props.mp_mm, 2) + " mm</span>" +
      ellipse +
      "</div>";
  }

  function pointInspector(props) {
    const fixedTag = props.fixed
      ? '<span class="tag tag-fixed">固定</span>'
      : '<span class="tag tag-free">待定</span>';
    return "<h3>" + esc(props.name) + fixedTag + "</h3>" +
      '<dl class="kv">' +
      "<dt>E / N</dt><dd>" + fmt(props.E, 3) + " / " + fmt(props.N, 3) + " m</dd>" +
      "<dt>经纬度</dt><dd>" + fmt(props.lon, 6) + "°, " + fmt(props.lat, 6) + "°</dd>" +
      "<dt>DEM 高程</dt><dd>" + fmt(props.elevation_m, 2) + " m</dd>" +
      "<dt>σE / σN</dt><dd>" + fmt(props.sigma_E_mm, 2) + " / " + fmt(props.sigma_N_mm, 2) + " mm</dd>" +
      "<dt>点位 mp</dt><dd>" + fmt(props.mp_mm, 2) + " mm</dd>" +
      (props.ellipse_a_mm > 0
        ? "<dt>95% 椭圆</dt><dd>a=" + fmt(props.ellipse_a_mm, 2) + " mm, b=" +
          fmt(props.ellipse_b_mm, 2) + " mm, az=" + fmt(props.ellipse_azimuth_deg, 1) + "°</dd>"
        : "<dt>95% 椭圆</dt><dd>固定点，无误差椭圆</dd>") +
      "</dl>";
  }

  function observationPopup(props) {
    const statusText = props.visible ? "通视" : (props.status === "marginal" ? "临界" : "遮挡");
    const tag = props.visible ? "tag-ok" : "tag-bad";
    return "<h3>" + esc(props.from) + " – " + esc(props.to) +
      '<span class="tag ' + tag + '">' + statusText + "</span></h3>" +
      '<div class="kv">' +
      "<span>平距</span><span>" + fmt(props.distance_m / 1000, 3) + " km</span>" +
      "<span>最小净空</span><span>" + fmt(props.min_clearance_m, 2) + " m</span>" +
      "<span>位置</span><span>" + fmt(props.min_distance_m, 1) + " m 处</span>" +
      (props.obstruction
        ? "<span>遮挡点</span><span>E " + fmt(props.obstruction.E, 1) + ", N " +
          fmt(props.obstruction.N, 1) + ", H " + fmt(props.obstruction.elevation_m, 2) + " m</span>"
        : "<span>剖面</span><span>" + fmtInt(props.samples) + " 个采样点</span>") +
      "</div>";
  }

  function observationInspector(props) {
    const statusText = props.visible ? "通视" : (props.status === "marginal" ? "临界" : "遮挡");
    const tag = props.visible ? "tag-ok" : "tag-bad";
    return "<h3>" + esc(props.from) + " – " + esc(props.to) +
      '<span class="tag ' + tag + '">' + statusText + "</span></h3>" +
      '<dl class="kv">' +
      "<dt>平距</dt><dd>" + fmt(props.distance_m / 1000, 3) + " km</dd>" +
      "<dt>最小净空</dt><dd>" + fmt(props.min_clearance_m, 2) + " m</dd>" +
      "<dt>最小位置</dt><dd>距起点 " + fmt(props.min_distance_m, 1) + " m</dd>" +
      "<dt>采样 / 无效</dt><dd>" + fmtInt(props.samples) + " / " + fmtInt(props.nodata_count) + "</dd>" +
      (props.obstruction
        ? "<dt>遮挡点</dt><dd>E " + fmt(props.obstruction.E, 1) + ", N " + fmt(props.obstruction.N, 1) +
          ", H " + fmt(props.obstruction.elevation_m, 2) + " m</dd>"
        : "") +
      "</dl><p class=\"muted\">点击剖面按钮或在剖面模式下点击地图两点，查看详细曲线。</p>";
  }

  function makePointLayer(geojson) {
    return L.geoJSON(geojson, {
      pane: "pointPane",
      pointToLayer: function (feature, latlng) {
        const fixed = feature.properties.fixed;
        const icon = L.divIcon({
          className: "point-icon",
          html: '<div class="point-marker ' + (fixed ? "fixed" : "unknown") + '"></div>',
          iconSize: [17, 17],
          iconAnchor: [8.5, 8.5],
        });
        const marker = L.marker(latlng, { icon: icon, pane: "pointPane" });
        marker.bindTooltip(feature.properties.name, {
          permanent: true,
          direction: "right",
          offset: [9, 0],
          className: "point-tooltip",
        });
        marker.bindPopup(pointPopup(feature.properties), { maxWidth: 330 });
        marker.on("click", function () {
          setInspector(pointInspector(feature.properties));
        });
        return marker;
      },
    });
  }

  function addLayerGroups(layersPayload) {
    const byId = {};
    layersPayload.layers.forEach(function (layer) { byId[layer.id] = layer; });

    state.groups.hillshade = L.layerGroup();
    const hs = byId.hillshade;
    if (hs) {
      const image = L.imageOverlay(hs.url, hs.bounds, {
        pane: "hillshadePane", opacity: hs.opacity || 0.95, interactive: false,
      });
      state.groups.hillshade.addLayer(image);
    }

    state.groups.contours = L.geoJSON(byId.contours.geojson, {
      pane: "contourPane", style: styleContours, interactive: false,
    });

    state.groups.ellipses = L.geoJSON(byId.ellipses.geojson, {
      pane: "ellipsePane", style: styleEllipses,
      onEachFeature: function (feature, layer) {
        const props = feature.properties;
        layer.bindPopup("<h3>" + esc(props.name) + " · 95% 误差椭圆</h3>" +
          '<div class="kv"><span>半长轴 a</span><span>' + fmt(props.a_mm, 2) + " mm</span>" +
          "<span>半短轴 b</span><span>" + fmt(props.b_mm, 2) + " mm</span>" +
          "<span>方位角</span><span>" + fmt(props.azimuth_deg, 1) + "°</span>" +
          "<span>显示放大</span><span>" + fmtInt(props.scale) + " ×</span></div>");
        layer.on("click", function () {
          setInspector("<h3>" + esc(props.name) + ' · 95% 椭圆</h3><dl class="kv">' +
            "<dt>半长轴 a</dt><dd>" + fmt(props.a_mm, 2) + " mm</dd>" +
            "<dt>半短轴 b</dt><dd>" + fmt(props.b_mm, 2) + " mm</dd>" +
            "<dt>方位角</dt><dd>" + fmt(props.azimuth_deg, 1) + "°</dd>" +
            "<dt>置信度</dt><dd>" + fmt(props.confidence * 100, 1) + "%</dd>" +
            "<dt>图上放大</dt><dd>" + fmtInt(props.scale) + " ×</dd></dl>");
        });
      },
    });

    state.groups.observations = L.geoJSON(byId.observations.geojson, {
      pane: "obsPane", style: styleObservations,
      onEachFeature: function (feature, layer) {
        const props = feature.properties;
        layer.bindPopup(observationPopup(props), { maxWidth: 360 });
        layer.on("click", function () { setInspector(observationInspector(props)); });
      },
    });

    state.groups.points = makePointLayer(byId.points.geojson);
    state.groups.scan = L.layerGroup();
    state.groups.gcp = L.layerGroup();

    [state.groups.hillshade, state.groups.contours, state.groups.ellipses,
      state.groups.observations, state.groups.points, state.groups.scan, state.groups.gcp]
      .forEach(function (group) { group.addTo(map); });

    state.tempLayer = L.layerGroup().addTo(map);
    state.profileLayer = L.layerGroup().addTo(map);

    bindLayerToggles();
  }

  function bindLayerToggles() {
    const mapping = {
      "lyr-hillshade": state.groups.hillshade,
      "lyr-contours": state.groups.contours,
      "lyr-observations": state.groups.observations,
      "lyr-ellipses": state.groups.ellipses,
      "lyr-points": state.groups.points,
      "lyr-scan": state.groups.scan,
      "lyr-gcp": state.groups.gcp,
    };
    Object.keys(mapping).forEach(function (id) {
      const input = document.getElementById(id);
      const group = mapping[id];
      input.addEventListener("change", function () {
        if (input.checked) group.addTo(map); else map.removeLayer(group);
      });
    });
  }

  function fitInitialView(project) {
    const dem = project.summary.dem.bounds_native;
    const bounds = [[dem[1], dem[0]], [dem[3], dem[2]]];
    const points = project.points || [];
    if (points.length) {
      const lats = points.map(function (p) { return p.N; });
      const lngs = points.map(function (p) { return p.E; });
      map.fitBounds([[Math.min.apply(null, lats), Math.min.apply(null, lngs)],
        [Math.max.apply(null, lats), Math.max.apply(null, lngs)]], {
        paddingTopLeft: [330, 120],
        paddingBottomRight: [410, 70],
        maxZoom: 4,
      });
    } else {
      map.fitBounds(bounds, { padding: [20, 20] });
    }
    map.setMaxBounds(L.latLngBounds(bounds).pad(0.6));
    window.setTimeout(function () { map.invalidateSize(); }, 80);
  }

  function bindMapEvents() {
    if (state.controlsBound) return;
    state.controlsBound = true;

    map.on("mousemove", function (event) {
      const E = event.latlng.lng;
      const N = event.latlng.lat;
      document.getElementById("status-coord").textContent =
        "E " + fmt(E, 1) + " / N " + fmt(N, 1) + " m · zoom " + map.getZoom();
    });

    map.on("click", function (event) {
      const E = Number(event.latlng.lng);
      const N = Number(event.latlng.lat);
      state.profilePoints.push([E, N]);
      L.circleMarker([N, E], {
        pane: "profilePane", radius: 5, color: "#fbbf24", weight: 2,
        fillColor: "#f59e0b", fillOpacity: 0.65,
      }).addTo(state.tempLayer);
      if (state.tempLayer.getLayers().length > 1) {
        const pts = state.tempLayer.getLayers().map(function (layer) { return layer.getLatLng(); });
        L.polyline(pts, { pane: "profilePane", color: "#fbbf24", weight: 1.5, dashArray: "4 4" })
          .addTo(state.tempLayer);
      }
      if (state.profilePoints.length === 2) {
        const from = state.profilePoints[0];
        const to = state.profilePoints[1];
        state.tempLayer.clearLayers();
        state.profilePoints = [];
        showProfile(from[0].toFixed(3) + "," + from[1].toFixed(3),
          to[0].toFixed(3) + "," + to[1].toFixed(3));
      }
    });
  }

  function loadRegistration() {
    return getJSON("/api/registration/demo").then(function (data) {
      state.registration = data;
      const status = document.getElementById("registration-status");
      if (state.groups.scan) state.groups.scan.clearLayers();
      if (state.groups.gcp) state.groups.gcp.clearLayers();

      const overlay = L.imageOverlay(data.overlay_url, data.overlay_bounds, {
        pane: "scanPane", opacity: data.opacity || 0.48, interactive: false,
        className: "scan-overlay",
      });
      overlay.on("load", function () { window.ctrlnetReady = true; });
      overlay.on("error", function () {
        window.ctrlnetReady = true;
        status.textContent = "配准叠加影像加载失败，请检查后端日志。";
      });
      state.groups.scan.addLayer(overlay);

      const controls = data.control_points || [];
      controls.forEach(function (point) {
        const icon = L.divIcon({
          className: "gcp-icon",
          html: '<div class="gcp-marker"></div>',
          iconSize: [18, 18], iconAnchor: [9, 9],
        });
        const marker = L.marker([point.N, point.E], { icon: icon, pane: "gcpPane" });
        marker.bindTooltip(point.label + " · Δ " + fmt(point.residual_m, 2) + " m", {
          permanent: true, direction: "top", offset: [0, -10], className: "gcp-tooltip",
        });
        marker.bindPopup("<h3>" + esc(point.label) + " · 配准控制点</h3>" +
          '<div class="kv"><span>像素 col,row</span><span>' + fmt(point.col, 2) + ", " + fmt(point.row, 2) + "</span>" +
          "<span>E / N</span><span>" + fmt(point.E, 3) + " / " + fmt(point.N, 3) + " m</span>" +
          "<span>ΔE / ΔN</span><span>" + fmt(point.residual_E_m, 2) + " / " + fmt(point.residual_N_m, 2) + " m</span>" +
          "<span>残差</span><span>" + fmt(point.residual_m, 2) + " m</span></div>");
        marker.on("click", function () {
          setInspector("<h3>" + esc(point.label) + ' · 配准控制点</h3><dl class="kv">' +
            "<dt>像素坐标</dt><dd>col=" + fmt(point.col, 3) + ", row=" + fmt(point.row, 3) + "</dd>" +
            "<dt>目标 E / N</dt><dd>" + fmt(point.E, 3) + " / " + fmt(point.N, 3) + " m</dd>" +
            "<dt>ΔE / ΔN</dt><dd>" + fmt(point.residual_E_m, 2) + " / " + fmt(point.residual_N_m, 2) + " m</dd>" +
            "<dt>平面残差</dt><dd>" + fmt(point.residual_m, 2) + " m</dd></dl>");
        });
        state.groups.gcp.addLayer(marker);
      });

      (data.check_points || []).forEach(function (point) {
        const marker = L.circleMarker([point.N, point.E], {
          pane: "gcpPane", radius: 6, color: "#f9a8d4", weight: 2,
          dashArray: "3 2", fillColor: "#fce7f3", fillOpacity: 0.4,
        });
        marker.bindTooltip(point.label + " · 检查 " + fmt(point.residual_m, 2) + " m", {
          direction: "bottom", offset: [0, 8], className: "gcp-tooltip",
        });
        state.groups.gcp.addLayer(marker);
      });

      document.getElementById("reg-n").textContent = fmtInt(data.n_control_points) + " 对";
      document.getElementById("reg-rms").textContent = fmt(data.rms_m, 3) + " m";
      document.getElementById("reg-check-n").textContent =
        data.check_points ? fmtInt(data.check_points.length) + " 个" : "—";
      document.getElementById("reg-check-rms").textContent =
        data.check_rms_m === undefined ? "—" : fmt(data.check_rms_m, 3) + " m";
      status.textContent = "已用 4 个控制点求解六参数仿射；RMS " +
        fmt(data.rms_m, 3) + " m，检查点 RMS " + fmt(data.check_rms_m, 3) +
        " m。半透明叠加已启用。";

      const p = data.parameters;
      document.getElementById("registration-detail").classList.remove("muted");
      document.getElementById("registration-detail").innerHTML =
        "<b>模型</b>：E=a0+a1·col+a2·row；N=b0+b1·col+b2·row<br>" +
        '<span class="param">a0=' + fmt(p.a0, 3) + "，a1=" + fmt(p.a1, 5) + "，a2=" + fmt(p.a2, 5) + "</span><br>" +
        '<span class="param">b0=' + fmt(p.b0, 3) + "，b1=" + fmt(p.b1, 5) + "，b2=" + fmt(p.b2, 5) + "</span><br>" +
        "<b>控制点残差</b>：" + (data.control_points || []).map(function (pt) {
          return pt.label + " " + fmt(pt.residual_m, 2) + " m";
        }).join("，") + "<br>" +
        "<b>检查点</b>：" + (data.check_points || []).map(function (pt) {
          return pt.label + " " + fmt(pt.residual_m, 2) + " m";
        }).join("，") +
        "<br><b>影像</b>：" + esc(data.image_name) + " · " + data.overlay_size[0] + "×" + data.overlay_size[1] + " px";

      window.ctrlnetRegistration = data;
      return data;
    }).catch(function (error) {
      document.getElementById("registration-status").textContent = "配准演示载入失败：" + error.message;
      window.ctrlnetReady = true;
      throw error;
    });
  }

  function chartSVG(data) {
    const W = 340, H = 178;
    const pad = { left: 42, right: 9, top: 9, bottom: 24 };
    const profile = data.profile;
    const xs = profile.distance_m;
    const zs = profile.elevation_m;
    const los = profile.los_m;
    const validZ = zs.filter(function (v) { return v !== null && v !== undefined; });
    const validL = los.filter(function (v) { return v !== null && v !== undefined; });
    if (!validZ.length) return '<div class="chart-placeholder">剖面全部落在 DEM 有效范围之外</div>';
    let yMin = Math.min.apply(null, validZ.concat(validL));
    let yMax = Math.max.apply(null, validZ.concat(validL));
    if (!isFinite(yMin) || !isFinite(yMax)) return '<div class="chart-placeholder">剖面无效</div>';
    const span = Math.max(yMax - yMin, 8);
    yMin -= span * 0.12;
    yMax += span * 0.12;
    const xMax = Math.max(xs[xs.length - 1], 1);
    const sx = function (x) { return pad.left + (x / xMax) * (W - pad.left - pad.right); };
    const sy = function (y) { return pad.top + (1 - (y - yMin) / (yMax - yMin)) * (H - pad.top - pad.bottom); };

    function pathFor(values, closeToBottom) {
      let path = "";
      values.forEach(function (value, index) {
        if (value === null || value === undefined) return;
        path += (path === "" ? "M" : "L") + sx(xs[index]).toFixed(2) + " " + sy(value).toFixed(2) + " ";
      });
      if (closeToBottom && path !== "") {
        path += "L" + sx(xMax).toFixed(2) + " " + sy(yMin).toFixed(2) + " " +
          "L" + sx(0).toFixed(2) + " " + sy(yMin).toFixed(2) + " Z";
      }
      return path;
    }

    const terrainPath = pathFor(zs, true);
    const losPath = pathFor(los, false);
    let grid = "";
    for (let i = 0; i <= 4; i += 1) {
      const y = yMin + ((yMax - yMin) * i) / 4;
      const py = sy(y);
      grid += '<line x1="' + pad.left + '" y1="' + py.toFixed(1) + '" x2="' + (W - pad.right) +
        '" y2="' + py.toFixed(1) + '" stroke="#334155" stroke-width="0.6" opacity="0.75"/>';
      grid += '<text x="' + (pad.left - 5) + '" y="' + (py + 3).toFixed(1) +
        '" text-anchor="end" fill="#7c8da6" font-size="8">' + Math.round(y) + "</text>";
    }
    const xTicks = [0, 0.5, 1];
    let xLabels = "";
    xTicks.forEach(function (fraction) {
      const x = xMax * fraction;
      const px = sx(x);
      xLabels += '<text x="' + px.toFixed(1) + '" y="' + (H - 7) +
        '" text-anchor="middle" fill="#7c8da6" font-size="8">' +
        (x / 1000).toFixed(1) + " km</text>";
      xLabels += '<line x1="' + px.toFixed(1) + '" y1="' + pad.top + '" x2="' + px.toFixed(1) +
        '" y2="' + (H - pad.bottom) + '" stroke="#334155" stroke-width="0.6" opacity="0.55"/>';
    });

    let obstruction = "";
    if (data.obstruction) {
      const ox = sx(data.obstruction.distance_m);
      const oy = sy(data.obstruction.elevation_m);
      obstruction = '<line x1="' + ox.toFixed(1) + '" y1="' + pad.top + '" x2="' + ox.toFixed(1) +
        '" y2="' + (H - pad.bottom) + '" stroke="#ef4444" stroke-width="0.9" stroke-dasharray="3 3"/>' +
        '<circle cx="' + ox.toFixed(1) + '" cy="' + oy.toFixed(1) + '" r="4.2" fill="#ef4444" stroke="#fff" stroke-width="1"/>';
    }
    const color = data.visible ? "#22c55e" : "#ef4444";
    return '<svg viewBox="0 0 ' + W + " " + H + '" role="img" aria-label="DEM 剖面图">' +
      '<rect x="0" y="0" width="' + W + '" height="' + H + '" rx="9" fill="#07111f" stroke="#273449"/>' +
      grid + xLabels +
      '<path d="' + terrainPath + '" fill="#8a6a3c" fill-opacity="0.32" stroke="#d6b47a" stroke-width="1.15"/>' +
      '<path d="' + losPath + '" fill="none" stroke="' + color + '" stroke-width="1.8"/>' +
      obstruction +
      '<g font-size="8.5" fill="#94a3b8">' +
      '<rect x="' + (pad.left + 4) + '" y="' + (pad.top + 3) + '" width="104" height="30" rx="4" fill="#0f172a" opacity="0.86"/>' +
      '<line x1="' + (pad.left + 10) + '" y1="' + (pad.top + 12) + '" x2="' + (pad.left + 28) + '" y2="' + (pad.top + 12) + '" stroke="#d6b47a" stroke-width="1.2"/>' +
      '<text x="' + (pad.left + 34) + '" y="' + (pad.top + 15) + '">地形 / 遮挡</text>' +
      '<line x1="' + (pad.left + 10) + '" y1="' + (pad.top + 25) + '" x2="' + (pad.left + 28) + '" y2="' + (pad.top + 25) + '" stroke="' + color + '" stroke-width="1.8"/>' +
      '<text x="' + (pad.left + 34) + '" y="' + (pad.top + 28) + '">曲率折光视线</text></g>' +
      "</svg>";
  }

  function renderProfileSummary(data) {
    const statusMap = { visible: "通视", blocked: "遮挡", marginal: "临界", unknown: "不确定" };
    const status = data.status;
    const klass = data.visible ? "ok" : "bad";
    const from = data.from.label || "起点";
    const to = data.to.label || "终点";
    let html = "<strong>" + esc(from) + " → " + esc(to) + "</strong> · " +
      fmt(data.distance_m / 1000, 3) + " km · <span class=\"" + klass + "\">" +
      esc(statusMap[status] || status) + "</span> · 最小净空 " +
      fmt(data.min_clearance_m, 2) + " m";
    if (data.obstruction) {
      html += " · 遮挡点距起点 " + fmt(data.obstruction.distance_m, 1) + " m";
    }
    html += '<div class="chart-note">k=' + fmt(data.analysis.k, 2) +
      "，R=" + fmtInt(data.analysis.R_m) + " m，仪器高/目标高 " +
      fmt(data.analysis.instrument_height_m, 1) + " / " + fmt(data.analysis.target_height_m, 1) +
      " m，采样 " + fmtInt(data.samples) + " 点</div>";
    document.getElementById("profile-summary").innerHTML = html;
  }

  function showProfile(from, to) {
    const mode = document.getElementById("profile-mode");
    mode.textContent = "计算中…";
    return getJSON("/api/profile?from=" + encodeURIComponent(from) + "&to=" + encodeURIComponent(to))
      .then(function (data) {
        state.lastProfile = data;
        if (state.profileLayer) state.profileLayer.clearLayers();
        const lineColor = data.visible ? "#22c55e" : "#ef4444";
        L.polyline([[data.from.N, data.from.E], [data.to.N, data.to.E]], {
          pane: "profilePane", color: lineColor, weight: 3.2, opacity: 0.95, dashArray: "8 5",
        }).addTo(state.profileLayer);
        [[data.from, "起点"], [data.to, "终点"]].forEach(function (item) {
          L.circleMarker([item[0].N, item[0].E], {
            pane: "profilePane", radius: 6, color: "#fbbf24", weight: 2,
            fillColor: "#fef3c7", fillOpacity: 0.85,
          }).bindTooltip(item[1] + " " + item[0].label, { className: "gcp-tooltip" })
            .addTo(state.profileLayer);
        });
        document.getElementById("profile-chart").innerHTML = chartSVG(data);
        renderProfileSummary(data);
        mode.textContent = "已绘制";
        document.getElementById("status-mode").textContent =
          "剖面 " + (data.from.label || "起点") + " → " + (data.to.label || "终点") +
          " · " + (data.visible ? "通视" : "遮挡");
        window.lastProfile = data;
        return data;
      })
      .catch(function (error) {
        mode.textContent = "失败";
        document.getElementById("profile-summary").textContent = "剖面请求失败：" + error.message;
        showError("剖面请求失败：" + error.message);
        throw error;
      });
  }

  function bindButtons() {
    document.getElementById("reload-registration").addEventListener("click", function () {
      document.getElementById("registration-status").textContent = "重新载入示例影像并配准…";
      loadRegistration().catch(function (error) { showError(error.message); });
    });
  }

  async function boot() {
    try {
      const project = await getJSON("/api/project");
      state.project = project;
      renderTopStats(project.summary);
      fitInitialView(project);
      bindMapEvents();
      const layers = await getJSON("/api/layers");
      state.layers = layers;
      addLayerGroups(layers);
      bindButtons();
      await loadRegistration();
      document.getElementById("loading").classList.add("hidden");
      window.ctrlnetApp = {
        showProfile: showProfile,
        loadRegistration: loadRegistration,
        state: state,
        map: map,
      };
      window.ctrlnetBooted = true;
      if (!window.ctrlnetReady) {
        window.setTimeout(function () { window.ctrlnetReady = true; }, 900);
      }
    } catch (error) {
      document.getElementById("loading").classList.add("hidden");
      showError("页面初始化失败：" + error.message);
      console.error(error);
      window.ctrlnetBooted = true;
      window.ctrlnetReady = true;
    }
  }

  boot();
})();
