# Bounded network-settings scenario merge

With a unique common ancestor and unchanged point/line/angle structure, a saved
branch's network settings now combine with the other branch's existing-point
fields or measured line overrides. The entire `network` object is one authored
unit, including observation selections, grade and display settings. Presence
is compared explicitly; the selected object is copied without mutating parents.

Competing network edits remain a whole-topology conflict, even when different
settings changed. Projection, structural changes and other unhandled fields
remain conservative. Derived geometry is refreshed after automatic combination.
No UI choice or API payload changes are required. Existing stale-preview checks,
atomic saves and dual-parent provenance remain in place.

This closes one bounded remaining-field portion only. Structural/general field
merges, per-point choices and ambiguous criss-cross bases remain open. Accepted
v0.8 and the package version are unchanged; no production maturity claim is made.

Validation uses the scenario API tests and a focused real HTTP/Chromium merge,
server restart and reopen. Full results and independent review are recorded in
`/workspace/ctrlnet-v08/cn_post_v08_network_merge/`. The initial test interpreter
lacked pytest and the first browser attempt lacked Playwright's default browser;
reruns use the existing test venv and installed Chromium. These attempts are
retained in stage artifacts. Preexisting repository dirt is excluded.

Stage result: **406 passed, 1 skipped, 2 xfailed**, 8 warnings in 29.93s.
Focused Chromium: **PASS**. Independent review: **PASS**, with independent
focused regression (17 passed). Demo SQLite SHA256 remains
`fa597f57b5952fa603b9464550c5d72e9c7c2b6bd4efc48c8281692b84a204f6`.
