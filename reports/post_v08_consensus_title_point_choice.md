# Independent title and point choices across differing merge bases

The scenario planner now retains independent title and one whole-point choice when every differing-content best base reports exactly those conflicts and all four joint outcomes agree across every base. Existing target stable-ID order, known allocator maxima, provenance, immutable snapshots and stale-version guards remain in force. Other mixed/multiple conflicts and recursive ancestor reconciliation remain unsupported.

Validation: 19 focused feature tests passed; author and independent Chromium merge/restart/reopen passed. Independent review PASS with 118 regression tests and 8 adversarial probes including three best bases and all four outcomes. Full pytest: 1044 passed, 1 skipped, 2 xfailed, 8 warnings in 117.39s. An initial run exposed one obsolete conservative-policy expectation, updated to the new bounded behavior; final independent follow-up: 28 passed.

v0.8 acceptance is unchanged. No production maturity claim is made.
