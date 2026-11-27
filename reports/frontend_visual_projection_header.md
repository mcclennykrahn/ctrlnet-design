# Thesis projection settings

Added a visible projection heading and a short coordinate-direction caption to identify the existing field grid. Projection inputs, selects and apply button now have 44px targets. The taller card uses additional sidebar space.

Chromium before/after crops cover 1440, 900, 390 and 320px. Focused checks verify control height, no document overflow and the apply interaction. Existing thesis calculation, shared-project/GNSS and robust browser regressions pass. Evidence, full pytest output and independent review are under `/workspace/ctrlnet-v08/cn_frontend_visual_projection_header`.

Independent review initially found an unrelated network-control height change; it was reverted before re-review. This change makes no release-readiness or acceptance claim.
