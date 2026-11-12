# Bounded unselected angle addition merge

Saved-scenario merges can combine unselected angle additions whose station,
backsight and foresight are distinct points present in all three snapshots with
supported survivor edits, line additions and isolated deletions. Stable IDs define
identity; identical authored additions coalesce. Target order precedes source-only
additions, derived angle values are recomputed, and all three angle allocator
high-water marks are preserved.

Competing added IDs/names, duplicate ordered reference triples (including survivor
reference edits), selections on added angles, unknown added-angle fields, repeated
references and references to new/deleted points retain whole-topology conflicts.
Selection safety is checked before offering network conflict choices. Existing
conservative boundaries and ambiguous criss-cross merge-base rejection remain.
This is one bounded post-v0.8 improvement; accepted v0.8 is unchanged.

Regression tests cover directional, identical and distinct additions, persistence,
parent immutability, target order, allocators, mixed deletions, point choices and
conservative boundaries. The HTTP/Chromium check creates divergent addition and
coordinate branches, merges through the UI, restarts/reopens, and checks derived
geometry, dual parents and fresh allocation. Stage evidence is retained at
`/workspace/ctrlnet-v08/cn_post_v08_angle_addition/`.

Independent review initially found that a nondefault whole-angle choice could
collide with an added name/reference triple after a valid preview. The fix checks
both survivor alternatives before offering choices; two API regressions verify
whole-topology preview and successful explicit resolution. Initial review evidence
is preserved with the final review.

Final pytest: 567 passed, 1 skipped, 2 xfailed, 8 warnings in 37.89s.
The initial suite run had a benchmark subprocess import failure because the local
`.venv/bin/python` symlink loses its environment prefix. Validation passed with
explicit source and installed-package PYTHONPATH; no product change was made for
that environment issue. Focused Chromium merge/restart/reopen passed, including
an independent rerun. Sample SQLite SHA256 matches HEAD; prior evidence and
unrelated worktree dirt are preserved.
