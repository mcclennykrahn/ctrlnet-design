# Bounded existing-line endpoint merge

Existing-line endpoint changes can combine with independent existing-object
edits by stable ID. A changed endpoint pair makes that entire authored line
indivisible: endpoints, name and measured overrides travel together. Competing
endpoint changes, or an endpoint change against a name/measurement edit on the
same line, require a whole-line target/source choice. Derived unkept geometry
is recomputed from the selected endpoints and merged point coordinates.
Target list order and both parent scenarios are retained.

Only distinct references to existing point IDs are in scope. Additions/deletions,
angle reference changes, unknown authored fields and ambiguous criss-cross merge
bases remain conservative/unsupported. Network settings remain an independent
whole-object unit. This does not establish consistency between independently
authored network selections and changed lines; users must review the resulting
network before adjustment. Accepted v0.8 and maturity claims are unchanged.

Regression covers automatic merge, identical endpoint changes, competing
endpoints, endpoint versus name/measurement conflicts, both whole-line choices,
invalid references, atomic missing-choice rejection, geometry recomputation,
observation references, parent immutability, target order and reopen. Focused
Chromium uses saved branches seeded through the store (there is no endpoint
editing API), then exercises browser preview/choice/merge and restart/reopen.

Final test and independent review results are recorded under
`/workspace/ctrlnet-v08/cn_post_v08_line_endpoint_merge/`.

Validation: 465 passed, 1 skipped, 2 xfailed, 8 warnings in 30.80s.
Focused Chromium PASS; independent review PASS with 76 scenario-tree tests and
Chromium rerun. Demo SQLite SHA unchanged; prior evidence and unrelated worktree
deletions/runner dirt preserved. No cc-gins changes.
