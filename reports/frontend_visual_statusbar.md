# Dashboard status bar

Candidate `dashboard_statusbar_readability` improves the dashboard’s map
readouts with 12px type, brighter coordinates and attribution, and a consistent
reading order. The desktop bar retains its 30px height. Unusually long mode
labels truncate on desktop so the coordinate, CRS and attribution fields remain
visible. Tablet widths use two columns, and phone widths stack all four fields.

Chromium captures and checks at 320, 390, 768, 1024, 1025 and 1440px are in
`/workspace/ctrlnet-v08/cn_frontend_visual_statusbar/`. The probe moves the
pointer on the map to populate real coordinates and checks containment with a
long scenario name. The same folder holds pytest, GNSS and robust-estimation
regression results, and independent review.
