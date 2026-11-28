# Dashboard selectors

The scenario, basemap and comparison selectors now share dark styling, 44px minimum height, full panel width and visible focus. Basemap and comparison labels use consistent 12px type with spacing above their controls. The basemap status wraps within the panel. The change is limited to dashboard HTML/CSS; selection and comparison logic is unchanged.

Chromium before/after evidence covers 1440, 1024, 390 and 320px. The focused harness checks target size, focus visibility, horizontal containment, scenario switching, and a successful comparison API response with rendered snapshot output. Dashboard regression additionally covers five widths, layer toggling and terrain profiles. Thesis calculation, shared-project/GNSS and robust-estimation regressions are recorded separately.

Evidence: `/workspace/ctrlnet-v08/cn_frontend_visual_dashboard_selectors`. Full pytest: 1,274 passed, 1 skipped, 2 xfailed, 8 warnings in 208.45s (explicit exit 0). Independent source and visual review: PASS. All four browser regressions passed. The initial pytest shell reported exit 143 after a complete passing summary; its cause is unconfirmed. The isolated confirmation run above supplies the final test gate. This is a bounded visual change and does not close existing product gaps.
