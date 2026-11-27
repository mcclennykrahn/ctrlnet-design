# Dashboard version navigation

Candidate `dashboard_version_rows`: each scenario version now has a distinct row with a full-width destination button and a separate parent lineage. Root versions have a quiet label, parent links remain actionable, and the comparison button and output share the dashboard's spacing, borders and colors. Long labels wrap within the sidebar; destination controls are at least 36px tall and parent controls at least 32px.

This is a bounded navigation presentation change. Existing scenario selection, comparison APIs, map rendering and product gaps remain unchanged. No new release or maturity claim.

Evidence: `/workspace/ctrlnet-v08/cn_frontend_visual_versions`. Baseline and final Chromium screenshots cover 1440, 1024, 820, 390 and 320px. The focused browser script checks destination and parent navigation, successful comparison, button containment and size, layer toggles, scenario switching and profile rendering using isolated databases. Full pytest, existing GNSS/robust browser regressions, and independent review results are recorded with the delivery artifacts.

Validation: 1274 passed, 1 skipped (pyproj unavailable), 2 expected failures, 8 warnings in 180.37s. Focused five-width Chromium and existing GNSS/robust-estimation regressions PASS. Independent review PASS: 31 focused tests and separate five-width Chromium navigation, comparison, keyboard focus and long-label containment. Sample SQLite matches HEAD.
