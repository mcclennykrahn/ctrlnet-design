# Bounded existing-angle name merge

Combined saved-scenario field merges now merge existing angle numeric names by
stable ID. A competing name offers an explicit whole-angle target/source choice
in the browser. Target list order is retained and derived values are recomputed.
References, additions/deletions and unknown authored fields still require a
whole-topology choice. Ambiguous criss-cross merge bases remain unsupported.
This closes only the existing-angle name portion of the remaining topology gap;
accepted v0.8 and product maturity claims are unchanged.

API regression covers disjoint edits, competing names in both directions,
missing/invalid/extra choices, parent immutability, ordering and reopen. Guard
cases cover station, backsight and foresight changes. Focused Chromium covers
an HTTP coordinate edit plus store-seeded numeric angle names (the editor has
no angle rename endpoint), a competing source choice, measured line retention,
target order, restart and reopen. Independent review reruns focused tests and
Chromium. Evidence and final validation counts are recorded under
`/workspace/ctrlnet-v08/cn_post_v08_angle_name_merge/`.

The initial full test invocation had a benchmark subprocess import failure;
the full suite is rerun with PYTHONPATH pointing to the source tree. No code was
changed for this environment issue. Pre-existing docs deletions and runner dirt
are excluded; demo SQLite SHA remains unchanged. No cc-gins changes.

Validation: 442 passed, 1 skipped, 2 xfailed, 8 warnings in 30.85s.
Focused Chromium PASS; independent review PASS (53 focused tests and Chromium).
