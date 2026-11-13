# Selected angle addition merge

One bounded post-v0.8 topology gap: selected angle additions between common existing points now merge by stable ID. The network object stays indivisible; competing settings offer target/source choices, and either choice retains accepted additions. Target order, allocator high-water marks, coordinate edits, recomputed geometry and dual-parent provenance are preserved.

Selected deletions, delete-versus-edit, new/deleted point references, competing added IDs/names, duplicate ordered triples and unknown authored fields remain conservative. Ambiguous merge bases remain unsupported. Accepted v0.8 is unchanged; this is not a production maturity claim.

Validation:
- Full pytest: 620 passed, 1 skipped, 2 xfailed, 8 warnings in 56.72s.
- Focused HTTP/Chromium: PASS; divergent coordinate branch, selected addition, preview/merge, restart/reopen, persisted selection and generated angle observation, recomputed value, target order, dual parents, fresh allocation and no page errors.
- Independent review: PASS; 231 focused tests and separate Chromium rerun.

Initial failures are retained in external stage evidence: obsolete selected-addition conflict expectation, missing configured browser, and benchmark subprocess missing the source import path. The expectation now tests supported behavior; final pytest used PYTHONPATH=/workspace/ctrlnet-design/src and /tmp/cn-angle-venv/bin/python. Browser used CHROMIUM_EXECUTABLE=/usr/bin/google-chrome. No test exclusions were added.

Stage evidence: /workspace/ctrlnet-v08/cn_post_v08_selected_angle_addition (pytest-final.txt, e2e.json, review.md and independent rerun artifacts). Sample database SHA256 matches HEAD: fa597f57b5952fa603b9464550c5d72e9c7c2b6bd4efc48c8281692b84a204f6. Prior evidence and unrelated worktree dirt preserved; no cc-gins changes.
