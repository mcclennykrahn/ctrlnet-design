# Thesis line and angle table readability

Line and angle library tables now use 12px text, 8px cell padding, alternating
row shading, and a highlight on the row containing keyboard focus. Delete controls
have a 32px minimum height and a tinted hover state. These styles match the
existing point table while retaining the original table structure and actions.

Chromium evidence covers 1440, 900, 390, and 320px, including keyboard focus,
local horizontal scrolling, deletion and example restoration. Rows measured 30px before and 49px after in both libraries. Taller rows show fewer entries at once;
narrow layouts may require more horizontal scrolling within the table wrapper.

Evidence and independent review:
`/workspace/ctrlnet-v08/cn_frontend_visual_geometry_tables/`.
Independent source and visual review passed. The thesis calculation, shared-project
and GNSS flows, and robust estimation browser regressions passed. The capture
harness retried one toast timeout with a longer wait; production code was unchanged.
Full pytest: 1274 passed, 1 skipped, 2 xfailed, 8 warnings in 630.63s.
The skip is optional pyproj; the two expected failures concern unpublished thesis
angle data.
