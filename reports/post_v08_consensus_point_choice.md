# Lone point choice over differing-content merge bases

One bounded post-v0.8 extension: when every best base reports only the same whole-point conflict, offer that point choice only after verifying both target and source outcomes against every base. Unrelated clean edits remain merged, with target order, allocator high-water marks, all-base versions and provenance preserved. Commit recomputes the verified all-base plan with the selected point, avoiding replay against one representative ancestor.

Mixed point/title/network conflicts, multiple point conflicts, mismatched per-base conflict sets and differing outcomes retain whole-topology conflicts. Recursive ancestor reconciliation remains unsupported. Accepted v0.8 is unchanged.

Validation: 937 passed, 1 skipped, 2 xfailed in the full pytest run. Focused Chromium merge/restart/reopen passed; independent review evidence is stored under `/workspace/ctrlnet-v08/cn_post_v08_consensus_point_choice`. Prior document deletions and runner dirt are excluded from this change.
