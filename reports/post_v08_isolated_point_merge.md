# Bounded isolated-point addition merge

Saved scenarios can combine isolated point additions with supported existing-field
edits. Existing IDs are retained, the target point order is preserved, and
source-only additions append in source order. Identical additions sharing an ID
are kept once. The point allocator retains both branches' high-water marks.
Existing point conflicts still offer whole-point choices alongside the additions.

Competing additions sharing an ID, duplicate resulting names, point deletions,
new lines/angles or references to added points, and unknown authored fields remain
whole-topology conflicts during combined topology merges. Independently adding
points in the browser often allocates the same next ID; different such additions
therefore require a whole-topology choice. This stage does not remap IDs or names.
Ambiguous criss-cross merge bases remain unsupported. Accepted v0.8 is unchanged;
this is one bounded extension, with no production maturity claim.

Tests cover one-sided and disjoint additions, identical/same-ID competing
additions, target order, allocator high-water marks, existing-point choices,
conservative boundaries, missing-choice rollback, parent immutability and reopen.
Focused Chromium uses real HTTP point creation, preview and merge, process
restart, UI reopen, and a subsequent point addition to check fresh allocation.

Validation and independent review evidence:
`/workspace/ctrlnet-v08/cn_post_v08_isolated_point_merge/`.

Final pytest: 489 passed, 1 skipped, 2 xfailed, 8 warnings in 31.25s.
Independent review PASS: 100 focused tests and separate Chromium rerun PASS.
Sample database hash unchanged; prior evidence and unrelated dirt preserved.
