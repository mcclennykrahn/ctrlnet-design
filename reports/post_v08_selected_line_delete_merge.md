# Selected line deletion merge

One bounded post-v0.8 topology gap: unchanged selected line deletions now merge by stable ID. A retaining branch must preserve each deleted line's base selection membership; a deleting branch must clear it. The merge removes those references before merging the remaining network object, so either network choice stays valid. Target order, allocator high-water marks, independent edits and dual-parent provenance remain preserved.

Delete-versus-edit, selection edits on the retained line, dangling references, referenced-point deletions, unknown authored fields and selected angle deletions remain conservative whole-topology conflicts. Ambiguous bases remain unsupported. Accepted v0.8 is unchanged; this is not a production maturity claim.

Validation: full pytest **640 passed, 1 skipped, 2 xfailed, 8 warnings in 39.79s** (the skip is unavailable optional pyproj). Focused HTTP/Chromium PASS for observed-edge selection; independent review PASS with 252 focused tests and a separate added-edge selection Chromium run. Both browser runs verify merge, restart/reopen, selection cleanup, generated distance count, coordinate edits, target order, dual parents and fresh allocation.

Validation and independent review evidence: `/workspace/ctrlnet-v08/cn_post_v08_selected_line_delete`. The independent reviewer found a reference-stripping issue that could hide a referenced-point deletion; the final guard checks original references and includes target/source/both regression cases. Initial evidence is retained externally.

The sample SQLite SHA256 matches HEAD: `fa597f57b5952fa603b9464550c5d72e9c7c2b6bd4efc48c8281692b84a204f6`. Prior evidence and unrelated worktree dirt are preserved; no cc-gins changes.
