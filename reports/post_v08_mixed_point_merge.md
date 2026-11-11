# Mixed isolated-point additions and deletions

Saved-scenario merges now combine isolated point additions with unchanged isolated
point deletions, including changes on the same branch. Deletions are checked
against all three snapshots before additions and surviving fields use the existing
merge rules. Target survivor order remains intact; source-only additions append in
source order. The point allocator retains all three high-water marks.

Delete-versus-edit, references to removed or newly added points, competing added
IDs/names, unknown authored fields, and new lines/angles still require conservative
whole-topology choices. Ambiguous criss-cross bases remain unsupported. No ID or
name remapping is introduced. Accepted v0.8 is unchanged.

Validation: 506 passed, 1 skipped, 2 xfailed, 8 warnings in 52.40s. Focused HTTP
and Chromium preview/merge, restart/reopen, order, dual-parent provenance, deleted
point absence and fresh allocation checks passed. Initial bundled-browser launch
failed; rerun used the installed Chromium. Stage artifacts and independent review:
`/workspace/ctrlnet-v08/cn_post_v08_mixed_point_merge/`.

The sample database SHA256 remains
`fa597f57b5952fa603b9464550c5d72e9c7c2b6bd4efc48c8281692b84a204f6`.
Prior evidence and unrelated worktree dirt are preserved. No cc-gins changes.
