# Thesis observation list readability

The observed and optimization lists now use 32px minimum-height checkbox rows,
wrapping observation names, and separate status badges for graphic-only, observed,
and added entries. Keyboard focus outlines the full row. The lists use two columns
on desktop and stack at the existing mobile breakpoint. The taller rows leave
fewer entries visible at once, with vertical scrolling for the rest.

Chromium before and after captures cover 1440, 900, 390, and 320px. A synthetic long
name gave the first list a 721px scroll width at all four widths before the change.
Afterward, its scroll width matched its visible width at each viewport. The focused
browser checks also cover keyboard focus, observed and added selection through
successful network updates, and calculation after restoring the original selection.

Independent review passed. The thesis example calculation, shared-project and GNSS
flows, and robust estimation browser regressions passed. Evidence is recorded under
`/workspace/ctrlnet-v08/cn_frontend_visual_observation_lists/`.

Full pytest reported 1274 passed, one skip for optional pyproj, two expected
thesis-reference failures, and eight warnings in 644.76 seconds.
