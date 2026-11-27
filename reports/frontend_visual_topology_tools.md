# Thesis topology controls

Candidate `thesis_topology_tools` groups JSON import and export above the
snapping and history controls. The file actions stack on narrow screens.
The two snapping inputs align, with the units and zero-value behavior beneath
each label. Undo and redo use the same button style as the rest of the editor.

The Chromium probe captures before and after views at 1440, 900, 390 and
320px. At each width it exports the example topology, imports it into an empty
project, then exercises undo, redo and both snapping inputs. The updated view
also checks control height and horizontal bounds.

The captures, independent review, full pytest output and thesis, GNSS, robust
estimation and snap/history browser regressions are recorded under
`/workspace/ctrlnet-v08/cn_frontend_visual_topology_tools/`.

Independent review and all browser checks passed. Pytest reported 1,274 passed,
one skipped and two expected failures.
