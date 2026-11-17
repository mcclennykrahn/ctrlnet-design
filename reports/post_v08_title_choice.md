# Independent editor-title conflict choices

Competing editor project titles now offer a `title` target/source conflict choice,
retaining supported independent geometry, structure and network changes. Scenario
snapshot names remain separate. Presence and explicit null remain distinct.
Unsupported authored fields and structural edits still require whole-topology
choices. Equivalent-content multiple bases support title choices with all-base
version/provenance guards. Differing-content bases still require converged tips
or equivalent conflict-free results from every base; a competing title does not
introduce field choices against an arbitrary ancestor. Recursive reconciliation
of competing ancestor edits remains unsupported.

Validation and independent review evidence live under
`/workspace/ctrlnet-v08/cn_post_v08_title_choice/`. Focused HTTP tests cover both
choices, structural recursion, combined point/title conflicts, invalid resolution
atomicity, presence, unknown fields, immutability and multiple-base guards. The
Chromium check exercises the actual title control, both independent point edits,
restart/reopen, allocator/order and parent/base provenance. Accepted v0.8 and the
broader deployment/CRS gaps are unchanged.

Validation: **766 passed, 1 skipped, 2 xfailed**, 8 warnings in 54.73s.
Author and independent Chromium checks passed, as did the prior differing-base
title e2e. Independent review PASS: 377 focused tests and 3 probes. The initial
full run had one environment failure because a benchmark hardcodes the absent
`.venv/bin/python`; a temporary link to the existing environment fixed that
execution path for the passing rerun. Initial evidence is retained externally.
The demo SQLite SHA256 remains
`fa597f57b5952fa603b9464550c5d72e9c7c2b6bd4efc48c8281692b84a204f6`.
