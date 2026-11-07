# Measured line override scenario merge

Saved scenario merges now combine existing point coordinate/name/fixed edits with
independent measured line length and azimuth overrides. Each keep flag and its
measured value form one indivisible unit. Computed values do not count as edits;
after merging, geometry is refreshed while chosen measurements remain intact.
Different overrides on the same existing line can combine. Competing edits to an
override, including clearing versus changing its value, retain the existing
whole-topology target/source choice.

Automatic combination requires identical ordered point and line IDs and all
other authored structure/settings. Structural changes, remaining authored fields,
per-point conflict choices and ambiguous criss-cross merge bases remain open.
This is a bounded post-v0.8 feature; accepted v0.8 and release maturity are unchanged.

Validation covers both measured fields alongside coordinate edits, independent
length/azimuth changes, clear-versus-edit conflicts, atomic rejection, parent
preservation and reopen. The focused Chromium script seeds a measured branch via
the store because no line-override editor endpoint exists, then exercises real
HTTP preview/merge controls and server restart/UI reopen in isolated databases.
Evidence and independent review: /workspace/ctrlnet-v08/cn_post_v08_line_overrides/.
