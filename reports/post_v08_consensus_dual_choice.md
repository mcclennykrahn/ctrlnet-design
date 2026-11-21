# Independent title and network choices over differing merge bases

Saved scenarios with differing-content best bases can now retain simultaneous
editor-title and whole-network choices when every base reports exactly those
two conflicts and produces the same topology for each of the four independent
choice combinations. The existing title and network controls require both choices.
The merge replans against every base with those choices, retaining independent
geometry edits, target order, allocator high-water marks and provenance.

A clean result at one base and conflicts at another, differing candidate results,
additional field conflicts, invalid counters and unknown authored edits remain
whole-topology conflicts. Recursive reconciliation of competing ancestor edits
remains unsupported. This closes one bounded gap; accepted v0.8 and the package
version remain unchanged.

Validation and independent review evidence are recorded under
`/workspace/ctrlnet-v08/cn_post_v08_consensus_dual_choice/`. The browser check uses
real HTTP branches, both UI choices with opposite outcomes, restart and reopen,
and verifies independent geometry, saved title/network, order and provenance.
Unrelated repository dirt and prior acceptance evidence are preserved.

Final validation: **926 passed, 1 skipped, 2 xfailed**, 8 warnings in 88.05s.
Author and independent Chromium checks: **PASS**. Independent review: **PASS**,
77 tests/probes including selected-deletion combinations, every-outcome consensus
guards and a prepatch comparison. Thirteen review checks are retained as tests.
Sample SQLite SHA256: `fa597f57b5952fa603b9464550c5d72e9c7c2b6bd4efc48c8281692b84a204f6`
(matches HEAD). An initial browser attempt used a missing executable; the passing
runs used installed Chromium. No product changes followed independent review.
