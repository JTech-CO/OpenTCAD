"""Recompute a saved laboratory result and compare numerical arrays."""
import argparse
import asyncio
import json
import math
from pathlib import Path

from .contract import MODEL, digest, validate_input
from .service import run_solver

def read_record(path):
    with Path(path).open("rb") as handle:
        source = handle.read(1_048_577)
    if len(source) > 1_048_576:
        raise ValueError("record-size")
    def pairs(items):
        output = {}
        for key, value in items:
            if key in output:
                raise ValueError("duplicate-key")
            output[key] = value
        return output
    record = json.loads(source, object_pairs_hook=pairs)
    if not isinstance(record, dict) or record.get("format") != "opentcad-solver-result" or record.get("model") != MODEL or record.get("schemaVersion") != 1 or record.get("productApproved") is not False:
        raise ValueError("record-format")
    inputs = validate_input(record["input"])
    result_hash = record.pop("resultSha256")
    if digest(record) != result_hash or digest(inputs) != record["inputSha256"]:
        raise ValueError("record-integrity")
    record["resultSha256"] = result_hash
    return record

def compare(previous, current):
    if previous["model"] != current["model"] or previous["input"] != current["input"] or previous["templateSha256"] != current["templateSha256"] or previous["solverVersion"] != current["solverVersion"]:
        raise ValueError("model-version-mismatch")
    # Absolute tolerances in the recorded units, plus relative 1e-8.
    tolerances = {"iv": 1e-14, "xUm": 1e-12, "potentialV": 1e-9,
                  "equilibriumPotentialV": 1e-9, "electronsCm3": 1e-4,
                  "holesCm3": 1e-4, "netDopingCm3": 1e-4}
    def flatten(values):
        for value in values:
            if isinstance(value, list):
                yield from flatten(value)
            else:
                yield value
    passed = True
    for key, tolerance in tolerances.items():
        a, b = list(flatten(previous[key])), list(flatten(current[key]))
        if len(a) != len(b) or not all(type(x) in (int, float) and type(y) in (int, float) and math.isfinite(x) and math.isfinite(y) and math.isclose(x, y, rel_tol=1e-8, abs_tol=tolerance) for x, y in zip(a, b)):
            passed = False
    return {"numericallyReproduced": passed, "byteIdentical": previous["resultSha256"] == current["resultSha256"],
            "relativeTolerance": 1e-8, "absoluteTolerances": tolerances, "productApproved": False}

def main():
    parser = argparse.ArgumentParser(description="Recompute a saved experimental result; never grants product approval")
    parser.add_argument("record", type=Path)
    args = parser.parse_args()
    try:
        previous = read_record(args.record)
        current = asyncio.run(run_solver(previous["input"]))
        report = compare(previous, current)
        print(json.dumps(report, sort_keys=True))
        return 0 if report["numericallyReproduced"] else 1
    except Exception:
        print("Replay failed: check input format, hash integrity, template version and solver installation.")
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
