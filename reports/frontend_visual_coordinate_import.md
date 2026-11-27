# Coordinate import control

Candidate `thesis_coordinate_import_group` groups the coordinate-file picker and coordinate-system guidance in a bordered panel. The label stacks above a full-width native file picker with a 44px target and visible keyboard focus. Guidance uses 13px text and is associated through `aria-describedby`. The change adds vertical space above the point library.

Chromium before/after captures at 1440, 900, 390 and 320px and actual two-point coordinate imports are recorded in `/workspace/ctrlnet-v08/cn_frontend_visual_coordinate_import`. Baseline source, reproduction script and scoped patch are preserved there. JavaScript behavior is unchanged. The native picker text follows browser locale.

Full pytest: 1274 passed, 1 skipped, 2 xfailed, 8 warnings in 221.41s. Focused four-width imports and thesis/shared-project/GNSS/robust browser regressions passed. Independent final review PASS. Initial regressions could not find default Playwright Chromium; reruns explicitly used installed Chromium. Sample SQLite checksum unchanged. No acceptance or remaining-gap claims change.
