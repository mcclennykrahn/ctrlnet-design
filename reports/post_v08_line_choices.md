# Bounded whole-line scenario merge choices

Competing measured length/azimuth overrides on existing lines now offer an
explicit target/source whole-line choice when all three saved structures match.
The chosen line includes both override flags and values; unkept geometry is
recomputed from the merged points. Independent point, other-line and network
edits survive, and line choices can coexist with point and network choices.
The browser labels the choice as a whole line, including its stable ID.

Existing exact resolution-key validation, stale preview rejection, transactional
save and dual-parent provenance remain in force. Structural changes and other
unsupported authored fields retain whole-topology choices. Ambiguous criss-cross
merge bases remain unsupported. This is one bounded post-v0.8 improvement;
accepted v0.8 status and production-readiness claims are unchanged.

Validation evidence is under `/workspace/ctrlnet-v08/cn_post_v08_line_choices`:
full pytest, independent focused review, and real Chromium explicit choice,
server restart and reopen. The browser seeds measured branches through the store
because there is no measured-override editing endpoint; its independent point
edit, preview, merge and reopen use HTTP/UI. Initial public-state seeding failure
is retained separately; corrected internal saved-state harness passes.

The sample SQLite SHA256 remains
`fa597f57b5952fa603b9464550c5d72e9c7c2b6bd4efc48c8281692b84a204f6`.
Prior evidence, unrelated worktree deletions and runner files are preserved.
No other project repository was changed.
