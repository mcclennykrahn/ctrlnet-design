# Thesis project loading controls

Candidate `thesis_project_load_groups` keeps the saved-project selector beside its Load button and the two example buttons beside each other. The groups share one row in a wide panel and stack in a narrow panel. The baseline split the example buttons across rows at viewport widths of 900 and 390 px. The new panel adds vertical padding, and a long project name is clipped within the closed selector to keep the Load button in view.

Chromium captures at 1440×950, 900×950, 390×844, and 320×568 show the empty and populated selector. The focused check exercises keyboard navigation, loading both examples, and saving and reopening a project with a long name. It checks alignment, control height, containment and page errors. The thesis calculation, shared-project/GNSS and robust-estimation regressions passed. Independent review passed after checking the markup, JavaScript bindings, baseline, patch and screenshots.

Evidence, including baseline source, reproduction scripts and test logs, is in [the stage artifact folder](/workspace/ctrlnet-v08/cn_frontend_visual_project_load).

Full pytest: 1274 passed, 1 skipped, 2 xfailed, 8 warnings in 186.27s (0:03:06). Focused thesis pytest: 15 passed.
