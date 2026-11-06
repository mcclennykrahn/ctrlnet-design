"""第四批共享工程 + 参数，真实 Chromium；进程独立 SQLite。"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from playwright.sync_api import sync_playwright
from test_thesis_e2e import _free_port, _wait_server

ROOT = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='ctrlnet-fourth-') as temp:
    db = Path(temp)/'demo.sqlite'
    shutil.copy2(ROOT/'data/sample/demo_project.sqlite', db)
    for resource in (ROOT/'data/sample').iterdir():
        if resource.suffix not in ('.sqlite', '.db'):
            (Path(temp)/resource.name).symlink_to(resource)
    env = dict(os.environ, CTRLNET_DB=str(db), CTRLNET_THESIS_DB=str(Path(temp)/'engineering.sqlite'))
    port = _free_port()
    base = f'http://127.0.0.1:{port}'
    proc = subprocess.Popen([sys.executable,'-m','uvicorn','ctrlnet.webmap.app:app','--host','127.0.0.1','--port',str(port),'--log-level','error'],cwd=ROOT,env=env)
    try:
        _wait_server(base+'/api/health')
        with sync_playwright() as p:
            browser = p.chromium.launch(args=['--no-sandbox'])
            page = browser.new_page(viewport={'width':1600,'height':1200})
            errors=[]
            page.on('pageerror',lambda e:errors.append(str(e)))
            page.on('dialog',lambda d:d.accept())
            page.goto(base+'/thesis',wait_until='networkidle')
            page.click('[data-example="1"]')
            page.wait_for_function('window.ctrlnetThesis.state.data.points.length === 9')
            page.locator('#observed-edge-list input').first.check()
            page.wait_for_function('window.ctrlnetThesis.state.data.network.observed_edges.length === 1 && !window.ctrlnetThesis.state.busy')
            original=page.request.get(base+'/api/thesis/state').json()
            page.fill('#engineering-name','第四批共享工程')
            page.click('#engineering-save')
            page.wait_for_function('document.querySelector("#engineering-result").textContent.includes("snapshot_id")')
            a=json.loads(page.text_content('#engineering-result'))
            page.get_by_text('GNSS 二维基线参数（随保存/派生持久化）', exact=True).click()
            page.click('#engineering-add-gnss')
            page.fill('#engineering-gnss input[data-key="sigma_N"]','0.007')
            page.fill('#engineering-gnss input[data-key="correlation"]','0.3')
            page.fill('#engineering-gnss input[data-key="correlation"]',' ')
            page.fill('#engineering-name','空白参数不落库')
            page.click('#engineering-branch')
            page.wait_for_function('document.querySelector("#engineering-summary").textContent.includes("不可留空")')
            assert len(page.request.get(base+'/api/engineering/projects').json()['projects'][0]['scenarios']) == 1
            page.fill('#engineering-gnss input[data-key="correlation"]','0.3')
            page.fill('#engineering-name','分支方案')
            page.click('#engineering-branch')
            page.wait_for_function('document.querySelector("#engineering-result").textContent.includes(\'"version": 2\')')
            b=json.loads(page.text_content('#engineering-result'))
            page.select_option('#engineering-scenario',a['scenario_id'])
            with page.expect_navigation(wait_until='networkidle'):
                page.click('#engineering-open')
            loaded=page.request.get(base+'/api/thesis/state').json()
            for key in ('points','lines','angles','network','projection'):
                assert loaded[key] == original[key], (key, loaded[key], original[key])
            page.select_option('#engineering-project',a['project_id'])
            page.select_option('#engineering-scenario',a['scenario_id'])
            page.click('#engineering-calculate')
            page.wait_for_function('document.querySelector("#engineering-result").textContent.includes("sigma_E_mm")')
            low=json.loads(page.text_content('#engineering-result'))
            page.select_option('#engineering-confidence','0.99')
            page.click('#engineering-calculate')
            page.wait_for_function('document.querySelector("#engineering-result").textContent.includes(\'"confidence": 0.99\')')
            high=json.loads(page.text_content('#engineering-result'))
            assert low['input_hash'] != high['input_hash']
            assert {o['kind'] for o in high['observations']} == {'angle','distance'}
            assert max(p['ellipse']['a_m'] for p in high['points']) > max(p['ellipse']['a_m'] for p in low['points'])
            page.select_option('#engineering-scenario',b['scenario_id'])
            page.click('#engineering-calculate')
            page.wait_for_function('document.querySelector("#engineering-result").textContent.includes(\'"kind": "gnss"\')')
            gnss=json.loads(page.text_content('#engineering-result'))
            assert gnss['summary']['max_mp_mm'] < high['summary']['max_mp_mm']
            with page.expect_navigation(wait_until='networkidle'):
                page.click('#engineering-open')
            assert page.locator('#engineering-gnss input[data-key="correlation"]').input_value() == '0.3'
            page.reload(wait_until='networkidle')
            assert page.locator('#engineering-gnss input[data-key="correlation"]').input_value() == '0.3'
            page.fill('#engineering-name','刷新后另存')
            page.click('#engineering-save')
            page.wait_for_function('document.querySelector("#engineering-result").textContent.includes("snapshot_id")')
            refreshed=json.loads(page.text_content('#engineering-result'))
            assert page.request.get(base+'/api/engineering/settings/'+refreshed['scenario_id']).json()['gnss'][0]['correlation'] == .3
            page.get_by_text('GNSS 二维基线参数（随保存/派生持久化）', exact=True).click()
            page.screenshot(path=str(Path('/workspace/ctrlnet-v08')/'stage2_gnss.png'))
            for checkbox in page.locator('#observed-edge-list input').all():
                checkbox.check()
                page.wait_for_function('!window.ctrlnetThesis.state.busy')
            page.fill('#engineering-name','实测参数验证')
            page.click('#engineering-save')
            page.wait_for_function('document.querySelector("#engineering-summary").textContent.includes("已保存") && document.querySelector("#engineering-name").value === "实测参数验证"')
            # Wait on a new scenario rather than matching the previous save response.
            page.wait_for_function('(old) => JSON.parse(document.querySelector("#engineering-result").textContent).scenario_id !== old', arg=refreshed['scenario_id'])
            measured=json.loads(page.text_content('#engineering-result'))
            page.click('#engineering-estimation > summary')
            page.click('#engineering-template')
            page.wait_for_function('document.querySelector("#engineering-values").value.startsWith("[[")')
            assert '非实测' in page.text_content('#engineering-observation-labels')
            values=json.loads(page.input_value('#engineering-values'))
            import random
            rng=random.Random(30)
            template=page.request.get(base+'/api/engineering/observations/'+measured['scenario_id']).json()
            for row, obs in zip(values,template['observations']):
                for i in range(len(row)): row[i] += rng.gauss(0, 2e-6 if obs['unit']=='rad' else .005)
            values[0][0] += .3
            page.fill('#engineering-values',json.dumps(values))
            estimates=[]
            for method,threshold in [('ls','1.345'),('huber','0.8'),('huber','3'),('igg3','1.345')]:
                page.select_option('#engineering-method',method)
                page.fill('#engineering-c',threshold)
                page.fill('#engineering-max-iter','100')
                with page.expect_response('**/api/engineering/estimate/*') as response:
                    page.click('#engineering-estimate')
                result=response.value.json()
                assert response.value.status == 200,result
                assert result['method'] == method
                estimates.append(result)
            assert estimates[0]['weights'] != estimates[1]['weights']
            assert estimates[1]['weights'] != estimates[2]['weights']
            assert min(estimates[1]['weights']) < 1
            page.fill('#engineering-c','0')
            page.click('#engineering-estimate')
            page.wait_for_function('document.querySelector("#engineering-summary").textContent.includes("c>0")')
            page.fill('#engineering-c','1.345')
            page.fill('#engineering-max-iter','1')
            page.select_option('#engineering-method','huber')
            page.click('#engineering-estimate')
            page.wait_for_function('document.querySelector("#engineering-summary").textContent.includes("未收敛")')
            (Path('/workspace/ctrlnet-v08')/'stage2_estimation_evidence.json').write_text(json.dumps(dict(template=template,estimates=estimates),ensure_ascii=False,indent=2))
            page.screenshot(path=str(Path('/workspace/ctrlnet-v08')/'stage2_robust.png'))
            page.locator('#engineering-summary').scroll_into_view_if_needed()
            page.screenshot(path=str(Path('/workspace/ctrlnet-v08')/'stage2_robust_result.png'))
            page.goto(base+'/dashboard',wait_until='networkidle')
            page.wait_for_function('window.ctrlnetReady === true')
            page.click('#engineering-panel > summary')
            page.select_option('#engineering-project',a['project_id'])
            page.select_option('#engineering-scenario',a['scenario_id'])
            page.select_option('#engineering-candidate',b['scenario_id'])
            page.click('#engineering-compare')
            page.wait_for_function('document.querySelector("#engineering-result").textContent.includes("base_hash")')
            diff=json.loads(page.text_content('#engineering-result'))
            assert diff['base_hash'] != diff['candidate_hash']
            page.screenshot(path=str(Path('/workspace/ctrlnet-v08')/'stage2_dashboard.png'))
            assert page.request.get(base+'/api/project').json()['selected_scenario'] == 'dem-all'
            assert not errors,errors
            (Path('/workspace/ctrlnet-v08')/'stage2_engineering_evidence.json').write_text(json.dumps(dict(saved=a,branch=b,options=[low['options'],high['options']],compare=diff,pageerrors=errors),ensure_ascii=False,indent=2))
            browser.close()
        print('PASS: measured values / LS / Huber c / IGG-III / invalid parameter / nonconvergence; GNSS editable/persisted/opened/computed; thesis named project/save/parent snapshot/branch/open topology; 95/99% UI/API/ellipse; dashboard scoped selection/compare; no global map overwrite; zero pageerror')
    finally:
        proc.terminate();proc.wait(timeout=10)
