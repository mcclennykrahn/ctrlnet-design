# Thesis workspace visual polish

The thesis workspace had tightly packed controls, browser-default engineering
buttons and four narrow result cards on phones. This bounded CSS change gives
the existing controls consistent borders, focus outlines, spacing and green
accents. Panel headers and tabular values are easier to scan; phone results use
two columns. The engineering panel has its own scroll area and desktop map and
library columns share the remaining viewport height.

Calculation code, page routes and stored data formats are unchanged. This is
visual polish, with no new product maturity or v0.8 acceptance claim. The
dashboard retains its existing stylesheet.

Chromium before/after evidence at 1440×1000, 821×1000, 820×1180 and 390×844 is in
`/workspace/ctrlnet-v08/cn_frontend_visual/{before,after}`. The reproducible
`scripts/test_frontend_visual_e2e.py` uses isolated databases, checks the known
example calculation and 17 denominator rows, and records page errors, external
requests, viewport containment and unbroken decimal values. Independent review
found decimal values splitting just above the tablet breakpoint; the corrected
grid sizes its columns to available space. Set `VISUAL_PHASE=before` on the baseline
and `VISUAL_PHASE=after` on this version. `CHROMIUM_EXECUTABLE` can select a
locally installed Chromium binary; `VISUAL_ARTIFACTS` selects the evidence root.

Full pytest, existing GNSS/robust-estimation browser regressions and independent
review evidence are saved in that same stage directory. Regression screenshots
have new destinations so prior stage evidence is preserved. The stage manifest
and completion record contain the final outcomes.

Final validation: 1274 passed, 1 skipped (optional pyproj unavailable), 2 expected
failures, 8 warnings in 191.30s. Both existing GNSS and robust-estimation browser
regressions pass after the responsive correction. Independent review: PASS
after correction, with five Chromium widths (320, 390, 820, 821, 1440), all stage
views, GNSS/save/calculation flows and 31 focused pytest tests. Author screenshots
and viewport/decimal assertions pass at all four recorded widths.

Before this visual change, pending reviewed two-point consensus work was
resumed and committed separately as `c2e5356`, with fresh focused tests and a
Chromium merge/restart/reopen check. Unrelated document deletions, prompt files
and raw logs remain outside both commits; the sample database matches HEAD.
