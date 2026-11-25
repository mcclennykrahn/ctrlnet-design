# Independent network and point consensus choices

This bounded post-v0.8 change preserves independent whole-network and single whole-point choices for differing-content best bases. Every base must report exactly the same network and point conflicts, and all four joint outcomes must produce identical topology across every base. The existing exhaustive outcome check, target ordering, all-base allocator maxima, provenance and version guards remain in use.

Network plus line/angle, additional item conflicts, title/network/point triples, unknown authored fields, and recursive ancestor reconciliation remain conservative whole-topology conflicts. Accepted v0.8 status is unchanged.

Validation: 1063 passed, 1 skipped, 2 xfailed, 8 warnings in 124.35s (0:02:04). Focused feature/prior-network tests: 32 passed. Author and independent Chromium merge/restart/reopen: PASS. Independent review: PASS with 38 focused/probe tests, seven external adversarial probes, three-base all-four-outcome checks and prepatch rejection. An obsolete single-point fallback expectation was corrected to retain a two-point fallback check. The sample database matches HEAD; unrelated worktree files are excluded.
