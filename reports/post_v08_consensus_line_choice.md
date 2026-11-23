# Lone line choice over differing-content merge bases

One bounded post-v0.8 extension: retain a whole-line choice when every best base reports only the same line conflict and both target/source outcomes produce equivalent authored topology across every base. Commit recomputes the all-base plan with the selected line, preserving independent edits, target order, allocator high-water marks, versions and provenance.

Mixed or multiple field conflicts, mismatched per-base conflicts, disagreeing outcomes and recursive ancestor reconciliation remain unsupported. Accepted v0.8 is unchanged. Prior document deletions and runner dirt are excluded.

Validation evidence: `/workspace/ctrlnet-v08/cn_post_v08_consensus_line_choice`. Focused tests cover numeric names and kept measured lengths in both directions, both choices, rejection atomicity, stale bases and both-outcome consensus guards. Chromium merge/restart/reopen passed. Full pytest and independent review results are recorded with the stage artifacts.

Validation result: 948 passed, 1 skipped, 2 xfailed, 8 warnings in 107.75s; latest expanded focused suite: 15 passed. PASS: independent 66 focused tests, latest 15 tests, 8 external API probes and prepatch regression check.
