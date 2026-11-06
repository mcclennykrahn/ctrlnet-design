# Post-v0.8 seven-parameter CLI

One bounded addition: `ctrlnet helmert estimate|forward|inverse` exposes the
existing first-order Cartesian position-vector core through JSON. Parameters,
covariance, residuals, variance, convention and units are explicit. Invalid
input fails before writing the requested output. No changes to adjustment math.

Focused subprocess e2e uses independently calculated coordinates and exercises
fit → forward → inverse; invalid and degenerate inputs preserve existing output.
Independent review PASS (/root/review); independent CLI + core tests: 17 passed.
Full-suite outcome is recorded in the stage artifact and manifest.

Arbitrary CRS conversion and 3D web-editor workflows remain gaps. This does not
change accepted v0.8 status or claim production maturity. Prior documentation
deletions, runner files and demo databases were excluded from this commit.
