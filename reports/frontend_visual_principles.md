# Thesis explanation-card readability

Candidate: `thesis_principles_readability` (new work).

The three map-side explanation cards used 11.5px body and 10.8px formula text. Body text now uses 13px with 1.75 line height, headings use 14px, and formulas use 12.5px with roomier inset surfaces. Card gaps and padding provide clearer separation. Formula wrapping and minimum-width containment preserve local layout on narrow screens. The existing three-column desktop / single-column narrow layout remains. Taller cards require more scrolling.

Chromium before/after: 1440×950, 900×950, 390×844, 320×568, 740×360. Checked three cards, computed body typography, page/card overflow, and page errors. Independent review PASS includes 280×600, 1100×900, 1101×900 and 1920×1080. Thesis calculation, shared-project/GNSS and robust regressions PASS. Focused pytest: 31 passed. Full pytest: 1274 passed, 1 skipped, 2 xfailed, 8 warnings in 323.93s.

Evidence: `/workspace/ctrlnet-v08/cn_frontend_visual_principles/`, including reproducible browser scripts, baseline CSS, before/after screenshots, independent review and test logs. Prior evidence remains intact; new regression scripts use isolated artifact destinations. Sample SQLite SHA256 matches the recorded manifest baseline. Existing stages, acceptance and gaps remain unchanged; this is a bounded readability improvement.
