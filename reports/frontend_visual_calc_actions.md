# Thesis calculation and export buttons

Candidate `thesis_calc_action_bar`

The action bar uses 44px minimum button heights, larger labels, and consistent spacing. The green Calculate button spans the row when the panel is narrow. The coordinate and angle export buttons stay together at equal widths. At wide panel widths all three share a row. The stacked layout uses more vertical space at widths where the original row fit, including the tested 900px viewport.

Before/after Chromium captures cover 1440×950, 900×950, 390×844, 320×568, and 740×360. The focused browser scenario loads thesis example 1, checks Tab and Shift+Tab order, runs the calculation with Enter, and opens both exports with Space. It checks the resulting calculation and export content and closes each export with Escape.

Evidence and browser scripts are in `/workspace/ctrlnet-v08/cn_frontend_visual_calc_actions/`. The thesis, GNSS/shared-project, and robust-estimation Chromium regressions passed. Independent read-only review passed. Focused pytest reported 49 passed, 1 skipped, and 2 xfailed.

Full pytest reported 1274 passed, 1 skipped, 2 xfailed, 8 warnings.
