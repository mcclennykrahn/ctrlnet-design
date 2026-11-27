# Thesis projection settings

Candidate `thesis_projection_controls` organizes the central meridian, zone
width, convention and false easting in an aligned two-column card. Controls
are 36px tall, the apply button spans the card, and the help text wraps below.
Existing IDs, values, constraints and projection behavior are preserved.

Chromium before/after captures at 1440, 900, 768, 390 and 320px are recorded in
`/workspace/ctrlnet-v08/cn_frontend_visual_projection_controls/{before,after}/`.
The focused probe applies UTM to the sample project, confirms nine points
remain, and checks control bounds and page width after the change. Baseline
HTML and CSS are retained with the probe and logs.

Thesis, GNSS and robust browser regressions passed. Independent review passed
based on source, desktop/mobile captures and recorded browser evidence.
Pytest: 1,274 passed, one skipped, two expected failures (232.69s).
Full output is recorded in the same artifact directory and delivery JSON.
This bounded styling change makes no product maturity claim.
