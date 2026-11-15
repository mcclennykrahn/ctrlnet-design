# Equivalent criss-cross merge bases

One bounded post-v0.8 gap: multiple best common ancestors are accepted when every topology and GNSS unit is equivalent under existing timestamp and derived-geometry normalization. Base IDs are sorted for a deterministic representative, all base versions guard the preview, and all base IDs are stored and displayed in the lineage tree. Unique-base behavior and existing topology merge rules remain intact.

Different authored values, measurements, selections, order, allocators or unknown fields between bases still reject the merge. There is no virtual-base synthesis or support for arbitrary ambiguous criss-cross content. Accepted v0.8 is unchanged.

Validation: **720 passed, 1 skipped, 2 xfailed, 8 warnings in 67.22s** with an explicit source PYTHONPATH. The first full run had an import failure in the benchmark subprocess; initial evidence is retained externally. Optional pyproj is unavailable. Focused HTTP/Chromium PASS verifies a real criss-cross DAG, independent coordinate edits, preview/merge, restart/reopen, target order, allocator preservation, dual parents, all-base provenance and tree display. Installed Google Chrome was used because the bundled Playwright binary is absent.

Independent review: PASS, with 331 focused tests, five additional probes and a separate Chromium rerun. Evidence: `/workspace/ctrlnet-v08/cn_post_v08_equivalent_bases`. Prior deleted documents and runner dirt are excluded. No cc-gins changes or renewed v0.8 acceptance claim.
