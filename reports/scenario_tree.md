# Post-v0.8 scenario merge/rename tree

The shared engineering panel now shows scenario ancestry, version, and both
parents of merges. Enter a name and use **重命名所选方案** to rename the selected
scenario. Rename checks its current version, increments it, and preserves IDs,
children, observations, and existing snapshots.

To merge saved editor scenarios in the same project:

1. Select the target scenario and choose the source in **比较对象**.
2. Use **预览合并**. The server finds a unique common ancestor across branch and
   merge ancestry. The preview records the current versions of all three inputs.
3. Resolve each conflicting unit explicitly, enter a new name, and use
   **保存合并新方案**. A changed input requires a fresh preview.

The initial implementation described below is a conservative three-way merge.
The later bounded coordinate extension is documented in
[post_v08_point_merge.md](post_v08_point_merge.md). Complete editor topology (including
projection and network settings) is one unit, and the GNSS list is another.
Unchanged units and identical changes merge automatically. Divergent edits in
the same unit require choosing the target or source. Timestamps and recomputed
geometry do not cause conflicts. The selected original topology is preserved;
there is no automatic point/line splicing. GNSS endpoints and covariance are
validated against the resulting topology before saving.

A merge creates a new scenario and computation snapshot in one SQLite write
transaction. Neither parent is overwritten. Metadata stores both parent IDs,
base ID, input versions, and resolutions; the normal parent link points to the
target. The editor draft is unchanged until the user opens the saved merge.
The tree displays the target hierarchy and labels both merge parents.

Limits: saved thesis-editor scenarios only; no cross-project merge, no unrelated
roots, and no ambiguous criss-cross merge bases. Fine-grained geometry conflicts
remain manual choices of whole topology. This closes the practical tree/rename/
merge workflow without claiming arbitrary geometry merging or production maturity.
The accepted v0.8 release decision and version are unchanged.

Validation: `tests/test_scenario_tree.py` covers independent units, both topology
conflict choices, GNSS conflict resolution, stale rename/preview, malformed
names, cross-project/self merge, incompatible endpoints with rollback, repeated
merge ancestry, snapshots, and timestamp-only no-op editor saves. The isolated
Chromium script `scripts/test_scenario_tree_e2e.py` exercises tree/rename/conflict/
merge controls and reopens merged GNSS after server restart. Stage test counts,
independent review and screenshot are recorded in
`/workspace/ctrlnet-v08/cn_post_v08_scenario_tree/`.

Final stage validation: **370 passed, 1 skipped, 2 xfailed** (8 warnings).
Focused Chromium: **PASS**; independent source review and independent focused
Chromium rerun: **PASS**. The skip is optional pyproj; expected failures are the
existing unpublished thesis-angle limitations. Sample SQLite SHA256 unchanged.
