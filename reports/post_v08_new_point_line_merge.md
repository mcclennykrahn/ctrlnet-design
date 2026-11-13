# Line additions with new points

One bounded post-v0.8 topology gap: selected or unselected line additions may reference compatible newly added points. Base endpoints must survive both branches, and each line must reference points present in its author branch. The recursive point merge validates new point IDs, names and authored fields before added lines are restored. Measured overrides, whole-network selection choices, target order and allocator high-water marks retain their existing rules.

Conflicting new points, duplicate endpoint pairs, deleted base endpoints, dangling references and unknown authored fields remain whole-topology conflicts. Angle additions involving new points and ambiguous merge bases remain unsupported. Accepted v0.8 and production-readiness claims are unchanged.

Validation evidence, independent review and initial failed attempts are preserved under `/workspace/ctrlnet-v08/cn_post_v08_new_point_line`. The focused HTTP/Chromium flow exercises a selected measured line with a new endpoint, independent coordinate edit, merge, restart/reopen, derived azimuth, selection, target order, dual parents and fresh allocation. Pytest covers both merge directions and observed/added/unselected lines, plus collision and unsafe-reference boundaries.

Sample SQLite SHA256 matches HEAD: `fa597f57b5952fa603b9464550c5d72e9c7c2b6bd4efc48c8281692b84a204f6`. Prior evidence and unrelated worktree dirt preserved; no cc-gins changes.

Validation: full pytest **670 passed, 1 skipped, 2 xfailed, 8 warnings in 100.07s** with `PYTHONPATH=src` (optional pyproj unavailable). Independent review: **285 passed**, including external probes for shared new points, both endpoints new, network choices, input immutability, order and allocator preservation; separate final Chromium run PASS. Initial environment and fixture failures remain in the external evidence directory.
