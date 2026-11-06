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
    <button id="engineering-rename">重命名所选方案</button>
    <pre id="engineering-tree" aria-label="方案谱系" style="white-space:pre-wrap"></pre>
    <p>三方合并：当前方案为目标，比较对象为来源；保存为新方案，保留双亲。拓扑整体与GNSS分别合并，不自动拼接几何。冲突须选择目标或来源。</p>
    <button id="engineering-merge-preview">预览合并</button><span id="engineering-conflicts"></span>
    <button id="engineering-merge" disabled>保存合并新方案</button>
    <details><summary>GNSS 二维基线参数（随保存/派生持久化）</summary>
    <p>端点使用点号；σ单位米，ρ在(-1,1)。这是二维设计态协方差，不是ECEF/ENU三维导入。打开方案会回读；保存新方案时使用此表。此表草稿保留在当前标签页，刷新不丢失；新工程保存前请检查端点并删除不需要的基线。</p>
    <table><thead><tr><th>起点</th><th>终点</th><th>σE m</th><th>σN m</th><th>ρ</th><th>操作</th></tr></thead><tbody id="engineering-gnss"></tbody></table>
    <button id="engineering-add-gnss">添加基线</button></details>
    <p>联合平差（已选距离 + 角度；GNSS 使用工程平面 E/N 米制分量，二维基线可在下方编辑）
    <label>基准 <select id="engineering-datum"><option value="fixed">固定（默认）</option><option value="free">自由网约束</option><option value="minimal">最小约束</option></select></label>
    <label>椭圆 <select id="engineering-confidence"><option value="0.95">95%置信度</option><option value="0.99">99%置信度</option><option value="false">标准椭圆</option></select></label>
    <button id="engineering-calculate">计算所选存储方案</button></p>
    <details id="engineering-estimation"><summary>实测值与稳健估计（固定基准）</summary>
    <p>载入的是当前存储方案的坐标推算参考值，不能当作实测成果。按模板顺序替换全部观测；距离/GNSS为米，角度为弧度。GNSS分量顺序E/N。输入与估计结果仅在当前页面，需自行复制保存。</p>
    <button id="engineering-template">载入所选方案观测模板</button>
    <pre id="engineering-observation-labels" style="max-height:100px;overflow:auto"></pre>
    <textarea id="engineering-values" aria-label="观测值数组" rows="5" style="width:95%" placeholder="载入模板后输入二维数值数组"></textarea>
    <label>方法 <select id="engineering-method"><option value="ls">普通最小二乘</option><option value="huber" selected>Huber</option><option value="igg3">IGG-III</option></select></label>
    <label>Huber c <input id="engineering-c" type="number" value="1.345" step="0.1" style="width:70px"></label>
    <label>IGG k0 <input id="engineering-k0" type="number" value="1.5" step="0.1" style="width:65px"></label>
    <label>k1 <input id="engineering-k1" type="number" value="3" step="0.1" style="width:65px"></label>
    <label>迭代上限 <input id="engineering-max-iter" type="number" value="50" min="1" max="100" style="width:65px"></label>
    <button id="engineering-estimate">运行实测估计</button></details>
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
    else if (value?.source === 'user_entered_values') summary = `实测值估计 · ${value.method} · ${value.converged ? '已收敛' : '未收敛：不得采用为最终成果'} · 迭代 ${value.iterations}\n秩 ${value.rank} · 冗余 ${value.redundancy}\n最小行权 ${Math.min(...value.weights).toFixed(6)}\n残差/行单位/权/坐标见详细JSON；基准 fixed；方案哈希 ${value.input_hash}`;
    else if (value?.network) summary = `基准 ${value.datum.kind} · 置信度 ${value.options.confidence === false ? '标准椭圆' : value.options.confidence}\n秩 ${value.network.rank} / 参数 ${value.network.n_params} · 冗余 ${value.network.redundancy} · 观测 ${value.network.n_observations}\n最大点位中误差 ${value.summary.max_mp_mm.toFixed(3)} mm\n` + value.points.map(p => `${p.name}: σE ${p.sigma_E_mm.toFixed(3)} mm / σN ${p.sigma_N_mm.toFixed(3)} mm / 椭圆长轴 ${(p.ellipse.a_m*1000).toFixed(3)} mm`).join('\n');
    else if (value?.snapshot_id) summary = `已保存 · 版本 ${value.version}\n工程 ${value.project_id}\n方案 ${value.scenario_id}\n快照 ${value.snapshot_id}`;
    $('summary').textContent = typeof summary === 'string' ? summary : JSON.stringify(summary);
  };
  function addGnss(row = {from:'8',to:'1',sigma_E:0.005,sigma_N:0.005,correlation:0}) {
    const tr = document.createElement('tr');
    for (const key of ['from','to','sigma_E','sigma_N','correlation']) {
      const td = document.createElement('td'), input = document.createElement('input');
      input.dataset.key = key; input.setAttribute('aria-label', key); input.value = row[key];
      input.style.width = '75px'; td.append(input); tr.append(td);
    }
    const td = document.createElement('td'), button = document.createElement('button');
    button.textContent = '删除'; button.onclick = () => { tr.remove(); persistGnss(); }; td.append(button); tr.append(td); $('gnss').append(tr);
    tr.oninput = persistGnss;
  }
  function gnssRows() {
    if ([...$('gnss').querySelectorAll('input')].some(i => !i.value.trim())) throw new Error('GNSS 参数不可留空');
    return [...$('gnss').rows].map(tr => Object.fromEntries([...tr.querySelectorAll('input')].map(i => [i.dataset.key, ['from','to'].includes(i.dataset.key) ? i.value : Number(i.value)])));
  }
  function persistGnss() {
    const rows = [...$('gnss').rows].map(tr => Object.fromEntries([...tr.querySelectorAll('input')].map(i => [i.dataset.key,i.value])));
    sessionStorage.setItem('ctrlnet-open-gnss', JSON.stringify(rows));
  }
  $('add-gnss').onclick = () => { addGnss(); persistGnss(); };
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
    renderTree(p?.scenarios || []);
    invalidateMerge();
  }
  let mergePlan = null;
  function invalidateMerge() {
    mergePlan = null;
    $('merge').disabled = true;
    $('conflicts').replaceChildren();
  }
  function renderTree(rows) {
    const lines = [], visited = new Set();
    function visit(s, depth) {
      if (visited.has(s.id)) return;
      visited.add(s.id);
      lines.push('  '.repeat(depth) + '└ ' + s.name + ' · v' + s.version + ' [' + s.id + ']' +
        (s.merge_parents.length ? ' ← 合并 ' + s.merge_parents.join(' + ') + ' · 祖先 ' + s.merge_base : ''));
      rows.filter(c => c.parent_id === s.id).forEach(c => visit(c, depth+1));
    }
    rows.filter(s => !s.parent_id || !rows.some(p => p.id === s.parent_id)).forEach(s => visit(s, 0));
    rows.forEach(s => visit(s, 0));
    $('tree').textContent = lines.join('\n');
  }
  async function refresh(selection) {
    const old = $('project').value, sid = $('scenario').value;
    projects = (await api('projects')).projects;
    options($('project'), projects.map(p => [p.id,p.name]), selection?.project_id || old);
    scenarios(selection?.scenario_id || sid);
  }
  const run = fn => async () => { try { await fn(); } catch (e) { output(e.message); } };
  $('project').onchange = () => scenarios();
  $('scenario').onchange = () => { snapshots(); invalidateMerge(); };
  $('candidate').onchange = invalidateMerge;
  $('refresh').onclick = run(() => refresh());
  async function save(branch) {
    if (!window.ctrlnetThesis || window.ctrlnetThesis.state.busy) throw new Error("编辑器尚未就绪，请稍后保存");
    await window.ctrlnetThesis.syncNetwork();
    const data = {name:$('name').value, gnss:gnssRows()};
    if (branch) {
      data.project_id = $('project').value; data.parent_snapshot = $('snapshot').value;
      if (!data.parent_snapshot) throw new Error('请先选择父快照');
    }
    const result = await api('save', data);
    await refresh(result); output(result);
  }
  $('save').onclick = run(() => save(false));
  $('branch').onclick = run(() => save(true));
  $('rename').onclick = run(async () => {
    const p = projects.find(p => p.id === $('project').value);
    const s = p?.scenarios.find(s => s.id === $('scenario').value);
    if (!s) throw new Error('请选择方案');
    const result = await api('rename/' + encodeURIComponent(s.id), {name:$('name').value, version:s.version});
    await refresh(); output(result);
  });
  $('merge-preview').onclick = run(async () => {
    invalidateMerge();
    const target = $('scenario').value, source = $('candidate').value;
    const plan = await api('merge/preview?target=' + encodeURIComponent(target) + '&source=' + encodeURIComponent(source));
    if (target !== $('scenario').value || source !== $('candidate').value) return;
    mergePlan = plan;
    for (const key of plan.conflicts) {
      const label = document.createElement('label'); label.textContent = key + ' 冲突 ';
      const select = document.createElement('select'); select.dataset.unit = key;
      options(select, [['','请选择'],['target','保留目标'],['source','采用来源']]);
      label.append(select); $('conflicts').append(label);
    }
    $('merge').disabled = false; output(plan);
  });
  $('merge').onclick = run(async () => {
    if (!mergePlan) throw new Error('请先预览');
    const resolutions = Object.fromEntries([...$('conflicts').querySelectorAll('select')].map(s => [s.dataset.unit,s.value]));
    const result = await api('merge', {...mergePlan, name:$('name').value, resolutions});
    await refresh(result); output(result);
  });
  $('open').onclick = run(async () => {
    if (!confirm('用所选存储方案覆盖论文编辑器当前四库？')) return;
    const settings = await api('settings/' + encodeURIComponent($('scenario').value));
    sessionStorage.setItem('ctrlnet-open-gnss', JSON.stringify(settings.gnss));
    sessionStorage.setItem('ctrlnet-open-selection', JSON.stringify({project_id:$('project').value,scenario_id:$('scenario').value}));
    await api('open/' + encodeURIComponent($('scenario').value), {});
    location.href = '/thesis';
  });
  $('calculate').onclick = run(async () => output(await api('calculate/' + encodeURIComponent($('scenario').value), {datum:$('datum').value, confidence:JSON.parse($('confidence').value)})));
  let template = null;
  $('template').onclick = run(async () => {
    template = null;
    const sid = $('scenario').value;
    const loaded = await api('observations/' + encodeURIComponent(sid));
    if (sid !== $('scenario').value) throw new Error('方案已改变，请重新载入模板');
    template = {...loaded, sid};
    $('values').value = JSON.stringify(template.observations.map(o => o.values));
    $('observation-labels').textContent = '坐标推算参考值（非实测）：\n' + template.observations.map(o => `${o.index}: ${o.label} [${o.unit}]`).join('\n');
  });
  $('estimate').onclick = run(async () => {
    if (!template || template.sid !== $('scenario').value) throw new Error('请为当前方案重新载入观测模板');
    const data = {input_hash:template.input_hash, values:JSON.parse($('values').value), method:$('method').value};
    for (const key of ['c','k0','k1','max-iter']) {
      if (!$(key).value.trim()) throw new Error('稳健参数不可留空');
      data[key.replace('-','_')] = Number($(key).value);
    }
    output(await api('estimate/' + encodeURIComponent(template.sid), data));
  });
  $('compare').onclick = run(async () => output(await api('compare?base=' + encodeURIComponent($('scenario').value) + '&candidate=' + encodeURIComponent($('candidate').value))));
  const opened = sessionStorage.getItem('ctrlnet-open-gnss');
  if (thesis && opened) { JSON.parse(opened).forEach(addGnss); }
  const selection = sessionStorage.getItem('ctrlnet-open-selection');
  sessionStorage.removeItem('ctrlnet-open-selection');
  run(() => refresh(thesis && selection ? JSON.parse(selection) : undefined))();
})();
