# Bounded angle list ordering merge

Combined saved-scenario field merges now compare existing angles by stable ID,
ignoring list order and derived angle values, while retaining target angle order.
IDs must be unique nonempty strings. Angle references, names and other authored
fields remain conservative whole-topology conflicts, as do additions/deletions.
Ambiguous criss-cross bases remain unsupported. Existing point, measured line,
and network merge choices remain unchanged. Accepted v0.8 is unchanged.

API regression covers target/source/both reordered angles with disjoint point
and line fields and competing whole-point/line choices, parent immutability and
reopen. Guard cases cover duplicate/missing IDs, additions/deletions, station,
name and unknown authored fields. The focused Chromium script uses an HTTP
coordinate branch and a store-seeded reordered measured branch, then verifies
UI preview/merge and restart/reopen with target point/line/angle order retained.
The editor has no measured-line override editing endpoint.

Evidence: `/workspace/ctrlnet-v08/cn_post_v08_angle_order_merge/`.
Preexisting deleted docs and runner dirt are excluded. Demo SQLite SHA unchanged.
Initial browser attempt lacked the default Playwright browser; the rerun uses
installed Chrome via CHROMIUM_EXECUTABLE. No cc-gins changes.

Validation: 438 passed, 1 skipped, 2 xfailed, 8 warnings in 32.50s.
Focused Chromium PASS; independent review PASS with 49 focused tests rerun.
