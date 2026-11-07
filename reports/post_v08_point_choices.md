# Bounded per-point scenario conflict choices

With unchanged point/line/angle structure and a unique merge base, competing
edits to an existing point now produce a `point:<id>` conflict. Each choice
selects the entire target or source point, including its name, fixed flag and
coordinate tuple. Independent edits on other points, network settings, measured
line overrides and GNSS observations retain their existing merge behavior.

The existing browser conflict controls display each point ID and require an
explicit target/source choice. Missing, invalid and extra choices are rejected;
stale previews remain rejected and saved provenance records the choices.
Derived geometry is refreshed after applying the selected points.

Structural changes and conflicting non-point topology units retain the existing
whole-topology conflict choices. No field-by-field conflict selection, structural
merge or ambiguous criss-cross base support is added. Accepted v0.8 is unchanged;
this is one bounded post-v0.8 improvement, with no production maturity claim.

Validation and independent review are recorded under
`/workspace/ctrlnet-v08/cn_post_v08_point_choices/`.

Stage validation: **408 passed, 1 skipped, 2 xfailed**, 8 warnings in 27.63s.
Focused Chromium restart/reopen: **PASS**. Independent review: **PASS**, with
19 independently rerun focused tests. Demo SQLite SHA256 is unchanged at
`fa597f57b5952fa603b9464550c5d72e9c7c2b6bd4efc48c8281692b84a204f6`.
