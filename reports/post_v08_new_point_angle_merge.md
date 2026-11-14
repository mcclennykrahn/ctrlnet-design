# New-point angle addition merge

One bounded post-v0.8 gap: selected or unselected angle additions may reference compatible new points, including points shared with added lines. Each reference must exist on its authoring branch. Existing referenced points must survive both branches; recursion validates added point identity, authored compatibility, names and unknown fields before restoring angles.

Target presentation order, allocator high-water marks, whole-network choices, derived geometry refresh and dual-parent provenance retain the existing behavior. Deleted-point references, competing IDs/names, duplicate ordered triples, delete-versus-edit, unknown authored fields and ambiguous merge bases remain conservative. Accepted v0.8 is unchanged; no maturity claim.

Validation: **700 passed, 1 skipped, 2 xfailed, 8 warnings in 56.91s**. Optional pyproj is unavailable. Focused HTTP/Chromium PASS exercises new point plus selected angle, independent coordinate edit, preview/merge, restart/reopen, recomputed angle, selections, order, provenance and fresh point/angle allocation. Independent review and reruns are recorded under `/workspace/ctrlnet-v08/cn_post_v08_new_point_angle`.

Tests cover one to three new references, target/source/both branches, observed/added/unselected additions, shared new-point line/angle additions and conservative incompatible, unknown, missing-local and deleted-point cases. Initial environment failure (repo venv lacks pytest), obsolete expectation failures and a collinear e2e fixture failure are retained externally; final runs pass. Sample SQLite SHA256 equals HEAD: `fa597f57b5952fa603b9464550c5d72e9c7c2b6bd4efc48c8281692b84a204f6`. Pre-existing deleted documents and runner dirt remain untouched. No cc-gins changes.
