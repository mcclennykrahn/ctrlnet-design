# CtrlNet document alignment third batch

- Baseline: main `0b55d04`; local edits, no cloud agents.
- Commit/push: see appended result below.
- Full pytest: **337 passed, 1 skipped, 2 xfailed**.
- Chromium: third E2E PASS (actual XYZ map clicks / drag / snap / undo / redo, zero pageerror); batch2 E2E PASS (including real local MBTiles and mock public XYZ fallback); original thesis E2E PASS (Qxx=.6502, Qyy=.3039).

UI wired:
1. Dashboard offline warped DEM EPSG:3857 selector; shared hillshade/contour/registered scan toggles under XYZ; bounded real raster warp + instance cache status and CRS hint.
2. XYZ two-point profile reprojects clicks back to project CRS and samples original DEM; map line and chart.
3. Thesis point placement/drag with optional project-metre grid snapping, atomic PATCH and related geometry refresh; undo/redo last20 successful mutations, new edit clears redo.

Evidence: `document_alignment_third_xyz.png`, `profile.png`, `editor.png`, `coordinates.json`; reviewed visually. These are offline evidence, not claims of public tile service availability.

Remaining: unified editable scheme tree (thesis/dashboard remain separate); GNSS advanced params UI; point/line snapping; persistent history; arbitrary CRS/datum transforms; nonstandard geographic-pixel MBTiles import. Existing standard MBTiles has geographic bounds metadata but native Mercator XYZ tiles, served directly. Warp cache is per service instance, not disk-persistent; rendering is bounded preview. No Baidu/BD-09/vendor packs/CDN introduced.

Sample DB and existing screenshots restored after regression; `.dsh-prompts/**` and preexisting codex log excluded.
