# Existing-point field merge

The unique-base scenario merge now combines existing-point name and fixed-flag
changes independently of each other and of the indivisible x/y/lon/lat tuple.
Point identity/order and all other authored topology must still match. Conflicting
edits to the same field retain the whole-topology target/source choice. Derived
geometry is refreshed and the existing atomic save, stale checks, GNSS endpoint
validation and dual-parent lineage remain in use.

This is a bounded extension of the previous coordinate merge. Structural merges,
other authored fields, per-point conflict choices and ambiguous criss-cross merge
bases remain open. Accepted v0.8 is unchanged; no maturity claim is added.

Validation: pytest covers coordinate plus name/fixed edits on the same point,
reopen, conflicting names and retained structural fallbacks. The focused Chromium
script test_point_fields_e2e.py merges coordinate and fixed edits on the same point
through the existing preview/merge UI, restarts the service and reopens the result.
Full results and independent review are retained under
/workspace/ctrlnet-v08/cn_post_v08_point_fields/.
