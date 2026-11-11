# Bounded unchanged-line deletion merge

Saved-scenario merges can combine deletion of an otherwise unchanged, unselected existing
line with supported edits elsewhere. Comparison ignores derived length/azimuth
but retains kept measurements, flags, endpoints, names and field presence.
Survivor lines retain target order and the line allocator retains all three
snapshots' high-water marks. Existing point structural rules still apply.

Delete-versus-edit, unknown deleted-line fields, and either branch retaining a
network selection of the removed line require whole-topology choices. Line and
angle additions and ambiguous criss-cross bases remain unsupported. No maturity
claim or change to accepted v0.8.

Validation: 515 passed, 1 skipped, 2 xfailed, 8 warnings in 50.86s.
Independent review and focused HTTP/Chromium evidence are retained under
`/workspace/ctrlnet-v08/cn_post_v08_line_delete/`. Review caught and fixed a
network-selection safety issue before commit. Initial test and browser failures
are retained in stage evidence. Unrelated dirt and prior evidence are preserved.

The focused browser fixture removes public JSON display fields (`from_name`,
`to_name`, `status`) before import. Snapshots retaining those fields remain
outside this bounded automatic deletion path and receive topology conflicts.
