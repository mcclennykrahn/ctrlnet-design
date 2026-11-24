# Independent title and line choices across differing-content bases

Saved-scenario merge now retains separate title and whole-line target/source
choices when every best base reports those same two conflicts and all four
joint outcomes agree across every base. This extends the existing bounded
consensus allowlist; it uses the existing all-outcome validation and replay.
Supported independent edits, target stable-ID order, known allocator maxima,
all-base version guards and provenance retain their existing behavior.

Only title plus one line is added. Title plus point, extra item/network conflicts,
differing conflict IDs, disagreeing or unsafe outcomes and unknown authored
fields remain conservative whole-topology conflicts. Recursive ancestor
reconciliation remains unsupported. Accepted v0.8 status is unchanged.

Full pytest: 1027 passed, 1 skipped, 2 xfailed, 8 warnings in 131.06s.
Focused tests exercise both directions, line names and measured overrides,
all four choices, immutable ancestors, known allocator maxima, stale bases,
and rejection when any single joint outcome disagrees.
Chromium exercised target title plus source line, merge, restart and reopen,
independent coordinates, order, provenance and no page errors, using installed
Chromium through CHROMIUM_EXECUTABLE.

Evidence: `/workspace/ctrlnet-v08/cn_post_v08_consensus_title_line_choice/`.

Independent review found an unsafe alternate endpoint outcome: a whole-line
choice could collide with another line's one-sided endpoint edit even though
both tips were valid. The new title/line route now checks undirected endpoint
pair uniqueness in every joint outcome. Four regression cases cover either
branch and both merge directions; even choosing the safe outcome cannot bypass
the conservative whole-topology fallback. This guard is scoped to the new route.

Independent re-review PASS: 96 focused tests, 11 external adversarial probes,
and a separate Chrome merge/restart/reopen run. The review reproduced prepatch
rejection, checked real three-best-base consensus with all four choices,
all-counter maxima, reordered lists, provenance, immutable parents and every-base
stale guards, and confirmed safe endpoint choices and unsafe alternate fallback.
