# Allocator-equivalent best bases retain field choices

One bounded post-v0.8 gap: best bases with equal authored topology but differing
valid known allocator counters now retain ordinary field-merge behavior, including
independent title/point/line/network choices. A copied representative base uses
point/line/angle high-water marks from every best base; both tips participate in
the existing merge and choice pass. Saved ancestors remain unchanged, target order
and all-base provenance/version guards remain intact.

Actual authored ancestor disagreements still require convergence, clean all-base
consensus, or explicit whole-unit choices. Unknown allocator fields and malformed
known counters are not normalized away. Recursive ancestor reconciliation remains
unsupported. Accepted v0.8 is unchanged; no production maturity claim.

Focused regressions cover both directions, both title resolutions, disjoint point
edits, reset tip counters, all three ancestor maxima, ancestor immutability and
stale-base rejection. Chromium exercises real consumed-ID ancestor differences,
disjoint coordinates, a source-title choice, restart/reopen, provenance, target
order and fresh allocation. Stage validation and independent review evidence live
under `/workspace/ctrlnet-v08/cn_post_v08_allocator_equivalent_bases`.

Validation: **821 passed, 1 skipped, 2 xfailed, 8 warnings in 66.08s**.
Author and independent Chromium checks PASS. Independent review PASS: 80 focused
tests, 8 adversarial probes, and prepatch regression confirmation. The installed
Chrome executable was used after the default Playwright browser was absent. A
temporary `.venv` link supplied the benchmark's expected interpreter and was
removed. Sample SQLite SHA256 matches HEAD. Unrelated deletions and runner dirt
were preserved and excluded; no cc-gins edits.
