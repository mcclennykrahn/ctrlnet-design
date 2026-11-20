# Independent title choice for differing-content merge bases

A saved-scenario merge can now offer a `title` choice over differing-content
criss-cross best bases when every base independently produces the same remaining
topology and reports exactly that title conflict. The choice preserves the
verified geometry, target list order and all-base/tip known allocator maxima.
It does not replay a representative ancestor during resolution. The saved
scenario name remains separate from the editor project title.

Mixed clean/title-conflicted ancestor results, other field conflicts, disagreeing
candidate geometry, unknown authored fields and invalid counters retain the
whole-topology conflict. Recursive reconciliation of competing ancestor edits
remains unsupported. Accepted v0.8 and product maturity claims are unchanged.

Regression tests cover both directions and title choices, independent coordinates,
ancestor-only allocator peaks, immutable parents, provenance, invalid/missing/extra
choices and stale versions for either best base. Focused Chromium exercises the
title control, saves the merge, restarts the server and reopens the result.
Independent review and validation evidence are recorded under
`/workspace/ctrlnet-v08/cn_post_v08_consensus_title_choice/`.

The initial focused run exposed one expectation for the old conservative behavior;
that expectation now checks the supported title-only result. The full suite uses
the existing ctrlnet environment and a temporary interpreter link for the benchmark
subprocess; the link is removed after validation. Pre-existing deleted documents,
runner dirt and the sample database are preserved. No cc-gins changes.

Validation: full pytest 882 passed, 1 skipped, 2 xfailed, 8 warnings in 88.24s.
Final strengthened focused regression: 35 passed. Author and independent Chromium
PASS. Independent review PASS: 73 focused tests and 12 external adversarial probes,
including three-best-base title choices and independent GNSS resolutions.
