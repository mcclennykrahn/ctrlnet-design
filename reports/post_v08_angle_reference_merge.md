# Bounded existing-angle reference merge

Existing-angle station, backsight and foresight changes now combine with edits
to independent objects by stable ID. The entire authored angle is indivisible:
reference triples and numeric names travel together. Competing reference edits,
or a reference edit against a name edit on the same angle, require a whole-angle
target/source choice. Derived values are recomputed from the selected references
and merged coordinates. Target list order and both parent scenarios are retained.

Only three distinct references to existing point IDs are in scope. Additions,
deletions, unknown authored fields and ambiguous criss-cross bases remain
conservative/unsupported. Network selections remain an independent whole-object
unit; users must review the resulting network before adjustment. There is no
new angle-reference editing UI. Accepted v0.8 and maturity claims are unchanged.

Tests cover automatic and identical edits, competing reference triples, name
versus reference conflicts, both choices, invalid references, atomic invalid or
missing-choice rejection, recomputed values, parent immutability, target order
and reopen. Chromium exercises preview, whole-angle source choice, merge and
restart/reopen with store-seeded reference branches and an HTTP coordinate edit.

Validation and independent review evidence:
`/workspace/ctrlnet-v08/cn_post_v08_angle_reference_merge/`.

Full pytest: 479 passed, 1 skipped, 2 xfailed, 8 warnings in 37.96s.
Independent review PASS: 90 focused tests and final Chromium rerun PASS.
Demo SQLite SHA unchanged; prior evidence and unrelated worktree dirt preserved.
