# Differing-base topology consensus

A bounded post-v0.8 scenario merge extension: when best common ancestors differ,
try the existing conservative topology merge independently against every base.
Accept automatically only if every attempt is conflict-free and the refreshed
results are equivalent. The existing merger retains target order, stable IDs and
allocator rules. All-base provenance and version checks remain mandatory.

This handles ancestor differences already reconciled by both tips while combining
independent later edits. It does not synthesize recursive virtual ancestors or
resolve competing ancestor edits. A conflicting attempt, unequal clean results,
unknown authored fields, or differing GNSS content still uses the existing whole
unit choices. Existing structural safety guards remain in force.

Validation: full pytest and author/reviewer Chromium restart/reopen evidence in
`/workspace/ctrlnet-v08/cn_post_v08_consensus_bases`. Tests cover both directions,
each stale base, three best bases, unequal clean candidates, and unknown fields.
Initial test expectations for newly supported cases were updated; the initial
failed run is retained in external stage artifacts. Accepted v0.8 and prior
Stage3 evidence are unchanged. Sample database SHA matches HEAD. No cc-gins edits.

Final validation: **743 passed, 1 skipped, 2 xfailed, 8 warnings in 49.95s**.
Independent review PASS: 354 focused tests plus separate persisted probes and
an independent Chromium restart/reopen run. Author Chromium run also PASS.
