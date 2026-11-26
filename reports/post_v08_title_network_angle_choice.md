# Independent title, network and angle consensus choices

One bounded post-v0.8 extension: differing-content criss-cross bases can retain independent editor title, whole-network and one whole-angle choices when every best base reports exactly those conflicts and every one of the eight joint outcomes agrees across all bases. Angle names and reference changes use the existing whole-angle resolution. Target presentation order, known allocator high-water marks, provenance and stale-version checks remain in force.

Title/network/line, additional item conflicts, differing conflict signatures and recursive ancestor reconciliation remain conservative whole-topology conflicts. Accepted v0.8 status is unchanged.

Validation evidence: `/workspace/ctrlnet-v08/cn_post_v08_consensus_title_network_angle_choice`.

- New focused suite: 46 passed; both angle name and reference edits, both tip orders, all choices, poisoned outcomes, stale bases and extra conflicts.
- Independent review: PASS, 133 focused regression tests and four external probes including prepatch rejection, three real best bases with all eight persisted outcomes, mismatched signatures and unsupported triple-line conflicts.
- Author and independent Chromium: separate title/network/angle selectors, merge and restart/reopen, independent authored edits, order, allocator and provenance checks.
- Initial full run interrupted after two obsolete conservative expectations failed; both symmetric tests now assert the supported shape and preserve other conservative cases.
- Full final pytest: 1193 passed, 1 skipped, 2 xfailed, 8 warnings in 148.92s (0:02:28).

Sample SQLite matches HEAD; unrelated workspace dirt and prior stage evidence preserved. No cc-gins changes.
