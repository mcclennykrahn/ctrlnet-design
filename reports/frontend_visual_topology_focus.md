# Snapping keyboard focus

Candidate `thesis_topology_focus` adds a green active label and matching input border
when keyboard users focus the snapping fields. The existing outline remains visible.
This is an incremental change on pushed topology layout commit `5df76eb`.

Evidence: `/workspace/ctrlnet-v08/cn_frontend_visual_topology_focus/`.
Chromium checks cover 1440, 900, 390 and 320px, JSON round trips, undo/redo,
editable snapping settings and visible keyboard focus. Full pytest: 1274 passed,
1 skipped (optional pyproj unavailable), 2 xfailed. Thesis, GNSS, robust estimation
and snap/history restart regressions passed on the integrated working tree.

Earlier artifact-local regression startup failed due to a copied script's ROOT;
correcting the artifact runner path resolved it. Existing stage evidence and product
gaps remain preserved. Final independent review is recorded with the stage artifacts. Fresh focused thesis
pytest also passed: 34 passed, 1 skipped, 2 xfailed.
