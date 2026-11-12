# Bounded measured line addition merge

Unselected line additions between distinct points common to all three saved
snapshots now retain authored length and/or azimuth overrides. Identical authored
additions coalesce by stable ID; competing measurements or keep flags conflict
as whole topology. Unkept values are ignored for comparison and recomputed after
merging coordinates. Target order and allocator high-water marks are preserved.

Selection, unknown fields, competing IDs/names, duplicate endpoint pairs and
references to new/deleted points remain conservative. Ambiguous merge bases
remain unsupported. This is one bounded post-v0.8 improvement; accepted v0.8
and the other open gaps are unchanged.

Validation: 580 passed, 1 skipped, 2 xfailed, 8 warnings in 37.04s. Focused
scenario suite: 191 passed. Chromium exercises a store-seeded measured addition
(the editor has no measurement editing endpoint), HTTP coordinate edits, UI
preview/merge, restart/reopen, preserved measured length, recomputed azimuth,
target order, dual parents and fresh allocation. The fixture was corrected to
use persisted state instead of public display fields and to inspect the private
keep flag in persisted metadata. Chrome is supplied explicitly because the
Playwright bundled browser is absent. Sample SQLite SHA256 matches HEAD.
Independent review and stage evidence are retained under
`/workspace/ctrlnet-v08/cn_post_v08_measured_line_addition/`.
