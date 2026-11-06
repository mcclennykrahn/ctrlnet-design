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
