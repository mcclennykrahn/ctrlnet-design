"""Optional offline Playwright smoke check; start ctrlnet-web on port 8765 first."""
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
 b=p.chromium.launch(headless=True,args=['--no-sandbox'])
 page=b.new_page(viewport={'width':1440,'height':900})
 errors=[]; urls=[]
 page.on('pageerror',lambda e:errors.append(str(e)))
 page.on('request',lambda r:urls.append(r.url))
 page.goto('http://127.0.0.1:8765/',wait_until='networkidle')
 page.wait_for_function('window.ctrlnetTerrainView && window.ctrlnetApp')
 print(page.locator('#terrain-status').inner_text())
 page.evaluate('window.ctrlnetApp.map.setZoom(0)')
 page.wait_for_timeout(1500)
 page.select_option('#scenario-select','s13-base')
 page.wait_for_function('window.ctrlnetScenarioReady === "s13-base"')
 page.evaluate('window.ctrlnetApp.showProfile("P1","P2")')
 page.wait_for_timeout(1000)
 page.screenshot(path='/tmp/ctrlnet-viewport.png')
 assert page.locator('#report-html').get_attribute('href').endswith('scenario=s13-base&format=html')
 assert page.evaluate('window.lastProfile.visible') is True
 print('errors',errors)
 print('layer requests',[u for u in urls if '/api/layers' in u])
 assert not errors
 assert all('terrain=false' in u for u in urls if '/api/layers' in u)
 b.close()
