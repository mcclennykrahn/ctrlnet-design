# Bounded whole-angle choices across differing-content bases

A saved-scenario merge retains one whole-angle target/source choice when every
best base reports the same angle conflict and both resolution outcomes agree
across every base. Names and ordered references stay together. Independent
supported edits combine, target stable-ID list order is retained, derived angle
values are recomputed, and known allocator maxima include every best base and
both tips. Applying the choice replays the all-base planner, preserving its
allocator and provenance guarantees.

Multiple angle conflicts, mixed item/title/network conflicts, disagreeing
outcomes, unsupported structures and unknown authored fields still require a
whole-topology choice. Recursive ancestor reconciliation remains unsupported.
Accepted v0.8 status and product maturity claims are unchanged.

Validation and independent review evidence are recorded under
`/workspace/ctrlnet-v08/cn_post_v08_consensus_angle_choice/`. Focused regressions
cover angle names and references, both choices and directions, derived geometry,
immutable parents, allocator maxima, provenance, invalid choices, both-outcome
checks and stale previews. Chromium exercises preview/choice/merge followed by
server restart and reopen. No cc-gins changes are part of this stage.

Validation: 967 passed, 1 skipped, 2 xfailed, 8 warnings (full pytest).
Independent review PASS: 85 focused tests plus the latest 18-test angle suite,
external three-base allocator/order/provenance/stale and conflict safety probes,
prepatch reproduction, and an independent Chromium restart/reopen run.
