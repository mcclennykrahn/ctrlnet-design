# Dashboard responsive layout

Bounded follow-up to the thesis workspace polish: the offline map dashboard now gives DEM and XYZ a shared canvas between desktop sidebars. At widths up to 1024px, the map, shared-project controls, layers and results flow vertically. Header actions wrap, long inspector values remain contained, and keyboard focus has a visible outline.

Map fitting now uses padding relative to the dedicated canvas instead of the old full-window sidebar offsets. This keeps control points in view after initial load and scenario changes.

Evidence: `/workspace/ctrlnet-v08/cn_frontend_visual_dashboard`. Chromium before/after screenshots at 1440, 1024, 820, 390 and 320px; independent checks additionally cover 1120px and DEM/XYZ switching. Validation results and independent verdict are recorded in the delivery artifacts. This change does not close existing product gaps or alter v0.8 acceptance.

Validation: full pytest 1274 passed, 1 skipped (pyproj unavailable), 2 expected failures, 8 warnings in 183.31s. Focused five-width Chromium and existing GNSS/robust-estimation browser regressions PASS. Independent review PASS with 31 focused tests and six-width DEM/XYZ, marker containment, map hit testing, profile and expanded project-drawer checks. Sample SQLite matches HEAD. Existing product gaps remain open.
