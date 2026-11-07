# Bounded point-coordinate scenario merge

Saved scenarios with a unique common ancestor now automatically combine coordinate
edits to different existing points. Each point's x/y/lon/lat tuple is one unit;
conflicting edits to the same point still require a whole-topology choice.
The preview and merge controls use this behavior without a new option.

Automatic combination requires identical point IDs, order, names, fixed status,
line/angle structure, network settings, projection and all other authored data.
Timestamps and computed line/angle geometry are ignored for comparison. Computed
geometry is refreshed after combination. Measured line overrides are preserved
and compared; moving a point that clears such an override may therefore require
a manual choice. Point addition/deletion, reorder, rename, fixed status, settings
or structural changes are outside this stage's automatic merge scope.

GNSS remains a separate unit and endpoints are validated against the merged
points. Saving still creates a new scenario/snapshot atomically, retains both
parents and versions, checks stale previews, and leaves parents untouched.

This is one bounded portion of the topology gap. General record/field merging,
manual per-point conflict resolution and ambiguous criss-cross merge bases remain
open. Accepted v0.8 and the package version are unchanged; no release or product
maturity claim is added.

Validation: tests/test_scenario_tree.py covers disjoint edits, regenerated
geometry, GNSS combination, reopen and parent preservation, plus conservative
fallbacks for authored changes and the existing conflict/stale/rollback cases.
scripts/test_point_merge_e2e.py drives real point movement HTTP requests and
Chromium preview/merge controls on an imported geometry-only network, restarts the
server and reopens both merged coordinates. Stage results and independent review
are recorded in /workspace/ctrlnet-v08/cn_post_v08_point_merge/.

Stage regression: **400 passed, 1 skipped, 2 xfailed** (8 warnings, 29.00s).
The initial browser attempt reached merge/restart but timed out at reopen due to
a missing test dialog handler; the retained attempt and corrected rerun are in
the stage artifacts. The demo SQLite checksum is unchanged.
Focused Chromium rerun: **PASS**, including server restart and UI reopen.
