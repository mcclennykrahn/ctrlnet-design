# Post-v0.8: converged-tip allocator preservation

One bounded gap: differing-content criss-cross best bases with equivalent tips
now retain the maximum known point, line and angle counters across every best
base and both tips. Previously the converged-tip shortcut copied the target and
could lose consumed IDs after a JSON import reset both tips' counters.

The change preserves target topology and presentation order, existing all-base
provenance/version guards, and input snapshots. Invalid known counters on this
path require a whole-topology choice. Unknown authored content is not replayed
from ancestors. Recursive competing-ancestor reconciliation remains unsupported;
accepted v0.8 status and production maturity claims are unchanged.

Regression tests cover both directions and separate counter maxima from both
bases, persisted reopen, unchanged geometry and parent snapshots. Focused
Chromium exercises real add/delete consumption, import counter reset, converged
tips, merge controls, server restart/reopen, provenance/order and fresh allocation.

Validation: 781 passed, 1 skipped, 2 xfailed, 8 warnings in 59.48s.
Author focused Chromium PASS. Independent review PASS: 40 focused tests, seven
probes (invalid counters, unknown content, both stale-base guards), prepatch
regression failure confirmation and separate Chromium restart/reopen. Evidence is retained under
`/workspace/ctrlnet-v08/cn_post_v08_converged_allocators/`.
Initial browser run failed because its expected point used the loop index after
the fixture was changed to converge; the assertion was corrected and rerun.
Sample SQLite SHA256 remains
`fa597f57b5952fa603b9464550c5d72e9c7c2b6bd4efc48c8281692b84a204f6`.
