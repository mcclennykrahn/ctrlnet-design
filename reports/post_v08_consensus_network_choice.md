Differing-base network choice consensus
======================================

This stage adds one narrow merge case: differing-content best bases can offer
an independent whole-network settings choice when every base reports only the
network conflict and every base produces the same topology for **both** choices.
The merge recomputes the selected consensus inside the existing write transaction,
retaining all-base version guards, provenance, target order and allocator maxima.
Structural selection filtering is preserved; the raw retaining-branch network is
never copied over a merged deletion.

Other field conflicts, mixed title/network conflicts, ambiguous ancestor edits,
unknown authored fields and unsafe structural merges retain conservative
whole-topology choices. Recursive ancestor reconciliation remains unsupported.
v0.8 acceptance and product maturity claims are unchanged.

Validation evidence is under
`/workspace/ctrlnet-v08/cn_post_v08_consensus_network_choice/`.
Focused API tests cover both directions and choices, invalid resolutions,
all-base stale guards, parent immutability, allocator maxima, independent point
edits, conservative guards and deleted selected lines. Chromium exercises the
network source choice through the UI, server restart/reopen, independent point
edits, order, allocator counters, provenance and tree display.

The first full-suite run reached 890 passed with one environment failure because
the benchmark test hardcodes `.venv/bin/python`. An ignored local symlink to the
existing `/workspace/venvs/ctrlnet` environment supplies that expected path.
The sample SQLite SHA-256 remains
`fa597f57b5952fa603b9464550c5d72e9c7c2b6bd4efc48c8281692b84a204f6`.
Prior evidence and unrelated working-tree dirt are preserved; cc-gins is untouched.

Final validation: pytest 895 passed, 1 skipped, 2 xfailed, 8 warnings in 88.54s.
Author focused suite: 22 passed. Author and independent Chromium runs: PASS.
Independent review: PASS, 65 focused tests/probes including 11 external adversarial
probes and isolated prepatch regression confirmation. No blocking findings.
