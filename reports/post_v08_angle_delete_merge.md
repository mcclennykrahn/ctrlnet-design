# Bounded unchanged-angle deletion merge

Saved-scenario merges can combine deletion of an otherwise unchanged, unselected
existing angle with supported survivor edits and existing isolated-point/line
structural merges. Stable IDs determine identity; survivors retain target order,
and the angle allocator retains all three snapshots' high-water marks. Derived
angle values do not count as authored edits.

Either branch retaining an observation selection, delete-versus-edit (including
name/reference/presence changes), unknown deleted-angle fields and duplicate IDs
remain conservative whole-topology conflicts. Removing an angle cannot hide a
referenced-point deletion. Angle/line additions and ambiguous criss-cross merge
bases remain unsupported. Accepted v0.8 is unchanged; no production maturity claim.

Focused HTTP/Chromium validation covers divergent branches, preview/merge,
restart/reopen, survivor order, dual parents and fresh angle allocation. The
browser fixture strips public angle display fields before JSON import; unknown
snapshot fields remain outside the bounded automatic path. Independent review
caught a referenced-point boundary leak, fixed before commit with a regression.
Evidence, including initial fixture and browser failures, is retained under
`/workspace/ctrlnet-v08/cn_post_v08_angle_delete/`.

Final validation: 529 passed, 1 skipped, 2 xfailed, 8 warnings in 35.29s.
Independent review PASS: 140 focused tests and Chromium rerun. Sample database
SHA256 matches HEAD. Prior evidence and unrelated worktree dirt preserved.
