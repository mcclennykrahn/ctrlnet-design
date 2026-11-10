# Bounded isolated-point deletion merge

Saved scenarios can combine deletion of isolated points with supported edits to
surviving objects. The removed points must have no line or angle references in
any of the three snapshots. A surviving copy on the other branch must match the
base exactly, and deleted points with unknown authored fields are excluded.
Both branches may delete the same point. Surviving points retain target order;
the point allocator retains all three snapshots' high-water marks.

Delete-versus-edit, referenced-point deletion, mixed additions/deletions,
line/angle additions, competing added IDs/names and unknown authored fields
remain conservative whole-topology conflicts. Ambiguous criss-cross bases remain
unsupported. Accepted v0.8 is unchanged; no production maturity claim.

Validation includes API merge/reopen, parent immutability, target order, allocator
preservation, conservative boundary cases and missing-choice atomicity. Focused
Chromium uses HTTP deletion and coordinates, merge preview/apply, process restart,
UI reopen and subsequent fresh point allocation. Evidence and independent review:
`/workspace/ctrlnet-v08/cn_post_v08_isolated_point_delete/`.

Final pytest: 499 passed, 1 skipped, 2 xfailed, 8 warnings in 106.03s.
Independent review PASS: 110 focused tests and separate Chromium rerun PASS;
first review browser restart timeout retained in evidence. Sample database hash
matches HEAD. Prior evidence and unrelated worktree dirt preserved.
