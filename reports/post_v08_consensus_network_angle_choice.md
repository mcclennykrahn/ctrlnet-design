# Independent network and angle consensus choices

This bounded post-v0.8 change retains independent whole-network and one whole-angle choice across differing-content best bases. Every base must report exactly the same network and angle conflicts, and all four joint outcomes must agree across every base. Existing target order, all-base allocator maxima, merge provenance and version guards remain in use. Angle values are recomputed on reopen.

Network plus line, extra item conflicts, title/network/angle triples, unknown authored fields and recursive ancestor reconciliation remain conservative whole-topology conflicts. Accepted v0.8 status is unchanged.

Validation: 1089 passed, 1 skipped, 2 xfailed, 8 warnings in 150.50s. Author focused tests: 43 passed. Independent review: PASS with 75 focused tests, seven external probes including three best bases, all four outcomes, allocator/provenance preservation, mismatched conflict signatures and prepatch rejection. Author and independent Chrome merge/restart/reopen: PASS. Evidence: `/workspace/ctrlnet-v08/cn_post_v08_consensus_network_angle_choice`. Sample SQLite matches HEAD; unrelated worktree files are excluded.
