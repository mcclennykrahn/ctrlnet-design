# Untagged install/release preparation

One bounded portion of the production install/release gap: isolated sdist-to-wheel
build into an empty output directory, SHA256SUMS, source revision/dirty-state
metadata, and a fresh installed-wheel smoke test outside the checkout.
No version change, tag, package-index publication or production certification.

Validation on Linux / Python 3.13.5:
- Full pytest: 393 passed, 1 skipped, 2 xfailed, 8 warnings in 26.23s.
- Isolated build: wheel and sdist built successfully.
- Fresh venv e2e: checksums, pip check, three CLI entries, sample-copy adjustment,
  actual HTTP health and bundled HTML/Leaflet assets PASS.
- Independent review: PASS; independently checked overwrite refusal, hashes,
  required wheel assets and absence of runner/demo dirt from sdist.
- Sample SQLite SHA256 unchanged:
  fa597f57b5952fa603b9464550c5d72e9c7c2b6bd4efc48c8281692b84a204f6.

Initial pytest: 1 failed, 392 passed, 1 skipped, 2 xfailed. The benchmark child
uses the repo's incomplete .venv/bin/python symlink and could not import ctrlnet.
Full rerun passed with PYTHONPATH pointing to src and the shared venv's
site-packages. No environment files were changed. The fresh-wheel e2e removes
PYTHON* / CTRLNET overrides and uses a real fresh venv, independently of this
regression-environment workaround.

Evidence: /workspace/ctrlnet-v08/cn_post_v08_release/{build.txt,pytest.txt,
pytest_attempt1.txt,e2e.txt,review.md,bundle/}. The candidate records baseline
HEAD and worktree_dirty=true; it is not an exact clean-commit release.

Remaining release work: target-platform/offline wheelhouse verification, signed
and published/tagged distribution, deployment operations and verified rollback.
Existing v0.8 acceptance and all prior evidence remain unchanged.
