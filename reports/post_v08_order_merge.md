# Bounded reordered scenario topology merge

Saved scenario merges now match existing points and lines by ID when their lists
have been reordered. With otherwise unchanged structure, independent point
fields, measured line overrides and whole-network settings keep the existing
three-way merge behavior. Competing authored fields still offer whole-point,
whole-line or whole-network choices. Combined topology retains target list order;
existing single-sided whole-topology selection keeps the chosen branch's order.
Derived geometry is recomputed and both parents remain unchanged.

This closes only the ordering portion of the structural merge gap. Additions,
deletions, endpoint changes, angle ordering, projection/other authored fields,
and ambiguous criss-cross bases remain conservative or unsupported. No new API
payload or UI control is needed. Accepted v0.8 and version 0.8.0 are unchanged.

Focused API tests cover target/source/both reorderings, disjoint edits, point and
line conflicts, parent immutability, reopen and changed-structure guards. The
focused Chromium script uses an HTTP coordinate branch and a store-seeded
reordered measured branch, then previews/merges through the UI and verifies
restart/reopen with target order and values preserved. Store seeding is needed
because the editor has no measured-line override editing endpoint.

Evidence, full pytest output and independent review:
`/workspace/ctrlnet-v08/cn_post_v08_order_merge/`.
The initial full test run retained two legacy expectations that reordering must
conflict; these were updated to projection guards and the corrected suite rerun.
The repository-local venv lacked pytest; validation uses the existing shared
ctrlnet venv. Preexisting deleted docs and runner dirt are excluded.

Validation result: **425 passed, 1 skipped, 2 xfailed**, 8 warnings in 31.39s.
Focused Chromium: **PASS**. Independent review: **PASS**, with independent
focused pytest **36 passed**, 1 warning in 3.83s. Demo SQLite SHA256 unchanged:
`fa597f57b5952fa603b9464550c5d72e9c7c2b6bd4efc48c8281692b84a204f6`.
