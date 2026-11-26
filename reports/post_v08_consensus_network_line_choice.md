# Independent network and line consensus choices

This bounded post-v0.8 change retains independent whole-network and one whole-line choices across differing-content best bases. Every base must report exactly the same two conflicts, and all four joint outcomes must agree across every base. Every offered outcome must have unique undirected endpoint pairs, including alternate line resolutions. Target order, all-base/tip allocator maxima, merge provenance and version guards remain in use.

Additional item conflicts, title/network/line triples, unknown authored fields and recursive ancestor reconciliation remain conservative whole-topology conflicts. Accepted v0.8 status is unchanged.

Validation and independent review are recorded under `/workspace/ctrlnet-v08/cn_post_v08_consensus_network_line_choice`. The focused browser check exercises real observed-edge selections, independent line choices, server restart and reopening. Existing unrelated worktree deletions and untracked files are excluded.

Final validation: 1120 passed, 1 skipped, 2 xfailed, 8 warnings in 155.25s. Focused Chrome merge/restart/reopen: PASS. Independent review: PASS, 89 focused tests plus two probes for prepatch rejection and mismatched conflict IDs. Sample SQLite SHA matches HEAD.
