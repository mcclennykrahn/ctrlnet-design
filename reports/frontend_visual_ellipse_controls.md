# Thesis result ellipse controls

Candidate: `thesis_ellipse_controls`; new source work after pushed `92873fe`.

The result ellipse toggle and magnification field now use 13px text, softly shaded label groups, a 16px checkbox, a 36px number input, and a focus-within surface. Labels wrap as complete groups. Existing keyboard outlines and calculation/event behavior remain intact. This is a CSS-only change.

Chromium before/after captures cover 1440×950, 900×950, 390×844, 320×568 and 740×360. The magnification field grows from 23px to 36px. The focused harness loads example 1, calculates 17 denominator rows, checks page-width containment, toggles ellipse visibility, edits magnification and captures focused controls. Narrow layouts take two rows and leave less vertical space for the result table.

Evidence: `/workspace/ctrlnet-v08/cn_frontend_visual_ellipse_controls/`, including baseline CSS, focused harness, five-size screenshots, metric logs, isolated regression copies, pytest output, source diff and independent review. Regression artifacts are redirected into this stage directory to preserve prior evidence. The initial setup used unavailable `python`; it was rerun using `.venv/bin/python` before source editing.

Acceptance and existing product gaps are unchanged. Unrelated target-document deletions and workspace dirt are excluded. Sample SQLite matches HEAD.

Validation: full pytest 1274 passed, 1 skipped, 2 xfailed, 8 warnings in 207.13s; focused web tests 31 passed. Five-size Chromium before/after and thesis, GNSS/shared-project and robust-estimation regressions PASS. Independent source/visual review PASS with additional Chromium checks at 280×400, 820×700 and 1440×950, including actual map ellipse removal/restoration and a successful magnification network update. Optional pyproj remains unavailable.
