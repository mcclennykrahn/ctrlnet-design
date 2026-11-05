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
    togglesBound: false,
    scenarios: [],
    selectedScenario: null,
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

  function renderTopStats(summary, scenario) {
    const stats = [
      [summary.n_points, "控制点"],
      [summary.n_observations, "设计观测"],
      [fmt(summary.max_mp_mm, 2) + " mm", "最大 mp"],
      [summary.min_r === null || summary.min_r === undefined ? "—" : fmt(summary.min_r, 3), "最小 r_i"],
    ];
    document.getElementById("top-stats").innerHTML = stats
      .map(function (item) {
        return '<div class="stat"><b>' + esc(item[0]) + "</b><span>" + esc(item[1]) + "</span></div>";
      })
      .join("");
    const dem = summary.dem || {};
    const shape = (dem.shape || []).join("×");
    const resolution = dem.resolution_m ? dem.resolution_m[0] : null;
    document.getElementById("project-sub").textContent =
      (summary.name || "CTRLNET") + " · " + (scenario ? scenario.name : "") +
      " · CRS " + (summary.crs || "—") + " · DEM " + shape +
      (resolution === null ? "" : " @ " + fmt(resolution, 0) + " m");
    renderScenarioMeta(summary, scenario);
  }

  function renderScenarioMeta(summary, scenario) {
    const node = document.getElementById("scenario-meta");
    if (!node) return;
    const parent = scenario && scenario.parent_id ? scenario.parent_id : "—";
    const hash = summary.snapshot_hash ? String(summary.snapshot_hash).slice(0, 12) + "…" : "—";
    node.innerHTML =
      "<b>" + esc(summary.scenario_name || (scenario && scenario.name) || "—") + "</b> · v" +
      esc(summary.scenario_version || (scenario && scenario.version) || 1) +
      "<br>观测 " + fmtInt(summary.n_observations) +
      " · 点数 " + fmtInt(summary.n_points) +
      " · 固定 " + fmtInt(summary.n_fixed) +
      "<br>max mp <b>" + fmt(summary.max_mp_mm, 2) + " mm</b> · min r_i " +
      (summary.min_r === null || summary.min_r === undefined ? "—" : fmt(summary.min_r, 3)) +
      "<br>通视 " + fmtInt(summary.n_visible) + " / " + fmtInt(summary.n_pairs) +
      " · 冗余 " + fmtInt(summary.redundancy) +
      '<br><span class="muted-line">父方案 ' + esc(parent) +
      " · 快照 " + esc(hash) + "</span>";
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
    const props = feature.properties || {};
    if (props.kind === "angle") {
      return {
        pane: "obsPane", color: "#2563eb", weight: 1.0,
        opacity: 0.42, dashArray: "2 4",
      };
    }
    if (props.kind === "visibility") {
      return {
        pane: "obsPane",
        color: props.visible ? "#16a34a" : "#dc2626",
        weight: 1.6, opacity: 0.72,
        dashArray: props.visible ? null : "5 5",
      };
    }
    const visible = props.visible;
    return {
      pane: "obsPane",
      color: visible === true ? "#16a34a" : (visible === false ? "#dc2626" : "#0ea5e9"),
      weight: visible === true ? 2.2 : 2.0,
      opacity: 0.92,
      dashArray: visible === false ? "7 5" : null,
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

  function observationStatus(props) {
    if (props.kind === "angle") return { text: "设计角度", tag: "tag-angle" };
    if (props.kind === "visibility") {
      return props.visible
        ? { text: "通视（未作为设计观测）", tag: "tag-ok" }
        : { text: props.status === "marginal" ? "临界" : "遮挡", tag: "tag-bad" };
    }
    if (props.visible === true) return { text: "通视", tag: "tag-ok" };
    if (props.visible === false) return { text: "遮挡", tag: "tag-bad" };
    return { text: "设计观测", tag: "tag-observed" };
  }

  function observationPopup(props) {
    const status = observationStatus(props);
    const title = props.kind === "angle"
      ? "∠" + esc(props.backsight) + "-" + esc(props.station) + "-" + esc(props.foresight)
      : esc(props.from) + " – " + esc(props.to);
    let kv = "";
    if (props.kind === "angle") {
      kv = "<span>观测值</span><span>" + fmt(props.value_deg, 5) + "°</span>" +
        "<span>r_i</span><span>" + fmt(props.r_i, 4) + "</span>" +
        "<span>MDB</span><span>" + fmt(props.mdb, 3) + " " + esc(props.mdb_unit || "") + "</span>";
    } else {
      kv = "<span>平距</span><span>" + fmt(props.distance_m / 1000, 3) + " km</span>" +
        "<span>最小净空</span><span>" + fmt(props.min_clearance_m, 2) + " m</span>" +
        "<span>位置</span><span>" + fmt(props.min_distance_m, 1) + " m 处</span>" +
        (props.obstruction
          ? "<span>遮挡点</span><span>E " + fmt(props.obstruction.E, 1) + ", N " +
            fmt(props.obstruction.N, 1) + ", H " + fmt(props.obstruction.elevation_m, 2) + " m</span>"
          : "<span>剖面</span><span>" + fmtInt(props.samples) + " 个采样点</span>") +
        "<span>r_i / MDB</span><span>" + fmt(props.r_i, 4) + " / " +
        fmt(props.mdb, 3) + " " + esc(props.mdb_unit || "") + "</span>";
    }
    return "<h3>" + title + '<span class="tag ' + status.tag + '">' + status.text + "</span></h3>" +
      '<div class="kv">' + kv + "</div>";
  }

  function observationInspector(props) {
    const status = observationStatus(props);
    const title = props.kind === "angle"
      ? "∠" + esc(props.backsight) + "-" + esc(props.station) + "-" + esc(props.foresight)
      : esc(props.from) + " – " + esc(props.to);
    let body = "";
    if (props.kind === "angle") {
      body = "<dt>观测值</dt><dd>" + fmt(props.value_deg, 5) + "°</dd>" +
        "<dt>测站</dt><dd>" + esc(props.station) + "</dd>" +
        "<dt>r_i</dt><dd>" + fmt(props.r_i, 4) + "</dd>" +
        "<dt>MDB</dt><dd>" + fmt(props.mdb, 3) + " " + esc(props.mdb_unit || "") + "</dd>";
    } else {
      body = "<dt>平距</dt><dd>" + fmt(props.distance_m / 1000, 3) + " km</dd>" +
        "<dt>最小净空</dt><dd>" + fmt(props.min_clearance_m, 2) + " m</dd>" +
        "<dt>最小位置</dt><dd>距起点 " + fmt(props.min_distance_m, 1) + " m</dd>" +
        "<dt>采样 / 无效</dt><dd>" + fmtInt(props.samples) + " / " + fmtInt(props.nodata_count) + "</dd>" +
        "<dt>r_i / MDB</dt><dd>" + fmt(props.r_i, 4) + " / " + fmt(props.mdb, 3) +
        " " + esc(props.mdb_unit || "") + "</dd>" +
        (props.obstruction
          ? "<dt>遮挡点</dt><dd>E " + fmt(props.obstruction.E, 1) + ", N " +
            fmt(props.obstruction.N, 1) + ", H " + fmt(props.obstruction.elevation_m, 2) + " m</dd>"
          : "");
    }
    return "<h3>" + title + '<span class="tag ' + status.tag + '">' + status.text + "</span></h3>" +
      '<dl class="kv">' + body + "</dl>" +
      "<p class=\"muted\">点击剖面按钮或在剖面模式下点击地图两点，查看详细曲线。</p>";
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

  function makeEllipseLayer(geojson) {
    return L.geoJSON(geojson, {
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
  }

  function makeObservationLayer(geojson) {
    return L.geoJSON(geojson, {
      pane: "obsPane", style: styleObservations,
      onEachFeature: function (feature, layer) {
        const props = feature.properties;
        layer.bindPopup(observationPopup(props), { maxWidth: 360 });
        layer.on("click", function () { setInspector(observationInspector(props)); });
      },
    });
  }

  function removeGroup(name) {
    const group = state.groups[name];
    if (group && map.hasLayer(group)) map.removeLayer(group);
  }

  function applyScenarioLayers(layersPayload) {
    const byId = {};
    layersPayload.layers.forEach(function (layer) { byId[layer.id] = layer; });
    removeGroup("observations");
    removeGroup("ellipses");
    removeGroup("points");
    if (byId.observations) {
      state.groups.observations = makeObservationLayer(byId.observations.geojson);
    }
    if (byId.ellipses) {
      state.groups.ellipses = makeEllipseLayer(byId.ellipses.geojson);
    }
    if (byId.points) {
      state.groups.points = makePointLayer(byId.points.geojson);
    }
    const checks = {
      observations: document.getElementById("lyr-observations"),
      ellipses: document.getElementById("lyr-ellipses"),
      points: document.getElementById("lyr-points"),
    };
    Object.keys(checks).forEach(function (key) {
      const input = checks[key];
      if (input && input.checked && state.groups[key]) state.groups[key].addTo(map);
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

    state.groups.scan = L.layerGroup();
    state.groups.gcp = L.layerGroup();

    [state.groups.hillshade, state.groups.contours, state.groups.scan, state.groups.gcp]
      .forEach(function (group) { group.addTo(map); });

    state.tempLayer = L.layerGroup().addTo(map);
    state.profileLayer = L.layerGroup().addTo(map);
    applyScenarioLayers(layersPayload);
    bindLayerToggles();
    getJSON("/api/tiles").then(function (data) {
      const select = document.getElementById("offline-tiles");
      data.resources.forEach(function (resource) {
        const option = document.createElement("option");
        option.value = resource.name; option.textContent = resource.name;
        select.appendChild(option);
      });
      let overlay = null;
      select.addEventListener("change", function () {
        if (overlay) map.removeLayer(overlay);
        if (select.value) {
          overlay = L.imageOverlay("/api/tiles/" + encodeURIComponent(select.value) + "/overlay.png",
            data.bounds, {pane: "hillshadePane", opacity: 0.8}).addTo(map);
        }
      });
    }).catch(function (error) { console.warn("离线瓦片资源读取失败", error); });
  }

  function bindLayerToggles() {
    if (state.togglesBound) return;
    state.togglesBound = true;
    const mapping = {
      "lyr-hillshade": "hillshade",
      "lyr-contours": "contours",
      "lyr-observations": "observations",
      "lyr-ellipses": "ellipses",
      "lyr-points": "points",
      "lyr-scan": "scan",
      "lyr-gcp": "gcp",
    };
    Object.keys(mapping).forEach(function (id) {
      const input = document.getElementById(id);
      input.addEventListener("change", function () {
        const group = state.groups[mapping[id]];
        if (!group) return;
        if (input.checked) group.addTo(map); else map.removeLayer(group);
      });
    });
  }

  function fitScenarioView(points, maxZoom) {
    if (points && points.length) {
      const lats = points.map(function (p) { return p.N; });
      const lngs = points.map(function (p) { return p.E; });
      map.fitBounds([[Math.min.apply(null, lats), Math.min.apply(null, lngs)],
        [Math.max.apply(null, lats), Math.max.apply(null, lngs)]], {
        paddingTopLeft: [330, 120],
        paddingBottomRight: [410, 70],
        maxZoom: maxZoom === undefined ? 6 : maxZoom,
      });
    }
  }

  function fitInitialView(project) {
    const summary = project.summary || {};
    const dem = (summary.dem && summary.dem.bounds_native) || null;
    if (dem) {
      const bounds = [[dem[1], dem[0]], [dem[3], dem[2]]];
      map.setMaxBounds(L.latLngBounds(bounds).pad(0.6));
    }
    fitScenarioView(project.points || [], 6);
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

  function currentScenario() {
    return (state.scenarios || []).filter(function (scenario) {
      return scenario.id === state.selectedScenario;
    })[0] || null;
  }

  function buildScenarioOptions() {
    const select = document.getElementById("scenario-select");
    select.innerHTML = (state.scenarios || []).map(function (scenario) {
      return '<option value="' + esc(scenario.id) + '">' + esc(scenario.name) +
        " · v" + esc(scenario.version) + " · " + esc(scenario.n_observations) + " obs</option>";
    }).join("");
    if (state.selectedScenario) select.value = state.selectedScenario;
  }

  function updateReportLinks() {
    const sid = state.selectedScenario || "";
    const query = "?scenario=" + encodeURIComponent(sid);
    document.getElementById("report-html").href = "/api/report" + query + "&format=html";
    document.getElementById("report-md").href = "/api/report" + query + "&format=md";
    document.getElementById("report-docx").href = "/api/report" + query + "&format=docx";
  }

  async function switchScenario(scenarioId) {
    const select = document.getElementById("scenario-select");
    const previous = state.selectedScenario;
    select.disabled = true;
    document.getElementById("scenario-meta").textContent = "正在切换方案…";
    try {
      const payload = await getJSON("/api/scenario/" + encodeURIComponent(scenarioId));
      const layers = await getJSON("/api/layers?scenario=" + encodeURIComponent(scenarioId));
      state.selectedScenario = scenarioId;
      state.project.selected_scenario = scenarioId;
      state.project.summary = payload.summary;
      state.project.points = payload.points;
      state.project.observations = payload.observations;
      state.project.visibility = payload.visibility;
      state.project.analysis = payload.analysis;
      state.project.network = payload.network;
      state.project.snapshot_hash = payload.snapshot_hash;
      state.layers = layers;
      state.lastPayload = payload;
      renderTopStats(payload.summary, payload.scenario);
      applyScenarioLayers(layers);
      fitScenarioView(payload.points, 6);
      updateReportLinks();
      document.getElementById("status-mode").textContent =
        "方案：" + payload.scenario.name + " · v" + payload.scenario.version;
      setInspectorMuted("已切换方案，点击点/观测/椭圆查看精度、可靠性与通视信息。");
      window.ctrlnetScenarioReady = scenarioId;
      return payload;
    } catch (error) {
      state.selectedScenario = previous;
      if (previous) select.value = previous;
      showError("方案切换失败：" + error.message);
      throw error;
    } finally {
      select.disabled = false;
    }
  }

  function bindButtons() {
    document.getElementById("reload-registration").addEventListener("click", function () {
      document.getElementById("registration-status").textContent = "重新载入示例影像并配准…";
      loadRegistration().catch(function (error) { showError(error.message); });
    });
    document.getElementById("scenario-select").addEventListener("change", function (event) {
      switchScenario(event.target.value).catch(function () { /* 已提示 */ });
    });
  }

  async function boot() {
    try {
      const project = await getJSON("/api/project");
      state.project = project;
      state.scenarios = project.scenarios || [];
      state.selectedScenario = project.selected_scenario;
      buildScenarioOptions();
      renderTopStats(project.summary, currentScenario());
      fitInitialView(project);
      bindMapEvents();
      const layers = await getJSON("/api/layers?scenario=" + encodeURIComponent(state.selectedScenario));
      state.layers = layers;
      addLayerGroups(layers);
      bindButtons();
      updateReportLinks();
      await loadRegistration();
      document.getElementById("loading").classList.add("hidden");
      window.ctrlnetApp = {
        showProfile: showProfile,
        loadRegistration: loadRegistration,
        switchScenario: switchScenario,
        state: state,
        map: map,
      };
      window.ctrlnetBooted = true;
      window.ctrlnetScenarioReady = state.selectedScenario;
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
