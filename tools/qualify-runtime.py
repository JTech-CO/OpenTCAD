"""Emit a redacted OpenTCAD runtime qualification observation for one host."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
from typing import Any


BACKENDS = ("docker", "podman")
CONTRACT_TESTS = (
    "backend.tests.product.test_gates",
    "backend.tests.runtime.test_oci_backend",
    "backend.tests.service.test_credentials",
    "backend.tests.service.test_anti_rollback",
    "backend.tests.service.test_worker_scheduler",
    "backend.tests.service.test_local_api",
    "backend.tests.service.test_application",
)


def command(arguments: tuple[str, ...], timeout: int = 30) -> dict[str, Any]:
    environment = {
        key: os.environ[key]
        for key in (
            "PATH",
            "HOME",
            "USERPROFILE",
            "SYSTEMROOT",
            "COMSPEC",
            "DOCKER_CONFIG",
            "XDG_RUNTIME_DIR",
        )
        if key in os.environ
    }
    environment["LANG"] = "C"
    environment["LC_ALL"] = "C"
    try:
        completed = subprocess.run(
            arguments,
            capture_output=True,
            timeout=timeout,
            check=False,
            env=environment,
        )
        return {
            "returnCode": completed.returncode,
            "stdout": completed.stdout[:1_048_576],
            "stderr": completed.stderr[:1_048_576],
        }
    except (OSError, subprocess.TimeoutExpired):
        return {"returnCode": None, "stdout": b"", "stderr": b""}


def json_value(raw: bytes) -> dict[str, Any] | None:
    try:
        value = json.loads(raw.decode("utf-8"))
        return value if isinstance(value, dict) else None
    except (UnicodeError, json.JSONDecodeError):
        return None


def inspect_backend(name: str) -> dict[str, Any]:
    executable = shutil.which(name)
    if executable is None:
        return {
            "installed": False,
            "daemonReachable": False,
            "runtimeInfoEligible": False,
            "nativeConformancePassed": False,
            "serverVersion": None,
            "serverOs": None,
            "serverArchitecture": None,
            "qualified": False,
            "reason": "cli-not-installed",
        }
    info = command((executable, "info", "--format", "{{json .}}"))
    value = json_value(info["stdout"]) if info["returnCode"] == 0 else None
    if value is None:
        return {
            "installed": True,
            "daemonReachable": False,
            "runtimeInfoEligible": False,
            "nativeConformancePassed": False,
            "serverVersion": None,
            "serverOs": None,
            "serverArchitecture": None,
            "qualified": False,
            "reason": "daemon-unavailable-or-invalid-info",
        }
    if name == "docker":
        version = value.get("ServerVersion")
        operating_system = value.get("OSType")
        architecture = value.get("Architecture")
    else:
        host = value.get("host")
        version_value = value.get("version")
        version = (
            version_value.get("version")
            if isinstance(version_value, dict)
            else version_value
        )
        operating_system = host.get("os") if isinstance(host, dict) else None
        architecture = host.get("arch") if isinstance(host, dict) else None
    runtime_info_eligible = (
        isinstance(version, str)
        and bool(version)
        and str(operating_system).casefold() == "linux"
        and str(architecture).casefold()
        in {"amd64", "x86_64", "arm64", "aarch64"}
    )
    return {
        "installed": True,
        "daemonReachable": True,
        "serverVersion": version if isinstance(version, str) else None,
        "serverOs": operating_system if isinstance(operating_system, str) else None,
        "serverArchitecture": architecture if isinstance(architecture, str) else None,
        "runtimeInfoEligible": runtime_info_eligible,
        "nativeConformancePassed": False,
        "qualified": False,
        "reason": (
            "native-conformance-not-run"
            if runtime_info_eligible
            else "unsupported-runtime-host"
        ),
    }


def approved_images(root: Path) -> list[dict[str, Any]]:
    value = json.loads(
        (root / "validation" / "manifests" / "image-lock.json").read_text(
            encoding="utf-8",
        ),
    )
    images = value.get("images")
    if not isinstance(images, list):
        return []
    return [
        image
        for image in images
        if isinstance(image, dict)
        and image.get("releaseApproved") is True
        and isinstance(image.get("digest"), str)
        and isinstance(image.get("sbomSha256"), str)
        and image.get("licenseReview") == "approved"
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    arguments = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = Path(arguments.output).resolve()
    if root not in output.parents or not output.parent.is_dir():
        raise SystemExit("output must be an existing repository directory")

    contract = command(
        (sys.executable, "-m", "unittest", *CONTRACT_TESTS),
        timeout=180,
    )
    backends = {name: inspect_backend(name) for name in BACKENDS}
    images = approved_images(root)
    qualified = (
        contract["returnCode"] == 0
        and all(value["qualified"] for value in backends.values())
        and bool(images)
    )
    record = {
        "schemaVersion": 1,
        "evidenceType": "runtime-host-observation",
        "observedAt": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "host": {
            "system": platform.system().casefold(),
            "release": platform.release(),
            "machine": platform.machine().casefold(),
            "python": platform.python_version(),
        },
        "contractSuite": {
            "modules": list(CONTRACT_TESTS),
            "passed": contract["returnCode"] == 0,
        },
        "backends": backends,
        "approvedImageCount": len(images),
        "qualified": qualified,
        "status": "passed" if qualified else "blocked",
    }
    output.write_text(
        json.dumps(record, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(json.dumps({"output": output.name, "status": record["status"]}))
    return 0 if qualified else 2


if __name__ == "__main__":
    raise SystemExit(main())
