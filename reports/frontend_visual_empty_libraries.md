# Empty library guidance

Candidate `thesis_empty_library_guidance` gives the empty point, line and angle tables a bordered, pale green message with a clear title, 13px instructions and roomier spacing. Existing IDs and hidden-state behavior remain intact; JavaScript is unchanged. The extra spacing increases empty-panel height.

Evidence lives at `/workspace/ctrlnet-v08/cn_frontend_visual_empty_libraries`: Chromium before/after crops at 1440, 900, 390 and 320px, baseline source, capture script and scoped patch. Captures reset the project at each width, assert all empty messages are visible and wait for the reset toast to disappear. Loading example 1 verifies that the messages hide again. An initial independent review rejected the responsive evidence because later views retained the example; corrected captures were submitted for re-review.

Validation results and final independent verdict are recorded with the delivery artifacts. Existing acceptance and remaining gaps are unchanged.
