# Object inspector readability

Candidate `dashboard_inspector_rows` improves the dashboard object inspector with separated label/value rows, brighter labels, more line spacing and wrapping within narrow panels. Data rendering and map handlers are unchanged.

Evidence is recorded in `/workspace/ctrlnet-v08/cn_frontend_visual_inspector`: real map selection screenshots before/after at 1440, 1024, 390 and 320px, focused browser checks, full pytest, GNSS/robust browser regressions and independent review. The initial regression launch lacked Playwright's bundled browser; the recorded rerun uses installed Chromium via the artifact harness.

Existing acceptance status and product gaps remain unchanged. Prior evidence, unrelated target deletions and scratch files are preserved and excluded from this commit.

Validation: 1274 passed, 1 skipped (optional pyproj absent), 2 xfailed, 8 warnings in 176.64s. Focused four-width Chromium before/after and GNSS/robust regressions PASS. Independent review PASS with 31 focused tests and five-width network-point/observation/ellipse/long-value coverage.
