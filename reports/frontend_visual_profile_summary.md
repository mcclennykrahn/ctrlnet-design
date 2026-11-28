# DEM profile result summary

The profile summary now separates the endpoint pair and visibility badge from labeled distance and minimum-clearance cards. Blocked profiles add a full-width obstruction-distance row. Numeric precision, units, calculation data and analysis notes are preserved.

Chromium before/after evidence covers visible P1–P2 and blocked P1–P4 profiles at 1440, 820, 390 and 320 CSS pixels. The focused check compares displayed values with the API response, checks conditional obstruction display, containment and browser errors. Five-width dashboard interaction, thesis calculation and robust/GNSS regressions cover existing behavior.

Independent review: PASS. Full test results and screenshots are recorded in `/workspace/ctrlnet-v08/cn_frontend_visual_profile_summary`. This is a bounded presentation improvement; existing product gaps remain open.

Validation: `pytest -q` — 1274 passed, 1 skipped, 2 xfailed (183.09s). Focused profile, dashboard, thesis and robust/GNSS Chromium checks passed. The sample SQLite SHA-256 matches the recorded baseline.
