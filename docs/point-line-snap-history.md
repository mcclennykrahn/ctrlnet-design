# Point/line snapping and durable editor history

Post-v0.8 stage `cn_post_v08_gap` adds one editor gap. The existing v0.8 acceptance and version remain unchanged.

In `/thesis`, set **点/线段吸附** to a distance in metres (0 disables it; maximum 1000). Adding or dragging a point selects the nearest existing point or location on a finite line segment within that distance, after optional grid snapping. Equal distances prefer a point, then a stable ID. Moving a point excludes itself and its incident segments. Fixed points remain locked. Snapping aligns coordinates; it does not merge point IDs or split a line. Projected engineering coordinates determine distances, rather than screen pixels.

The active draft and the last 20 undo/redo snapshots now share one SQLite record in `thesis_draft` in the configured `CTRLNET_THESIS_DB`. Successful editor mutations persist before returning; failures roll back live state and history. Undo/redo survive page reload and service restart. A new edit clears redo. Imports, example/new project loads, legacy saved-project loads, and shared-scenario opens participate in the same history. Named legacy saves update the saved project and draft in one transaction. Existing saved projects need no conversion.

This remains a single-user active editor per database, not per browser or account. History is bounded, crosses project switches, and is not an audit log or a full scenario lifecycle system. No release or production maturity claim is added.

Validation: `python -m pytest -q`; `CHROMIUM_EXECUTABLE=/path/to/chrome python scripts/test_snap_history_e2e.py`. The focused e2e uses isolated databases and tests the normal Leaflet click/drag listeners, server restart recovery, and undo/redo controls.
