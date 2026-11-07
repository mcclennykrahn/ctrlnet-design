# Bounded network settings conflict choices

With unchanged structure and a unique merge base, competing network settings
now expose a `network` target/source choice. The choice selects the entire
settings object, including observation selections, grade and display settings;
it preserves independently merged existing-point fields and measured line
overrides. Point conflicts can be resolved alongside the network choice.
The UI labels this as a whole-settings choice. Resolution provenance is saved.

Missing, invalid or extra choices are rejected before saving; stale previews
remain rejected. Structural and unhandled-field conflicts still fall back to
whole-topology choices. Ambiguous criss-cross bases remain unsupported. This is
one bounded conflict-resolution improvement, not completion of general topology
merge. Accepted v0.8 and the package version remain unchanged.

Validation and independent review are recorded under
`/workspace/ctrlnet-v08/cn_post_v08_network_choices/`. The repository `.venv`
lacked pytest; validation uses the existing `/tmp/cn-post-v08-venv` interpreter
and installed Chromium. Preexisting deletions and runner dirt are excluded.

Stage validation: **411 passed, 1 skipped, 2 xfailed**, 8 warnings in 25.49s.
Focused HTTP/Chromium merge, restart and reopen: **PASS**. Independent review:
**PASS**, including 22 independently rerun scenario tests. The demo database
SHA256 remains `fa597f57b5952fa603b9464550c5d72e9c7c2b6bd4efc48c8281692b84a204f6`.
