# Independent title and angle choices across differing-content bases

A saved-scenario merge retains separate title and whole-angle target/source
choices when every best base reports those same two conflicts and all four
joint resolution outcomes agree across every base. The existing all-base
planner validates and replays both choices. Independent supported edits,
target stable-ID list order, recomputed geometry, known allocator maxima,
version guards and provenance keep their existing guarantees.

This stage adds only title plus one angle. Title plus point/line, additional
item/network conflicts, differing conflict IDs, disagreeing outcomes and unknown
authored fields retain conservative whole-topology choices. Recursive ancestor
reconciliation remains unsupported. Accepted v0.8 status is unchanged.

Full pytest: 998 passed, 1 skipped, 2 xfailed, 8 warnings in 149.29s.
The skipped optional pyproj check and two existing thesis xfails remain.
Focused Chromium exercised target title plus source angle, merge, server
restart and reopen, retained independent coordinates, order and provenance,
and reported no page errors. The installed Chromium executable was supplied
through CHROMIUM_EXECUTABLE; the default Playwright download was unavailable.

Tests cover both merge directions, angle names and references, all four
choices, immutable parents, counters, stale bases, and rejection when any
single joint outcome disagrees. Explicit guards retain whole-topology
conflicts for unsupported mixed combinations.

Stage evidence and independent review:
`/workspace/ctrlnet-v08/cn_post_v08_consensus_title_angle_choice/`.

Independent review PASS: 118 focused tests, latest 29-test suite, 8 external
probes and a separate Chromium restart/reopen run. Review reproduced prepatch
whole-topology rejection and verified a real three-best-base DAG with reordered
target lists, ancestor-high counters, provenance and the third-base stale guard.
