# Post-v0.8: allocator drift in scenario topology merges

Bounded gap: independent edits no longer require a whole-topology choice solely
because consumed point/line/angle ID counters differ. Supported combined merges
preserve the maximum known counter from base, target and source, including a
base counter higher than both tips. Target presentation order stays intact.
Unknown allocator fields still participate in conservative skeleton comparison;
known counters must be nonnegative integers in the combined merge path.

This does not implement recursive competing-ancestor reconciliation. Differing
best bases still require equivalent conflict-free results from every base, or an
explicit whole-unit choice. No change to accepted v0.8 status.

Validation and independent review evidence:
`/workspace/ctrlnet-v08/cn_post_v08_allocator_merge/`.
The focused Chromium check consumes point IDs through HTTP add/delete operations,
merges independent coordinate/title edits across differing-content bases, restarts
and reopens, verifies counters/order/provenance, then allocates a fresh ID above
both parents. Unit tests cover both directions, independent counter maxima,
invalid known counters, unknown fields and input immutability.

Initial setup failures are retained in stage artifacts: missing `python` command,
missing default Playwright browser, and benchmark harness requiring `.venv`.
Tests use `/workspace/venvs/ctrlnet/bin/python`, installed Chromium, and a temporary
`.venv` symlink for the benchmark subprocess. Initial e2e attempted counter changes
through JSON import; import rebuilds counters, so the final check uses real edits.

Final validation: 773 passed, 1 skipped, 2 xfailed, 8 warnings in 289.69s.
Independent review PASS: 384 focused tests, four probes and separate Chromium.
Author Chromium PASS. Demo SQLite SHA256 unchanged:
`fa597f57b5952fa603b9464550c5d72e9c7c2b6bd4efc48c8281692b84a204f6`.
