# Two independent point choices across differing merge bases

Exactly two whole-point conflicts can retain independent choices when every
best base reports the same two stable IDs and all four joint outcomes agree
across every base. Every outcome must also have unique point names. A failed
check retains the whole-topology choice.

The merge preserves target point order, independent clean edits, known allocator
high-water marks, every best-base version guard and merge provenance. Extra
conflicts, mixed item types and recursive ancestor reconciliation remain
unsupported. Accepted v0.8 and the package version are unchanged.

Tests cover all four outcomes in both directions, disagreement in each joint
outcome, stale bases, invalid resolutions, duplicate alternate point names and
extra conflicts. Chromium verifies independent target/source choices, HTTP
persistence and restart/reopen. Independent review found the alternate-name
collision; the implementation now checks every offered outcome.

Final validation and independent review are recorded under
`/workspace/ctrlnet-v08/cn_post_v08_consensus_two_point_choice/`.
