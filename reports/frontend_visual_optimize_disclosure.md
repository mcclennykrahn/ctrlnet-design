# Thesis optimization disclosure

Candidate: `thesis_optimize_disclosure`; new source work after pushed `31b8ecb`.

The optimization disclosure now has a 44px minimum click target, 13px semibold text, a warm expanded surface, a divider above its nested observations, and an inset keyboard focus outline. Native details/summary behavior and disclosure marker remain intact. The larger summary and content padding consume more vertical space on phones. CSS-only change.

Chromium before/after captures cover 1440×950, 900×950, 390×844, 320×568 and 740×360. Measured summary height grows from 24.67px to 44px at each size. The focused harness loads example 1, checks keyboard Enter/Space and click toggling, confirms nested controls remain visible, and checks horizontal containment and JavaScript errors. Independent source/visual review PASS includes separate Chromium checks at 280×400, 820×700 and 1440×950, including checkbox state retention after reopening.

Evidence: `/workspace/ctrlnet-v08/cn_frontend_visual_optimize_disclosure/`. Full pytest, focused web tests, and thesis, GNSS/shared-project and robust-estimation regressions are recorded there. Acceptance and product gaps unchanged; unrelated deletions and scratch files excluded.

Evidence handling limitation: the initial regression copies retained the previous delivery's absolute output paths and refreshed its regression screenshots and JSON. Original bytes were not backed up. Prior before/after images, independent review, pytest logs, source patch and delivery were retained. `preservation.json` lists the affected files. Paths were corrected and regressions rerun into this delivery's directory. An initial focused pytest invocation used nonexistent test filenames; corrected invocation passed.

Validation: full pytest 1274 passed, 1 skipped, 2 xfailed, 8 warnings in 193.24s; focused web tests 31 passed. Five-size before/after Chromium, three browser regressions and independent review PASS. Optional pyproj absent. Sample SQLite SHA unchanged.
