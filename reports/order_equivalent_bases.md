# Reordered equivalent scenario bases

One bounded post-v0.8 improvement: multiple best bases whose points, lines and
angles differ only in presentation order now retain ordinary field merge choices.
Stable IDs define ancestor identity; the resulting topology retains target order.
Known allocator maxima still include every best base and both tips, and every
base remains in provenance and stale-version checks. Saved ancestors are unchanged.

The comparison sorts copies only, validates unique nonempty string IDs, and retains
all unknown fields. Actual authored ancestor differences still require whole-unit
choices, converged tips or identical clean results from every best base. Recursive
reconciliation of competing ancestor edits remains unsupported. Observation selection
list order is not normalized. Accepted v0.8 status is unchanged.

Validation evidence is recorded under
`/workspace/ctrlnet-v08/cn_post_v08_order_equivalent_bases`.

Review caught a one-sided trivial-merge shortcut selecting source order after the
new equivalence classification. Reordered-base merges now use the stable-ID field
merge for that case. The prior authored-tip convergence path remains available,
including structural convergence with differing known counters. Regression tests
cover both cases. Initial review FAIL and corrected verification remain in the
stage artifacts. Early browser fixture failures came from point deletion renaming
all items after reversal; the final fixture asserts authored equivalence before
building the criss-cross DAG.

Final author validation: 853 passed, 1 skipped, 2 xfailed, 8 warnings in 69.81s.
Focused Chromium merge/restart/reopen/fresh allocation passed. The existing
allocator-equivalent-base Chromium scenario also passed after the shared harness
refactor. Sample SQLite SHA256 matches HEAD; unrelated worktree deletions and
runner artifacts are excluded. Initial superseded expectations and failed fixture
runs are retained outside git. No changes were made to cc-gins.

Independent verification: 419 focused tests and external probes passed; latest
Chromium and prior allocator-equivalent Chromium runs passed. The independent
review found and verified the target-order regression fix. An expanded review run
also exposed an existing full-state timestamp comparison crossing a one-second
boundary; its failure evidence is retained and the unchanged suite rerun passed.
