# Selected angle deletion merge

One bounded post-v0.8 topology gap: unchanged selected angle deletions merge by stable ID. A retaining branch must preserve the base membership of each deleted angle in both observed/added selections; a deleting branch must clear it. Deleted IDs are removed before the remaining whole-network merge, so neither network choice can restore a dangling selection. Target order, allocator high-water marks, independent edits and dual-parent provenance remain preserved.

Delete-versus-edit, selection changes on retained deleted angles, dangling references, referenced-point deletions and unknown authored fields remain conservative whole-topology conflicts. Existing addition restrictions and unsupported ambiguous merge bases remain unchanged. Accepted v0.8 is unchanged; no production maturity claim.

Validation: full pytest **660 passed, 1 skipped, 2 xfailed, 8 warnings in 333.27s** (optional pyproj unavailable). Independent review reran 271 scenario-tree tests plus four external probes: **275 passed**. Observed-angle author Chromium and added-angle independent Chromium both PASS.

Validation evidence and independent review: `/workspace/ctrlnet-v08/cn_post_v08_selected_angle_delete`. Coverage includes target/source/both deletions, observed/added/both memberships, allocator/order/persistence, unsafe selection edits, network choices and referenced-point deletions. Focused HTTP/Chromium runs exercise observed-angle and added-angle selections, merge, restart/reopen, selection cleanup, generated angle counts, coordinates, order, parents and fresh allocation. Initial fixture expectation failures and missing bundled-browser failure are retained externally alongside final results.

Sample SQLite SHA256 matches HEAD: `fa597f57b5952fa603b9464550c5d72e9c7c2b6bd4efc48c8281692b84a204f6`. Prior evidence and unrelated worktree dirt preserved; no cc-gins changes.
