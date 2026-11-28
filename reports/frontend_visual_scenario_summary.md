# Scenario summary readability

The dashboard scenario summary now uses a labeled definition list of seven measurements: observation, point and fixed-point counts; max mp and min r_i; visible pairs and redundancy. Three count cards followed by two balanced pairs replace the small inline text. A title/version row and separate parent/snapshot footer improve hierarchy. Existing formatting, missing-value handling and escaped scenario metadata are preserved.

Chromium before/after evidence covers 1440, 820, 390 and 320 CSS pixels. The focused check verifies containment, labels and values against the live project summary before and after switching to dem-opt. Five-width dashboard interactions, thesis calculation and robust/GNSS browser regressions pass. Full pytest: 1274 passed, 1 skipped, 2 xfailed, 8 warnings in 197.67s. Sample SQLite SHA-256 is unchanged.

Artifacts, screenshots and independent review are recorded under `/workspace/ctrlnet-v08/cn_frontend_visual_scenario_summary`. This is a bounded visual improvement; existing acceptance history and product gaps remain unchanged. Initial regression-wrapper runs lacked the script import path and screenshot destination environment variable; corrected runs passed.
