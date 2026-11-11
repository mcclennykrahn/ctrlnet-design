# Bounded unselected line addition merge

Saved-scenario merges can combine unselected, unmeasured line additions between
points present in all three snapshots with supported survivor edits and deletions.
Stable IDs define identity. Identical authored additions with the same ID coalesce;
distinct additions retain target order followed by source-only additions. Derived
length and azimuth are recomputed after merging coordinates. The line allocator
retains all three high-water marks.

Competing added IDs/names, duplicate unordered endpoint pairs (including collisions
with survivor endpoint edits), selections on added lines, measured overrides,
unknown added-line fields, self edges, and references to added/deleted points
retain whole-topology conflict choices. Existing conservative deletion boundaries,
angle additions and ambiguous criss-cross bases remain unchanged. This is a
bounded post-v0.8 improvement; accepted v0.8 and product maturity claims are unchanged.

Tests cover directional and identical/distinct additions, persistence and parent
immutability, order, allocators, mixed supported deletions, point conflict choices
and conservative boundaries. The focused HTTP/Chromium check creates divergent
addition/coordinate branches, merges through the UI, restarts/reopens and verifies
recomputed geometry, dual parents and fresh allocation. Evidence is retained at
`/workspace/ctrlnet-v08/cn_post_v08_line_addition/`.

Independent review initially found a duplicate-edge invariant violation; the fix
checks the combined endpoint pairs after survivor merges, with regressions for
existing edges, competing additions and endpoint edits. The first browser fixture
attempt tried to move a fixed point; the fixture now uses a movable point.

Final validation: 548 passed, 1 skipped, 2 xfailed, 8 warnings in 35.80s.
Independent review PASS: 159 focused tests and Chromium rerun. Sample database
SHA256 matches HEAD. Prior evidence and unrelated worktree changes preserved.
