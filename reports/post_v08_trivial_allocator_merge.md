# Allocator preservation for trivial content merges

One bounded post-v0.8 gap: ordinary and equivalent-base topology merges now retain
known point, line and angle allocator maxima across every best base and both tips
when content equality or an unchanged branch selects a snapshot directly. This
covers converged imports and structural deletions with reset counters. Snapshot
content, target ordering and existing three-way selection semantics are preserved;
invalid known counters require a whole-topology choice. Recursive reconciliation
of competing ancestor edits remains unsupported. Accepted v0.8 is unchanged.

Regression coverage includes both directions, ordinary/equivalent bases, converged
authored tips, one unchanged tip, converged angle deletions, ancestor immutability
and stale-base rejection. The focused Chromium check exercises a real equivalent-
base DAG, JSON-import counter reset, merge controls, restart/reopen, all-base
provenance and fresh point allocation above ancestor maxima.

Validation results and independent review are recorded under
`/workspace/ctrlnet-v08/cn_post_v08_trivial_allocators`. Initial full-suite attempts
failed because the benchmark hardcodes the absent `.venv/bin/python`; the final
run uses a temporary link to the existing environment, removed before delivery.
No benchmark implementation or acceptance criteria were changed. The sample
SQLite SHA256 matches HEAD (`fa597f57b5952fa603b9464550c5d72e9c7c2b6bd4efc48c8281692b84a204f6`).
Unrelated worktree deletions, runner files and prior evidence remain untouched.

Final full pytest: **815 passed, 1 skipped, 2 xfailed, 8 warnings in 58.91s**.
Author and independent Chromium checks PASS. Independent review PASS: **51
focused tests and 15 external probes**, including a prepatch failure demonstration.
