"""JSON interface to the first-order, metre-based Helmert core."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .helmert import estimate, forward, inverse


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="ctrlnet helmert",
        description="First-order seven-parameter position-vector transform; Cartesian metres only, no CRS conversion.",
    )
    parser.add_argument("operation", choices=["estimate", "forward", "inverse"])
    parser.add_argument("input", type=Path, help="JSON: src/dst/optional weights for estimate; points/params otherwise")
    parser.add_argument("--out", type=Path, help="Output JSON (default stdout)")
    args = parser.parse_args(argv)
    try:
        payload = json.loads(args.input.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("input must be a JSON object")
        if args.operation == "estimate":
            result = estimate(payload["src"], payload["dst"], payload.get("weights"))
            output = {"params": result.params.tolist(), "covariance": result.covariance.tolist(),
                      "residuals": result.residuals.tolist(), "sigma0_sq": result.sigma0_sq}
        else:
            transform = forward if args.operation == "forward" else inverse
            output = {"points": transform(payload["points"], payload["params"]).tolist()}
        output.update({"operation": args.operation, "model": "first-order position-vector",
                       "coordinate_unit": "metre", "parameter_units": ["m", "m", "m", "rad", "rad", "rad", "ppm"]})
        content = json.dumps(output, indent=2, allow_nan=False) + "\n"
    except (OSError, ValueError, KeyError, TypeError, OverflowError) as exc:
        parser.error(str(exc))
    if args.out:
        args.out.write_text(content, encoding="utf-8")
    else:
        print(content, end="")
    return 0
