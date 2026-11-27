# Dashboard registration summary cards

Candidate: `dashboard_registration_cards` (`cn_frontend_visual`, new work).

Registration counts and RMS values now use larger, aligned label/value typography,
more card spacing, and a full-width 40px reload action. Two flexible columns and
wrapped values retain readability on narrow screens. No calculation changes.

Evidence: `/workspace/ctrlnet-v08/cn_frontend_visual_registration/` contains Chromium
before/after screenshots at 1440, 1024, 390 and 320px, full pytest output,
GNSS/robust e2e regression output and independent review. The focused browser
script reloads real registration data and checks populated metrics and containment.

Existing v0.8 acceptance and recorded product gaps remain unchanged.
