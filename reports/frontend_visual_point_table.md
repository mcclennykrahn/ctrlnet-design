# Thesis point table readability

Candidate `thesis_point_table_readability` gives the coordinate table 12px
numerals, more row spacing, alternating row backgrounds and a highlighted row
while a control has focus. Point-type selectors and delete buttons are now 30px
tall. The styling is scoped to the point table; wide coordinate columns retain
local horizontal scrolling on narrow screens.

Chromium before/after captures at 1440, 768, 390 and 320px are under
`/workspace/ctrlnet-v08/cn_frontend_visual_point_table/`. The before probe serves
the saved baseline stylesheet. Focus captures show the type and delete columns
after the browser scrolls the focused control into view. Each probe changes and
restores a point type, then verifies the example calculation still satisfies
its accuracy requirement. The after probe also checks control height, row
highlighting and absence of page-level horizontal overflow.

Full pytest results, existing thesis/GNSS/robust browser regressions and the
independent review are recorded in the same artifact folder. This is a bounded
presentation change and makes no new release or product-maturity claim.
