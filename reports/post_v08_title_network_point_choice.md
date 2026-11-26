# Independent title, network and point choices across differing bases

This bounded stage retains three independent choices only when every best base reports exactly the same title, network and one whole-point conflict. All eight joint outcomes must agree across all bases. The existing consensus machinery preserves target order, known allocator high-water marks and all-base provenance/version checks.

Additional item conflicts, title/network plus line or angle conflicts, unknown authored fields and recursive ancestor reconciliation remain conservative. Accepted v0.8 status is unchanged.

Independent review PASS: 97 focused tests plus a 30-test dual-choice follow-up, seven external probes (including three best bases and prepatch rejection), and a separate Chrome restart/reopen run. Full regression: 1147 passed, 1 skipped, 2 xfailed, 8 warnings in 119.07s (0:01:59). Focused Chromium merge/restart/reopen passed using installed Google Chrome; the bundled Playwright browser was absent. Unrelated document deletions and runner files are excluded.
