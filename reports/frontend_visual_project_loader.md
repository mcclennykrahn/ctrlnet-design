# Project loader target sizing

The thesis saved-project selector, Read command, and two example commands now use 44px minimum heights, matching the adjacent project identity commands. Existing responsive grouping and labels remain intact. The loader card grows by 16px when its two groups stack, or 8px when they sit side by side.

Chromium before/after screenshots at 1440, 900, 390 and 320px show all four controls changing from 36px to 44px. Both example transitions and page overflow checks pass. Evidence, full pytest results, browser regressions and independent review are under `/workspace/ctrlnet-v08/cn_frontend_visual_project_loader`.

The browser regression runner selects the installed Chromium executable because Playwright's default downloaded browser is absent. Existing acceptance and remaining product gaps are unchanged.

Validation: 1274 passed, 1 skipped, 2 xfailed (181.18s); thesis, shared-project/GNSS and robust browser regressions PASS. Independent review PASS.
