# Thesis denominator result table

Candidate: `thesis_denominator_table`; new source work after pushed `1578378`.

The thesis edge-error denominator table now uses 12px text, 8px cell padding, alternating row surfaces, a green header, and right-aligned numeric columns. The result scroller retains its 180px height and sticky column headings. The subsection heading gains readable spacing. Calculation logic and values are unchanged.

Chromium before/after evidence at 1440×950, 900×950, 390×844, 320×568 and 740×360 uses the real example-1 calculation and checks 17 result rows. Final row height is 34.39px versus 27.67px in the baseline. The larger cells show fewer rows at once; at 320px, the last column needs local horizontal scrolling. The harness checks vertical scrolling, sticky header cells and page width containment, and saves scrolled screenshots.

Evidence: `/workspace/ctrlnet-v08/cn_frontend_visual_denominator/`, including baseline CSS, focused harness, screenshots, metric logs, regression copies with isolated databases and redirected artifact paths, full pytest, and independent review. Initial harness assertion incorrectly measured the scrolling `thead` instead of sticky `th`; corrected and retained failure. Initial regression launches lacked the default Playwright browser; artifact-local copies explicitly use installed Chromium.

Acceptance status and existing product gaps are unchanged. Unrelated target-document deletions and workspace dirt are excluded.

Validation: full pytest 1274 passed, 1 skipped, 2 xfailed, 8 warnings in 207.29s; focused web tests 15 passed. Five-size before/after Chromium and thesis, shared-project/GNSS and robust-estimation regressions PASS. Independent source/visual review and additional Chromium at 280×400, 820×700 and 1440×950 PASS. Sample SQLite SHA matches HEAD. Full pytest ran on the final source change.
