# Saved scenario lifecycle

The shared engineering panel records a single-user scenario workflow in SQLite:

| Current | Allowed next states |
| --- | --- |
| draft | review, archived |
| review | draft, approved, archived |
| approved | draft, archived |
| archived | draft |

Every transition requires the displayed version and a 1–500 character note. Stale
requests return 409; illegal transitions return 400 without partial writes.
Submission and approval require a saved snapshot matching the current numerical
inputs; history records its ID and hash. Names and workflow revision counters do
not invalidate numerical evidence. Approval records a user's decision, not a
numerical quality guarantee or an independent review signature.

Rename and observation replacement require draft. Whole-project overwrite is
rejected once any scenario has workflow history, preserving that history even
after restoration to draft. Opening a saved scenario copies it to the active
editor; saving or merging creates a new draft with independent history. Archived
scenarios remain readable, calculable and usable as branch/merge sources. There
is no deletion, access control, multi-user reviewer identity or release gate.
Legacy scenarios default to draft with empty history, without rewriting their
snapshots. Existing v0.8 acceptance is unchanged.

Selected angle additions between points present in all three snapshots now merge
by stable ID. Selection remains part of the whole network settings object: competing
settings require an explicit target/source choice, while either choice retains the
accepted angle. Target angle order and the maximum allocator are preserved; angle
values are recomputed from merged coordinates. Selected deletions, unsafe point
references, competing added IDs/names, duplicate ordered triples and unknown
authored fields remain whole-topology conflicts. Ambiguous merge bases remain
unsupported. This bounded extension does not change v0.8 acceptance.

Competing editor project titles can be resolved independently through the `title`
choice when ordinary three-way topology merging is supported. The selected title
preserves independent geometry edits and is distinct from the new snapshot name.
Differing-content best bases also offer the independent title choice when every
best base reports only a title conflict and produces the same remaining topology.
The chosen title is applied to that verified consensus, preserving target order,
all-base/tip allocator maxima and all-base version guards. Mixed clean/conflicted
ancestor results, other field conflicts and disagreeing geometry still require a
whole-topology choice. This does not recursively reconcile competing ancestors.

Ordinary and equivalent-base merges also preserve known point/line/angle allocator
high-water marks from every best base and both tips when content merging takes a
trivial shortcut. Converged imports or deletions cannot recycle an ancestor's
consumed IDs. Invalid known counters require a whole-topology choice. This does
not extend recursive reconciliation of competing ancestor edits.

Differing-content best bases also permit converged authored tips whose point,
line or angle lists differ only in stable-ID presentation order. This includes
converged structural deletions: the target order and all-base/tip known allocator
maxima survive without replaying ancestor edits. Actual authored disagreements,
unknown-field differences and invalid counters retain conservative conflicts.
Recursive reconciliation of competing ancestor edits remains unsupported.
