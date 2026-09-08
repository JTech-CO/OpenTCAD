"""Windows-first source-only MVP candidate, independent of M3 activation."""
import argparse
import asyncio
import importlib.metadata
import json
import os
from pathlib import Path
import stat
import sys

from backend.app.service.instance import LocalInstance
from .contract import canonical
from .history import History, read_backup
from .service import ROOT, serve


def safe_path(path):
    path = Path(path)
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("absolute-local-path-required")
    for part in (path, *path.parents):
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400):
            raise ValueError("linked-path-not-supported")
    return path


def doctor(assets):
    dependencies = []
    for line in (ROOT / "backend/app/experimental/requirements.txt").read_text().splitlines():
        requirement = line.split(";", 1)[0].strip()
        if not requirement:
            continue
        name, expected = requirement.split("==")
        try:
            installed = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            installed = None
        dependencies.append({"name":name, "expected":expected, "installed":installed, "match":installed == expected})
    checks = {"windowsHost":sys.platform == "win32", "pythonSupported":(3, 12) <= sys.version_info[:2] <= (3, 14),
              "builtFrontend":(Path(assets) / "index.html").is_file(),
              "pinnedDependencies":all(item["match"] for item in dependencies)}
    return {"schemaVersion":1, "releaseTrack":"windows-local-mvp", "releaseStatus":"candidate",
            "prerequisitesReady":all(checks.values()), "checks":checks, "dependencies":dependencies,
            "m3Approved":False, "productEnabled":False, "solverDistribution":"user-installed-only",
            "physicalPowerLoss":"unverified", "macosLinuxQualification":"deferred",
            "backupProtection":"checksum-only-offline", "antiRollbackQualified":False}


def parser():
    result = argparse.ArgumentParser(description="Windows local MVP candidate; does not grant M3 approval")
    result.add_argument("command", choices=("doctor", "serve", "history", "export", "backup", "verify-backup", "restore"))
    result.add_argument("--state-directory", type=Path)
    result.add_argument("--file", type=Path, help="Explicit new output, or backup input for verify/restore")
    result.add_argument("--job-id")
    result.add_argument("--assets", type=Path, default=ROOT / "frontend/dist")
    result.add_argument("--port", type=int, default=0)
    result.add_argument("--suprem-structure", type=Path)
    result.add_argument("--suprem-contacts", type=Path)
    return result


def run(args):
    if args.command == "doctor":
        report = doctor(args.assets)
        print(json.dumps(report, sort_keys=True))
        return 0 if report["prerequisitesReady"] else 1
    if sys.platform != "win32":
        raise ValueError("windows-only-release-track")
    if args.command in {"export", "backup", "verify-backup", "restore"} and args.file is None:
        raise ValueError("file-required")
    if args.file is not None:
        args.file = safe_path(args.file)
    if args.command == "verify-backup":
        records = read_backup(args.file)
        print(json.dumps({"checksumValid":True, "records":len(records), "authenticated":False, "m3Approved":False}))
        return 0
    if args.state_directory is None:
        base = os.environ.get("LOCALAPPDATA")
        if not base:
            raise ValueError("local-app-data-unavailable")
        args.state_directory = Path(base) / "OpenTCAD/windows-mvp"
    directory = safe_path(args.state_directory)
    restored = None
    if args.command == "restore":
        restored = read_backup(args.file)
        if directory.exists():
            raise ValueError("restore-requires-new-directory")
    elif args.command in {"history", "backup", "export"} and not (directory / "history.sqlite3").is_file():
        raise ValueError("history-not-found")
    if args.command == "serve":
        if not doctor(args.assets)["prerequisitesReady"]:
            raise ValueError("run-doctor-first")
        from .windows_job import contain_current_process
        parent = os.environ.get("OPENTCAD_MVP_PARENT_PID")
        contain_current_process(int(parent) if parent else None)
    directory.mkdir(parents=True, exist_ok=args.command != "restore")
    for name in ("history.sqlite3", "instance.lock", "unused-endpoint.json"):
        safe_path(directory / name)
    with LocalInstance(directory / "instance.lock", directory / "unused-endpoint.json"):
        store = History(directory / "history.sqlite3")
        try:
            if args.command == "serve":
                print("Windows local MVP candidate. Offline history enabled; physical power-loss and M3 approval remain unverified.", flush=True)
                asyncio.run(serve(args, store=store))
            elif args.command == "history":
                print(json.dumps({"jobs":[{k:v for k,v in row.items() if k != "result"} for row in store.load().values()]}))
            elif args.command == "export":
                record = store.load().get(args.job_id)
                if record is None or record["state"] != "complete":
                    raise ValueError("complete-job-required")
                with args.file.open("xb") as stream:
                    stream.write(canonical(record["result"]))
                    stream.flush(); os.fsync(stream.fileno())
                print(json.dumps({"exported":True, "resultSha256":record["result"]["resultSha256"]}))
            elif args.command == "backup":
                print(json.dumps({"sha256":store.backup(args.file), "authenticated":False}))
            elif args.command == "restore":
                store.restore(restored)
                print(json.dumps({"restored":len(restored), "automaticallyExecuted":False, "m3Approved":False}))
        finally:
            store.close()
    return 0


def main():
    try:
        return run(parser().parse_args())
    except KeyboardInterrupt:
        return 0
    except Exception:
        print("Windows MVP command failed. Check prerequisites, exclusive state directory, file integrity and command arguments.", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
