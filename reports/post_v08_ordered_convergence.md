# Reordered authored-tip convergence across differing scenario bases

Differing-content criss-cross merge bases now accept tips with the same authored
point/line/angle content when those lists differ only in stable-ID presentation
order. This includes matching structural deletions that the ordinary field merge
cannot replay safely. The merged snapshot retains target order and maximum valid
known allocator counters from every best base and both tips. Saved parents and
all-base version/provenance guards remain unchanged.

The change reuses the stable-ID equivalence comparison already used for ancestor
classification. It compares copies, validates unique nonempty string IDs and
retains unknown authored fields in comparison. Actual authored differences,
unknown-field differences and invalid known counters still conflict. It does not
implement recursive reconciliation of competing ancestor edits or change v0.8
acceptance.

The parameterized API regression covers both merge directions, reordered and
unchanged list order, structural deletion, known counter drift, unknown authored
and counter fields, invalid counters, stale bases, parent immutability and target
order after reopen. The structural reordered case failed before the change.
Focused Chromium exercises saved criss-cross branches with differing bases,
matching deletions and reordered source lists, preview/merge, restart/reopen,
provenance and fresh allocation. JSON import supplies list reordering because
there is no list-order editor control. The default Playwright bundle was absent;
the installed Google Chrome completed the browser check.

Validation and independent review evidence:
`/workspace/ctrlnet-v08/cn_post_v08_ordered_convergence/`.

The benchmark smoke test requires a repository-local `.venv/bin/python` and a
source import path for its subprocess. Validation temporarily links the shared
interpreter at that path and exports `PYTHONPATH=src`; the link is removed after
testing. Initial runs without these environment prerequisites are retained in
the stage evidence. No benchmark or packaging implementation was changed.

Final validation: 873 passed, 1 skipped, 2 xfailed, 8 warnings in 115.28s (0:01:55). Focused Chromium PASS (author and independent);
independent review PASS with 71 focused tests and 24 adversarial probes.
Demo SQLite SHA matches HEAD. Unrelated worktree dirt and prior evidence preserved.
