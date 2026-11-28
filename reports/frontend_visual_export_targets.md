# Export dialog target sizing

The thesis text export dialog now gives its header close button a 44×44px target and its Copy and Close footer buttons a 44px minimum height, up from 36px. This matches the recently enlarged project controls while keeping the change scoped to this dialog. The header and footer each use 8px more height; export text retains its scrollable area and existing responsive bounds.

Evidence: `/workspace/ctrlnet-v08/cn_frontend_visual_export_targets`. Chromium screenshots and geometry checks cover 1440, 900, 390 and 320px widths. The harness loads example 1, checks both real export responses against dialog text, copies coordinate text to the clipboard, exercises both close buttons and checks dialog bounds and page overflow. Baseline screenshots use the saved pre-change stylesheet. The initial empty-project harness failed because there were no points to export; loading the example corrected the setup.

Validation results and independent review are recorded with the stage artifacts. Existing acceptance and remaining product gaps are unchanged.

Final validation: pytest 1274 passed, 1 skipped, 2 xfailed (215.00s); focused four-width Chromium checks and all three browser regressions PASS. Independent review PASS. Demo SQLite matches HEAD.
