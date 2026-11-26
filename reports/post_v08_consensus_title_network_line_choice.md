# Independent title, network and line choices across differing merge bases

This stage closes one bounded scenario-merge gap: a competing editor title,
whole network and one whole existing line can retain three independent choices
when every differing-content best base reports exactly those conflicts and all
eight joint outcomes agree across every base. Every outcome must have unique
undirected line endpoint pairs, including outcomes the user did not request.
Otherwise the merge retains the conservative whole-topology choice.

The existing whole-line merge keeps names, endpoints and measured overrides
together. Existing target ordering, allocator high-water marks, all-base version
guards, immutable parents and merge provenance continue to apply. Extra item
conflicts, unknown authored fields and recursive ancestor reconciliation remain
unsupported. Accepted v0.8 and package version are unchanged.

Validation covers all eight choices in both merge directions for line names,
measured lengths and endpoint changes with measured overrides, disagreement in
each alternate outcome, duplicate alternate endpoint outcomes, stale bases,
invalid resolutions and conservative extra conflicts. Focused Chromium checks
three independent UI choices, real HTTP persistence and restart/reopen.

Final results and independent review are recorded under
`/workspace/ctrlnet-v08/cn_post_v08_consensus_title_network_line_choice/`.

Result: **1257 passed, 1 skipped, 2 xfailed**, 8 warnings in 182.75s.
Focused Chromium **PASS**; independent review **PASS** (110 focused tests,
16 endpoint cases and two separate probes passed). Sample SQLite matches HEAD.
Pre-existing documentation deletions and runner artifacts are excluded.
