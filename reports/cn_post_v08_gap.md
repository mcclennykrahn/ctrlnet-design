# cn_post_v08_gap

Scope: point/finite-line snapping and durable 20-step editor history only. See `docs/point-line-snap-history.md` for behavior and single-user limitations.

Independent source review: PASS, with the named-save persistence issue corrected before final review. Reviewer independently ran 22 focused/regression tests and a named-save/restart/undo/redo probe. External review evidence: `/workspace/ctrlnet-v08/cn_post_v08_gap/review.md`.

Focused Chromium e2e: PASS (UI segment snap, drag point snap, server restart draft recovery, undo after restart, redo after reload, no page errors). Script: `scripts/test_snap_history_e2e.py`.

Full pytest: **366 passed, 1 skipped, 2 xfailed, 8 warnings in 30.85s** (external `pytest.txt`). The skip is optional pyproj; the expected failures retain the existing unpublished thesis-angle limitations. The first complete run found only the existing benchmark's missing `.venv/bin/python` path; final run supplies an ignored local environment link. Earlier collection attempts used environments missing web dependencies; final validation uses an isolated environment with project test/webmap/e2e dependencies.

Sample database SHA-256 remains `fa597f57b5952fa603b9464550c5d72e9c7c2b6bd4efc48c8281692b84a204f6`. Pre-existing deleted target documents and runner files are excluded. Prior v0.8 evidence is preserved; this stage does not change acceptance or version.
