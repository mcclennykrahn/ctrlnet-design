# Thesis export dialog

The coordinate and angle text export dialog now has a rounded card, roomier heading,
36px close control and a prominent copy action. The text area can shrink and scroll
while the header and actions remain visible on short viewports. Narrow screens
use 12px outer margins. Changes are scoped to the export dialog CSS.

Chromium before/after evidence covers 1440×950, 900×950, 390×844, 320×568 and
740×360. The focused check exercises coordinate/angle exports, clipboard contents,
keyboard focus, both close controls, Escape and text scrolling. Taller desktop
spacing is a tradeoff; short screens scroll the export text.

Full pytest: 1274 passed, 1 skipped, 2 xfailed, 8 warnings in 630.78s.
Thesis calculation, shared-project/GNSS and robust estimation browser regressions
passed. Harness retries and their causes are retained in the artifact directory;
Playwright controlled clock advances toast timers for deterministic captures;
no production logic changes were needed. Independent review is recorded there.

Evidence: `/workspace/ctrlnet-v08/cn_frontend_visual_export_dialog/`.
Existing product gaps and maturity claims are unchanged.
