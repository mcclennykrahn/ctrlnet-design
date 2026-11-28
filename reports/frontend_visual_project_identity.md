# Thesis project identity controls

The thesis project name used a 26px input beside compact commands. It now occupies a full-width labeled row above three equal-width commands. The input and buttons have 44px targets, with spacing and borders consistent with adjacent settings. This increases the card height and scrolling required.

Chromium before/after captures cover 1440, 900, 390 and 320px. Checks verify containment, target heights, save/refresh persistence, keyboard order and absence of page errors. Thesis calculation, shared-project/GNSS and robust-estimation browser regressions passed. Independent source and screenshot review passed.

Evidence: `/workspace/ctrlnet-v08/cn_frontend_visual_project_identity`, including screenshots, capture harness, review, regression logs and source patch. Existing acceptance and remaining gaps are unchanged. Protected docs/target deletions and unrelated dirt are excluded.

Validation: focused final-source pytest: 31 passed. Full-suite result is recorded in the candidate delivery JSON and pytest.txt; that run began before the CSS edit, with final CSS verified by focused tests and browser checks.
