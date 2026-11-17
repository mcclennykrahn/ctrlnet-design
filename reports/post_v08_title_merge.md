# Editor project-title scenario merge

One-sided changes to the saved editor state's `name` now combine with supported
geometry, structure and network edits. This title is distinct from the scenario
name supplied when saving a merge. Target list order, allocator high-water marks,
parent snapshots and all-base version/provenance guards retain their existing
behavior. Presence and explicit null are compared separately.

Competing title edits remain a whole-topology conflict; no extra resolution
control is introduced. Unknown authored fields, unsupported structural conflicts
and recursive reconciliation of competing ancestor edits remain conservative.
Differing-content best bases accept title combinations only when every base
independently yields the same conflict-free topology result.

Validation and independent review are recorded under
`/workspace/ctrlnet-v08/cn_post_v08_title_merge/`. The focused browser scenario
imports a title edit, merges through Chromium across a real criss-cross DAG,
restarts the server and reopens the result, checking title, independent point
edits, order, allocator and provenance. Initial environment/fixture failures are
retained alongside final results. This is one bounded remaining-field gap;
accepted v0.8 and outstanding deployment/CRS work are unchanged.

Stage validation: **753 passed, 1 skipped, 2 xfailed**, 8 warnings in 61.14s.
Author Chromium: **PASS**. Independent review: 364 focused tests and three
additional probes passed; independent Chromium restart/reopen also passed.
Demo SQLite SHA256 remains
`fa597f57b5952fa603b9464550c5d72e9c7c2b6bd4efc48c8281692b84a204f6`.
