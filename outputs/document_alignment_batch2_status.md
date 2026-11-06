# CtrlNet document alignment batch 2 status

- Baseline: `d32607c`
- Machine: local Codex `gpt-6.1-sol` in `/workspace/ctrlnet-design` (no cloud agent for implementation). Codex stalled after code/docs; executor finished commit/push hygiene.
- Pytest: **334 passed, 1 skipped, 2 xfailed** (`outputs/document_alignment_batch2_pytest.txt`)
- E2E: `scripts/test_document_alignment_batch2_e2e.py` PASS; `scripts/test_thesis_e2e.py` PASS
- Not staged: `data/sample/demo_project.sqlite`, `.dsh-prompts/**`, `outputs/document_alignment_batch2_codex.log`

## UI wired this batch
1. Dashboard `/` `/dashboard`: DEM / MBTiles / OSM / Esri basemap selector; Local UTM↔lon-lat for XYZ layers; CRS status; failure/timeout fallback; version list + compare API UI.
2. Thesis: editable CM / zone width / gauss|utm / false easting; cross-zone reject; topology JSON import/export; undo last 20.
3. Docs refreshed: gap matrix / impl report / basemap note / README.

## Remaining (true/partial)
- XYZ mode: DEM hillshade/contours/registration/profile not reprojected (disabled with note)
- No arbitrary EPSG editor / 7-param datum / BD-09
- No unified editable scenario tree across thesis↔dashboard; no drag/snap/redo
- No nationwide offline vector / MVT / GNSS editor UI
