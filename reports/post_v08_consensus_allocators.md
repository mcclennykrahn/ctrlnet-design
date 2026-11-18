# Post-v0.8: all-best-base allocator consensus

A differing-content criss-cross merge can have the same conflict-free authored
result from every best base while each candidate carries different consumed-ID
counters. Divergent tips now reconcile the known point/line/angle counters across
all successful candidates before comparing their contents. Each candidate already
includes its base and both tips, so the resulting maxima cover every best base
and both tips. Target order and all-base provenance/version guards remain intact.

This closes one bounded gap in automatic differing-base reconciliation. Every
base must still produce a clean merge, and authored candidate results must still
agree. Unknown authored fields, conflicting ancestor edits and unsupported
structural changes retain existing conservative behavior. The converged-tip
shortcut and explicit whole-topology choices are unchanged. Accepted v0.8 status
is unchanged; this is not recursive ancestor reconciliation.

Regression tests cover both directions, separate point/line/angle maxima,
ancestor counters above both tips, persisted provenance and stale versions for
either best base. The focused Chromium script consumes IDs in both ancestors,
rebuilds lower tip counters through JSON import, merges independent coordinates
and title, restarts/reopens, and checks order, provenance and fresh allocation
above every ancestor counter.

Validation and independent review evidence:
`/workspace/ctrlnet-v08/cn_post_v08_consensus_allocators/`.

Validation: 779 passed, 1 skipped, 2 xfailed, 8 warnings in 53.02s.
Author and independent Chromium runs PASS. Independent review PASS with 367
focused tests and three additional three-best-base probes. New six-case regression
failed before the implementation and passes afterward. Demo SQLite SHA256 remains
`fa597f57b5952fa603b9464550c5d72e9c7c2b6bd4efc48c8281692b84a204f6`.
