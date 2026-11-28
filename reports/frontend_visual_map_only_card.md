# Thesis map-only card

In the map-only thesis view, the map previously used nearly the entire viewport height inside a fixed-height card. The basemap toolbar and caption took additional space, clipping the caption and dashboard link. The card now fills the space below the shared-project panel. Its toolbar and caption use their natural heights, and the map fills the space between them. On short screens the page scrolls and the map keeps a 200px minimum. Leaflet updates its size when text wrapping changes the map height.

Chromium screenshots cover 1440×900, 900×720, 390×844, 320×568, 568×320 and 568×240. The checks verify the footer is reachable, the document has no horizontal overflow, zoom works, failed road tiles return to the offline DEM, and the map stays centered when the toolbar wraps. The full thesis workspace, example calculation, shared-project and GNSS flows, and robust-estimation browser regressions also passed.

[Before screenshots](/workspace/ctrlnet-v08/cn_frontend_visual_map_only_card/before) · [After screenshots](/workspace/ctrlnet-v08/cn_frontend_visual_map_only_card/after) · [Independent review](/workspace/ctrlnet-v08/cn_frontend_visual_map_only_card/independent_review.md)

Independent review passed. Pytest reported 1274 passed, 1 skipped, 2 xfailed, 8 warnings in 299.66s (0:04:59). The skip was for optional pyproj.
