"""Non-promoting PN repeat observations and lossless failure-pair capture."""
import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import math
import os
from pathlib import Path
import tempfile
from uuid import uuid4

from .contract import DEFAULT, canonical, digest
from .replay import compare, read_record
from .service import ROOT, run_solver


def source_hashes():
    return {str(path.relative_to(ROOT)).replace('\\', '/'): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in sorted((ROOT / 'backend/app/experimental').glob('*.py'))}


def difference(before, after):
    """Compare canonical values too: -0.0, 0.0 and int/float encodings differ."""
    fields = {}
    for key in sorted(set(before) | set(after)):
        if key not in before or key not in after:
            fields[key] = {"shapeChanged": True}
            continue
        if canonical(before[key]) == canonical(after[key]):
            continue
        examples = []; count = 0; maximum = 0.0; relative = 0.0; shape = False

        def walk(a, b, path):
            nonlocal count, maximum, relative, shape
            if canonical(a) == canonical(b):
                return
            if isinstance(a, list) and isinstance(b, list) and len(a) == len(b):
                for i, (x, y) in enumerate(zip(a, b)): walk(x, y, f'{path}/{i}')
            elif isinstance(a, dict) and isinstance(b, dict) and set(a) == set(b):
                for name in sorted(a): walk(a[name], b[name], f'{path}/{name}')
            else:
                count += 1
                if type(a) in (int, float) and type(b) in (int, float) and math.isfinite(a) and math.isfinite(b):
                    delta = abs(a-b); maximum = max(maximum, delta)
                    relative = max(relative, delta/max(abs(a), abs(b))) if a or b else relative
                elif type(a) != type(b) or isinstance(a, (dict, list)):
                    shape = True
                if len(examples) < 3:
                    examples.append({"path":path, "before":a if not isinstance(a,(dict,list)) else "structured-value",
                                     "after":b if not isinstance(b,(dict,list)) else "structured-value"})
        walk(before[key], after[key], '/'+key)
        fields[key] = {"changedLeaves":count, "maxAbsoluteDifference":maximum,
                       "maxRelativeDifference":relative, "shapeChanged":shape, "examples":examples}
    try:
        replay = compare(before, after)
    except (ValueError, KeyError, TypeError, IndexError, OverflowError):
        replay = {"numericallyReproduced":False, "comparisonRejected":True, "productApproved":False}
    return {"canonicalEqual":canonical(before)==canonical(after), "fields":fields, "replay":replay}


def write_new(path, value):
    with Path(path).open('xb') as stream:
        stream.write(canonical(value)); stream.flush(); os.fsync(stream.fileno())


def capture_failure(before, after, directory=None):
    """Never replace the original assertion; retain exact records for diagnosis."""
    base = Path(directory or os.environ.get('OPENTCAD_NUMERICAL_EVIDENCE_DIR') or tempfile.gettempdir())
    base.mkdir(parents=True, exist_ok=True)
    output = base / ('pn-repeat-failure-'+uuid4().hex)
    output.mkdir()
    write_new(output/'before.json', before)
    write_new(output/'after.json', after)
    # Verify the on-disk bytes through the same result-integrity reader as replay.
    a, b = read_record(output/'before.json'), read_record(output/'after.json')
    write_new(output/'comparison.json', {"schemaVersion":1, "classification":"non-promoting-repeat-failure",
              "releaseApproved":False, "sourceAtCapture":source_hashes(), "difference":difference(a,b)})
    return output


async def observe(output, cycles=12, runner=run_solver):
    output = Path(output)
    if not output.is_absolute() or type(cycles) is not int or not 1 <= cycles <= 50:
        raise ValueError('observation-options')
    output.mkdir(parents=True, exist_ok=False)
    before = source_hashes(); first = {}; records = []; comparisons = []
    started = datetime.now(timezone.utc).isoformat()
    try:
        for index in range(cycles*4):
            intervals = (100,200,400,200)[index%4]
            result = await runner(dict(DEFAULT, intervals=intervals))
            filename = f'{index:03d}.json'
            write_new(output/filename, result)
            result = read_record(output/filename)
            records.append({"file":filename, "intervals":intervals, "resultSha256":result['resultSha256']})
            if intervals in first:
                baseline_file, baseline = first[intervals]
                delta = difference(baseline, result)
                comparisons.append({"before":baseline_file, "after":filename, "difference":delta})
            else:
                first[intervals] = (filename, result)
        after = source_hashes()
        stable = before == after
        exact = all(item['difference']['canonicalEqual'] for item in comparisons)
        numeric = all(item['difference']['replay']['numericallyReproduced'] for item in comparisons)
        report = {"schemaVersion":1, "classification":"non-promoting-pn-repeat-observation",
                  "startedAt":started, "finishedAt":datetime.now(timezone.utc).isoformat(),
                  "status":"observed-stable" if stable and exact and numeric else "differences-observed",
                  "sourceBefore":before, "sourceAfter":after, "sourceStable":stable,
                  "byteIdenticalWithinEachInput":exact, "numericallyReproducedWithinEachInput":numeric,
                  "records":records, "comparisons":comparisons, "releaseApproved":False,
                  "historicalIssueCleared":False}
        report['reportSha256'] = digest(report)
        write_new(output/'report.json', report)
        return report
    except BaseException:
        write_new(output/'failure.json', {"schemaVersion":1, "status":"incomplete", "completedRecords":records,
                  "sourceBefore":before, "sourceAfter":source_hashes(), "releaseApproved":False})
        raise


def main():
    parser = argparse.ArgumentParser(description='Retain PN repeat results; no automatic release approval')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--cycles', type=int, default=12)
    args = parser.parse_args()
    try:
        report = asyncio.run(observe(args.output, args.cycles))
        print(canonical({"status":report['status'], "records":len(report['records']),
                         "reportSha256":report['reportSha256'], "releaseApproved":False}).decode())
        return 0 if report['status']=='observed-stable' else 1
    except Exception:
        print('PN observation failed; preserve any partial output and check installation and arguments.')
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
