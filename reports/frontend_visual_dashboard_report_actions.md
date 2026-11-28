# Dashboard report downloads

The dashboard header gives HTML, Markdown and DOCX report links a minimum 44×44px hit area and uses a 12px font. The primary link names HTML explicitly, and the other links identify their formats in their accessible names. At widths up to 480px the three links share a dedicated row, with HTML filling the remaining space. The offline badge moves below that row.

Chromium evidence covers 1440, 1241, 1025, 1024, 390 and 320px. The focused check verifies header containment and non-overlap, forward and reverse tab traversal, keyboard activation of HTML, pointer activation of MD and DOCX, and nonempty downloads for the selected scenario. DOCX requires Pandoc, supplied for this check from a temporary test directory. The first baseline attempt exposed that missing dependency. The final captures wait for the loading overlay to clear.

Evidence is in `/workspace/ctrlnet-v08/cn_frontend_visual_dashboard_report_actions`.

Full pytest returned 1274 passed, 1 skipped, 2 expected failures and 8 warnings. The dashboard map and profile, thesis calculation, shared-project/GNSS and robust-estimation Chromium regressions passed. The artifact directory records the regression screenshot paths refreshed by the first run.
