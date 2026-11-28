# Profile empty-state guidance

The dashboard now shows two numbered map-click steps and a compact terrain/sightline illustration before a profile is calculated. Readable labels replace the developer-call example and faint placeholder. The existing result and no-data renderers are unchanged. Dashboard regression waits now target the calculated chart directly rather than the decorative SVG.

Chromium before/after screenshots cover 1440, 820, 390 and 320 CSS pixels. The focused check performs real map clicks over known DEM terrain at each width, verifies the guidance is replaced by result measurements, and checks containment and browser errors. Initial test coordinates hit interactive observation lines or sampled outside the DEM; the final fixture offsets the known route into valid terrain.

Validation: full pytest — 1274 passed, 1 skipped, 2 xfailed, 8 warnings (203.67s). Focused four-width capture and five-width dashboard, thesis calculation, shared-project/GNSS and robust-estimation browser regressions passed. Independent review PASS is recorded with screenshots and logs at `/workspace/ctrlnet-v08/cn_frontend_visual_profile_empty`. Sample SQLite SHA-256 matches the recorded baseline. Existing acceptance records and product gaps remain unchanged.
