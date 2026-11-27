# Thesis notification readability

Candidate: `thesis_notification_readability`; new source work after pushed `c864395`.

Thesis notifications now use 13px text at every viewport, roomier padding, rounded borders and distinct green/error-red surfaces. Their width is capped at 430px or the viewport gutter. Long tokens wrap, and tall messages scroll locally within 240px and the available viewport height. Existing toast content, state changes and automatic expiry remain unchanged.

Chromium before/after evidence covers 1440×950, 900×950, 390×844, 320×568 and 740×360. Real invalid-line and example-load actions check error/success styling and expiry. Synthetic long-token and multiline messages stress wrapping and scrolling separately. At 320px the baseline multiline box extends above the viewport; the final box stays inside it. The final long-token case has no internal horizontal overflow at every tested size.

Tradeoff: larger text and padding cover more underlying content. Long messages require scrolling within the existing expiry period. This change does not resolve notification accessibility or alter dismissal behavior.

Evidence and harness: `/workspace/ctrlnet-v08/cn_frontend_visual_toast/`. Initial harness expected an empty-field error, but default numeric values generated a missing-point error; corrected expectation and retained retry log. Browser regressions use isolated databases and candidate-specific outputs to preserve earlier evidence. Existing acceptance and product gaps remain unchanged.

Validation: full pytest — 1274 passed, 1 skipped, 2 xfailed, 8 warnings in 272.66s. Optional pyproj is absent; existing expected failures remain. Focused thesis web tests — 15 passed. Five-size before/after Chromium, all three browser regressions and independent source/visual review PASS. Independent Chromium also passed at 280×240, 390×844 and 1440×950. Sample SQLite hash unchanged. Full pytest started during baseline capture; CSS was edited while it ran, with final CSS separately covered by focused tests and after-change browser checks.
