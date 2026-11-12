# Selected line addition merge

Line additions between distinct points common to all three saved snapshots now
merge even when selected in observed_edges or added_edges. Selection follows the
existing whole-network merge and explicit conflict-choice rules. Every accepted
addition is retained for either network choice. Authored measurements, target-first
order, geometry recomputation and allocator high-water marks use the existing
line restoration path.

Competing authored IDs/names, duplicate endpoint pairs, unknown fields and
new/deleted endpoint references remain conservative whole-topology conflicts.
Selected line/angle deletions, selected angle additions and ambiguous merge bases
remain unsupported by this bounded improvement. Accepted v0.8 is unchanged.

Full pytest: 594 passed, 1 skipped, 2 xfailed, 8 warnings in 54.10s.
Focused scenario suite: 205 passed. Independent review PASS includes a separate
205-test run and Chromium rerun. Chromium exercises a store-seeded selected
measured addition, HTTP coordinate edits, UI preview/merge, restart/reopen,
selection and measurement preservation, recomputed azimuth, target order, dual
parents and fresh allocation. Saved distance observations are checked in pytest.
The editor has no measurement editing endpoint, so that input is seeded through
the store. Full-suite results and initial obsolete-expectation failures are retained
under /workspace/ctrlnet-v08/cn_post_v08_selected_line_addition/.

Sample database SHA256 matches HEAD. Prior evidence and unrelated worktree dirt
are preserved; no changes were made to cc-gins.
