"""Recompute a saved laboratory result and compare numerical arrays."""
import argparse
import asyncio
import json
import math
from pathlib import Path

from .contract import MODEL, digest, validate_job_input
from .mos_contract import MODEL as MOS_MODEL
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
    if not isinstance(record, dict) or (record.get("model"),record.get("format")) not in ((MODEL,"opentcad-solver-result"),(MOS_MODEL,"opentcad-mos-result")) or record.get("schemaVersion") != 1 or record.get("productApproved") is not False:
        raise ValueError("record-format")
    inputs = validate_job_input(record["input"])
    result_hash = record.pop("resultSha256")
    if digest(record) != result_hash or digest(inputs) != record["inputSha256"]:
        raise ValueError("record-integrity")
    record["resultSha256"] = result_hash
    return record

def compare(previous, current):
    if previous["model"] != current["model"] or previous["input"] != current["input"] or previous["templateSha256"] != current["templateSha256"] or previous["solverVersion"] != current["solverVersion"]:
        raise ValueError("model-version-mismatch")
    if previous["model"]==MOS_MODEL:
        return compare_mos(previous,current)
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

def compare_mos(previous,current):
    if previous["dopingSource"]!=current["dopingSource"]: raise ValueError("process-source-mismatch")
    passed=True
    tolerances={"xUm":1e-12,"yUm":1e-12,"potentialV":1e-8,"electronsCm3":1e-3,"holesCm3":1e-3,"netDopingCm3":1e-3}
    for region in ("silicon","oxide"):
        a,b=previous["regions"][region],current["regions"][region]
        if a["triangles"]!=b["triangles"]: passed=False
        for key in a:
            if key=="triangles":continue
            if len(a[key])!=len(b[key]) or not all(math.isclose(x,y,rel_tol=1e-7,abs_tol=tolerances[key]) for x,y in zip(a[key],b[key])):passed=False
    if len(previous["iv"])!=len(current["iv"]) or not all(math.isclose(x,y,rel_tol=1e-7,abs_tol=1e-12) for a,b in zip(previous["iv"],current["iv"]) for x,y in zip(a,b)):passed=False
    return {"numericallyReproduced":passed,"byteIdentical":previous["resultSha256"]==current["resultSha256"],"relativeTolerance":1e-7,"absoluteTolerances":{**tolerances,"iv":1e-12},"productApproved":False}

def main():
    parser = argparse.ArgumentParser(description="Recompute a saved experimental result; never grants product approval")
    parser.add_argument("record", type=Path)
    parser.add_argument("--suprem-structure",type=Path)
    args = parser.parse_args()
    try:
        previous = read_record(args.record)
        from .suprem import read_structure
        profile=read_structure(args.suprem_structure) if args.suprem_structure else None
        if previous["input"].get("dopingMode")=="suprem" and (profile is None or profile["sourceSha256"]!=previous["dopingSource"]["sourceSha256"]):
            raise ValueError("replay-process-source")
        current = asyncio.run(run_solver(previous["input"],process_profile=profile))
        report = compare(previous, current)
        print(json.dumps(report, sort_keys=True))
        return 0 if report["numericallyReproduced"] else 1
    except Exception:
        print("Replay failed: check input format, hash integrity, template version and solver installation.")
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
