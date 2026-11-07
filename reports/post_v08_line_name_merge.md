# Bounded existing-line numeric name merge

Saved-scenario combined field merges now merge existing line numeric names by
stable ID. Disjoint names and measured overrides combine. Competing names or
measurements require a whole-line target/source choice, discarding partial edits
on that line. Target order is retained; derived geometry is recomputed.

Additions/deletions, endpoint and angle reference changes, unknown authored
fields and ambiguous criss-cross merge bases remain unsupported by fine-grained
merge. Accepted v0.8 and product maturity claims are unchanged.

Regression covers both choices, disjoint edits, combined measurement conflicts,
invalid/missing/extra choices, parent immutability, ordering and reopen. Focused
Chromium uses store-seeded numeric line names because no line rename endpoint
exists, then exercises browser preview/choice/merge and restart/reopen with
coordinates and measured overrides retained. Independent review PASS: 62
scenario-tree tests and Chromium rerun. Demo SQLite SHA unchanged; unrelated
worktree deletions and runner dirt excluded. No cc-gins changes.

Final full-suite result is recorded in the stage artifact directory:
`/workspace/ctrlnet-v08/cn_post_v08_line_name_merge/`.

Validation: 451 passed, 1 skipped, 2 xfailed, 8 warnings in 33.46s. Focused Chromium and independent review PASS.
