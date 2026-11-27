# Dashboard layer controls

Candidate `dashboard_layer_controls` gives each map layer a bordered row with a minimum 44px target, an 18px checkbox, clearer spacing, and enabled and keyboard-focus states. Labels wrap within narrow panels; the offline tile selector can wrap onto another line. Native checkbox semantics and existing map handlers are retained.

Evidence: `/workspace/ctrlnet-v08/cn_frontend_visual_layers`. Chromium before/after views cover 1440, 1024, 820, 390 and 320px. The focused script verifies row and checkbox sizes, layer visibility toggles, navigation, comparison, map containment and profile rendering. Full pytest, existing GNSS/robust browser regression and independent review results are recorded there. Existing acceptance and product gaps are unchanged.

Validation: 1274 passed, 1 skipped, 2 xfailed, 8 warnings in 183.00s. Five-width focused Chromium and GNSS/robust browser regressions PASS. Independent review PASS: 40 focused tests and six-width Chromium checking every layer label toggle, enabled/focus states and containment. Sample SQLite unchanged.
