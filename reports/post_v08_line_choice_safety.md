# Added-line merge choice safety

One bounded post-v0.8 gap: a line addition can be individually valid yet collide with an existing line's alternate whole-line conflict resolution. Previously preview checked only the default merged topology. Choosing the other line could then fail during merge instead of providing a usable resolution.

Preview now checks added line names and undirected endpoint pairs against surviving existing lines in both branches, matching the conservative boundary already used for angle additions. Any potential collision falls back to an explicit whole-topology target/source choice. This intentionally also rejects compatible-looking defaults when another branch choice would collide. Existing field merge, target ordering, allocator and selection rules are unchanged. Ambiguous merge bases and the other documented structural boundaries remain unsupported; v0.8 acceptance is unchanged.

Twelve HTTP regressions cover forward/reversed endpoint pairs and name collisions, both branch orientations and both whole-topology resolutions, rejection of a stale per-line resolution without writes, exact saved topology and reopen. Focused Chromium exercises valid saved branches, whole-topology preview and target choice, selected measured addition, restart/reopen, unique endpoints, allocator and dual-parent provenance.

Validation and independent review evidence, including failed fixture/browser attempts, are under `/workspace/ctrlnet-v08/cn_post_v08_line_choice_safety`. No cc-gins changes or release-readiness claims.

Final validation: 712 passed, 1 skipped, 2 xfailed, 8 warnings in 71.43s. Independent review PASS: 323 scenario-tree tests, five probes and separate Chromium run. Sample SQLite SHA256 unchanged: `fa597f57b5952fa603b9464550c5d72e9c7c2b6bd4efc48c8281692b84a204f6`.
