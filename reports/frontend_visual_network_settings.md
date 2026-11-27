# Thesis network settings readability

Candidate `thesis_network_settings` replaces the cramped network settings row with
an aligned two-column card. Grade and tolerance controls are 36px high; the
recommendation occupies a separate full-width row with readable wrapping. Existing
labels and focus outlines remain, with an active-label color matching nearby settings.
Only thesis CSS changes; calculation behavior and dashboard styling are unchanged.

Evidence: `/workspace/ctrlnet-v08/cn_frontend_visual_network_settings/`.
Before/after Chromium captures cover 1440, 900, 390 and 320px, including focus.
Focused checks verify field alignment, control size, no page overflow, editable grade
and tolerance, calculation, JSON topology round trips and undo/redo. They do not
independently establish persistence of the changed tolerance.

Full pytest: 1274 passed, 1 skipped (optional pyproj unavailable), 2 xfailed,
8 warnings in 449.32s. Independent review: PASS. Thesis calculation, GNSS/shared-project and robust
estimation browser regressions passed; results are recorded with the stage artifacts.

The initial focused runner raced the asynchronous grade update; waiting for its
response and the enabled calculate button resolved this test timing issue. An
artifact-local thesis regression copy also needed its final screenshot log changed
from a repository-relative path to an absolute artifact path. Neither issue required
product JavaScript changes. Existing target deletions and unrelated files are excluded.
This bounded visual delivery does not change acceptance status or close product gaps.
