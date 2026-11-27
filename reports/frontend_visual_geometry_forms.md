# Thesis line and angle entry forms

Candidate `thesis_geometry_forms` places point labels above equal-width number
fields. Both forms use 36px controls and the existing keyboard focus outline.
The angle action moves to a right-aligned second row when the panel is too
narrow to hold all four controls.

Matching Chromium captures at 1440, 900, 768, 390 and 320px are in
`/workspace/ctrlnet-v08/cn_frontend_visual_geometry_forms/{before,after}/`.
The baseline serves the prior HTML and CSS. The probe tabs between inputs and
adds a line and an angle in a disposable copy of the thesis workspace. It also
checks control sizes, field alignment and document width after the change.

The artifact directory contains the focused browser logs, thesis, GNSS and
robust browser regressions, full pytest output, and independent review.

Pytest finished with 1,274 passed, one skipped and two expected failures.
The focused Chromium probe passed at all five widths in both phases, and
the three existing browser regressions passed.
