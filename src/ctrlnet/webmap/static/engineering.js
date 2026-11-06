/* 共享工程桥接；选择仅保留在当前页面，不改变服务端地图工程。 */
(() => {
  const panel = document.createElement('details');
  panel.open = location.pathname === '/thesis';
  panel.id = 'engineering-panel';
  panel.style.cssText = 'background:#eef4f1;color:#163b34;padding:12px;margin:8px;position:relative;z-index:1000;font:14px sans-serif;max-height:460px;overflow:auto';
  panel.innerHTML = `<summary>工程… · 共享 SQLite 方案与快照</summary>
    <p>论文当前四库 → 命名新工程 / 从所选快照另存分支。仪表盘在此选择、计算及比较；底图仍显示演示工程。旧“保存/读取”为兼容 JSON 存档。</p>
    <input id="engineering-name" aria-label="工程或分支名称" placeholder="工程 / 分支名称">
    <button id="engineering-save">保存为命名新工程</button><button id="engineering-refresh">刷新工程</button>
    <select id="engineering-project" aria-label="共享工程"></select>
    <select id="engineering-scenario" aria-label="共享方案"></select>
    <select id="engineering-snapshot" aria-label="父快照"></select>
    <button id="engineering-branch">当前四库另存分支快照</button><button id="engineering-open">打开工程方案到论文编辑器</button>
    <p>联合平差（已选距离 + 角度；已有工程的 GNSS 观测由核心处理，无基线导入编辑器）
    <label>基准 <select id="engineering-datum"><option value="fixed">固定（默认）</option><option value="free">自由网约束</option><option value="minimal">最小约束</option></select></label>
    <label>椭圆 <select id="engineering-confidence"><option value="0.95">95%置信度</option><option value="0.99">99%置信度</option><option value="false">标准椭圆</option></select></label>
    <button id="engineering-calculate">计算所选存储方案</button></p>
    <label>比较对象 <select id="engineering-candidate"></select></label><button id="engineering-compare">比较方案</button>
    <pre id="engineering-summary" role="status" style="white-space:pre-wrap;max-height:230px;overflow:auto"></pre><details><summary>详细结果 JSON</summary><pre id="engineering-result" style="white-space:pre-wrap;max-height:180px;overflow:auto"></pre></details>`;
  document.body.prepend(panel);
  if (location.pathname !== '/thesis') {
    panel.style.cssText += ';position:fixed;top:76px;left:320px;right:408px;z-index:2500;max-height:70vh;box-shadow:0 6px 24px #0008';
  }
  const $ = id => document.getElementById('engineering-' + id);
  const thesis = location.pathname === '/thesis';
  $('save').disabled = $('branch').disabled = !thesis;
  let projects = [];
  const output = value => {
    $('result').textContent = typeof value === 'string' ? value : JSON.stringify(value, null, 2);
    let summary = value;
    if (value?.summary && typeof value.summary === 'string') summary = `基准哈希 ${value.base_hash}\n候选哈希 ${value.candidate_hash}\n${value.summary}`;
    else if (value?.network) summary = `基准 ${value.datum.kind} · 置信度 ${value.options.confidence === false ? '标准椭圆' : value.options.confidence}\n秩 ${value.network.rank} / 参数 ${value.network.n_params} · 冗余 ${value.network.redundancy} · 观测 ${value.network.n_observations}\n最大点位中误差 ${value.summary.max_mp_mm.toFixed(3)} mm\n` + value.points.map(p => `${p.name}: σE ${p.sigma_E_mm.toFixed(3)} mm / σN ${p.sigma_N_mm.toFixed(3)} mm / 椭圆长轴 ${(p.ellipse.a_m*1000).toFixed(3)} mm`).join('\n');
    else if (value?.snapshot_id) summary = `已保存 · 版本 ${value.version}\n工程 ${value.project_id}\n方案 ${value.scenario_id}\n快照 ${value.snapshot_id}`;
    $('summary').textContent = typeof summary === 'string' ? summary : JSON.stringify(summary);
  };
  async function api(path, data) {
    const response = await fetch('/api/engineering/' + path, data === undefined ? {} : {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(data)});
    const value = await response.json();
    if (!response.ok) throw new Error(value.detail || '请求失败');
    return value;
  }
  function options(node, rows, selected) {
    node.replaceChildren(...rows.map(([value, label]) => { const o = document.createElement('option'); o.value=value; o.textContent=label; return o; }));
    if (rows.some(r => r[0] === selected)) node.value=selected;
  }
  function snapshots() {
    const p = projects.find(p => p.id === $('project').value);
    const s = p?.scenarios.find(s => s.id === $('scenario').value);
    options($('snapshot'), (s?.snapshots || []).map(s => [s.id,s.id]));
  }
  function scenarios(selected) {
    const p = projects.find(p => p.id === $('project').value);
    const rows = (p?.scenarios || []).map(s => [s.id,`${s.name} · v${s.version} · 父 ${s.parent_id || '无'}`]);
    options($('scenario'), rows, selected);
    options($('candidate'), rows);
    snapshots();
  }
  async function refresh(selection) {
    const old = $('project').value, sid = $('scenario').value;
    projects = (await api('projects')).projects;
    options($('project'), projects.map(p => [p.id,p.name]), selection?.project_id || old);
    scenarios(selection?.scenario_id || sid);
  }
  const run = fn => async () => { try { await fn(); } catch (e) { output(e.message); } };
  $('project').onchange = () => scenarios();
  $('scenario').onchange = snapshots;
  $('refresh').onclick = run(() => refresh());
  async function save(branch) {
    if (!window.ctrlnetThesis || window.ctrlnetThesis.state.busy) throw new Error("编辑器尚未就绪，请稍后保存");
    await window.ctrlnetThesis.syncNetwork();
    const data = {name:$('name').value};
    if (branch) {
      data.project_id = $('project').value; data.parent_snapshot = $('snapshot').value;
      if (!data.parent_snapshot) throw new Error('请先选择父快照');
    }
    const result = await api('save', data);
    await refresh(result); output(result);
  }
  $('save').onclick = run(() => save(false));
  $('branch').onclick = run(() => save(true));
  $('open').onclick = run(async () => {
    if (!confirm('用所选存储方案覆盖论文编辑器当前四库？')) return;
    await api('open/' + encodeURIComponent($('scenario').value), {});
    location.href = '/thesis';
  });
  $('calculate').onclick = run(async () => output(await api('calculate/' + encodeURIComponent($('scenario').value), {datum:$('datum').value, confidence:JSON.parse($('confidence').value)})));
  $('compare').onclick = run(async () => output(await api('compare?base=' + encodeURIComponent($('scenario').value) + '&candidate=' + encodeURIComponent($('candidate').value))));
  run(() => refresh())();
})();
