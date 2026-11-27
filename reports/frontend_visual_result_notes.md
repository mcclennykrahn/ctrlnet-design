# Calculation result explanation readability

Candidate `thesis_result_notes_readability` increases the result explanation and weakest-edge text to 13px with 1.7 line spacing. A bordered white note separates the numeric convention and matrix details from the verdict. Long diagnostics wrap inside the panel; empty paragraphs remain hidden. The larger text and spacing require more scrolling to reach the denominator table.

Chromium before/after captures cover 1440×950, 900×950, 390×844, 320×568 and 740×360. The focused scenario checks the result text bounds, calculation, keyboard order and both exports. Thesis, GNSS/shared-project and robust-estimation browser regressions passed. Full pytest: 1274 passed, 1 skipped, 2 xfailed, 8 warnings. Independent read-only source and visual review PASS.

Evidence: `/workspace/ctrlnet-v08/cn_frontend_visual_result_notes/`. Existing acceptance and remaining gaps are unchanged. Unrelated worktree deletions and runner files are excluded.
