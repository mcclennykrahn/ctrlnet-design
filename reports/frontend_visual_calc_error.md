# Thesis calculation error readability

Candidate: `thesis_calc_error_readability` (new work).

The inline calculation diagnostic used 11.5px text and tight padding. It now uses 13px text with 1.65 line height, 12×14px padding, rounded corners, and a stronger red left border. Long unbroken diagnostic strings wrap inside the panel. The larger message occupies more vertical space; error handling and calculation logic are unchanged.

Chromium before/after captures cover 1440×950, 900×950, 390×844, 320×568 and 740×360. The focused browser script triggers the real empty-project error, checks its text, captures after the transient toast dismisses, exercises a synthetic long diagnostic for layout only, and loads example 1 to verify successful calculation clears the error. Sample SQLite SHA256 matches the recorded baseline. Existing acceptance, gaps and prior evidence remain unchanged.

Evidence and reproducible scripts: `/workspace/ctrlnet-v08/cn_frontend_visual_calc_error/`. Focused pytest: 31 passed. Full pytest: 1274 passed, 1 skipped, 2 xfailed, 8 warnings in 308.67s. Thesis calculation, GNSS/shared-project, and robust-estimation browser regressions passed. Independent review PASS includes Chromium at 280×600, 820×900, 821×900 and 1920×1080; see `independent_review.md`.
