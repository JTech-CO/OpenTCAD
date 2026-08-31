"""Cross-platform command line for M3 doctor, blocked preview, and product serve."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import signal
import sys
import webbrowser

from backend.app.product.gates import ProductGateError
from backend.app.product.release_profile import ProductReleaseProfile

from .bootstrap import M3LocalProductBootstrap
from .configuration import LocalUserConfiguration
from .instance import (
    LocalEndpointRecord,
    LocalInstance,
    LocalInstanceAlreadyRunning,
)
from .local_api import LocalApiBind
from .paths import LocalProductPaths
from .static_assets import LocalStaticAssets


EXIT_INVALID = 2
EXIT_BLOCKED = 3
EXIT_ALREADY_RUNNING = 4
EXIT_START_FAILED = 5


def _repository_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _emit(value: dict[str, object]) -> None:
    print(json.dumps(value, sort_keys=True, separators=(",", ":")))


def _doctor(bootstrap: M3LocalProductBootstrap) -> int:
    report = bootstrap.report
    _emit(
        {
            "schemaVersion": 1,
            "command": "doctor",
            "productEnabled": report.product_enabled,
            "ready": report.ready,
            "manifestSha256": report.manifest_sha256,
            "blockedGates": [item.value for item in report.blocked_gate_ids],
            "runtimeGrantCount": len(report.runtime_grants),
        },
    )
    return 0


async def _stop_event() -> asyncio.Event:
    event = asyncio.Event()
    loop = asyncio.get_running_loop()

    def stop() -> None:
        event.set()

    signals = [signal.SIGINT, signal.SIGTERM]
    if hasattr(signal, "SIGBREAK"):
        signals.append(signal.SIGBREAK)
    for item in signals:
        try:
            loop.add_signal_handler(item, stop)
        except (NotImplementedError, RuntimeError, ValueError):
            try:
                signal.signal(item, lambda *_: loop.call_soon_threadsafe(stop))
            except (OSError, RuntimeError, ValueError):
                pass
    return event


async def _preview(
    bootstrap: M3LocalProductBootstrap,
    assets: LocalStaticAssets,
    port: int,
    open_browser: bool,
) -> int:
    event = await _stop_event()
    host = bootstrap.preview(assets, LocalApiBind("127.0.0.1", port))
    await host.start()
    try:
        url = host.browser_url
        _emit(
            {
                "schemaVersion": 1,
                "mode": "preview",
                "port": host.port,
                "browserUrl": url,
                "solverExecution": False,
            },
        )
        if open_browser:
            webbrowser.open(url, new=1, autoraise=True)
        await event.wait()
        return 0
    finally:
        await host.close()


async def _serve(
    bootstrap: M3LocalProductBootstrap,
    configuration: LocalUserConfiguration,
    profile: ProductReleaseProfile,
    paths: LocalProductPaths,
    assets: LocalStaticAssets,
    open_browser: bool,
) -> int:
    # Activation and the code-owned profile were checked before asset lookup.
    event = await _stop_event()
    paths.prepare()
    instance = LocalInstance(paths.instance_lock, paths.endpoint_file)
    try:
        instance.acquire()
    except LocalInstanceAlreadyRunning:
        return EXIT_ALREADY_RUNNING
    service = None
    try:
        service = await bootstrap.build_activated(
            configuration,
            paths,
            assets,
            profile=profile,
        )
        await service.start()
        instance.publish(
            LocalEndpointRecord(
                service.startup_id,
                os.getpid(),
                service.port,
                bootstrap.report.manifest_sha256,
                "product",
            ),
        )
        url = service.browser_url
        _emit(
            {
                "schemaVersion": 1,
                "mode": "product",
                "port": service.port,
                "browserUrl": url,
                "solverExecution": True,
            },
        )
        if open_browser:
            webbrowser.open(url, new=1, autoraise=True)
        await event.wait()
        return 0
    finally:
        if service is not None:
            await service.close()
        instance.close()


def _parser(root: Path) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="opentcad-local")
    parser.add_argument(
        "--manifest",
        type=Path,
        default=root / "validation" / "manifests" / "m3-entry-gates.json",
    )
    subcommands = parser.add_subparsers(dest="command", required=True)
    subcommands.add_parser("doctor")
    preview = subcommands.add_parser("preview")
    preview.add_argument("--assets", type=Path, default=root / "frontend" / "dist")
    preview.add_argument("--port", type=int, default=0)
    preview.add_argument("--open-browser", action="store_true")
    serve = subcommands.add_parser("serve")
    serve.add_argument("--assets", type=Path, default=root / "frontend" / "dist")
    serve.add_argument("--config", type=Path)
    serve.add_argument("--data-root", type=Path)
    serve.add_argument("--open-browser", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    root = _repository_root()
    args = _parser(root).parse_args(argv)
    try:
        bootstrap = M3LocalProductBootstrap(root, args.manifest)
        if args.command == "doctor":
            return _doctor(bootstrap)
        if args.command == "preview":
            assets = LocalStaticAssets(args.assets)
            if args.port != 0 and not 1_024 <= args.port <= 65_535:
                raise ValueError("Preview port must be 0 or 1024 through 65535.")
            return asyncio.run(
                _preview(bootstrap, assets, args.port, args.open_browser),
            )
        # Preserve this order: manifest, operator config, code-owned profile,
        # assets, then all stateful host integration.
        bootstrap.require_activation()
        paths = (
            LocalProductPaths.at_root(args.data_root.resolve())
            if args.data_root is not None
            else LocalProductPaths.for_platform()
        )
        configuration_path = args.config or paths.configuration_file
        configuration = LocalUserConfiguration.load(configuration_path)
        profile = bootstrap.require_release_profile(configuration)
        assets = LocalStaticAssets(args.assets)
        return asyncio.run(
            _serve(
                bootstrap,
                configuration,
                profile,
                paths,
                assets,
                args.open_browser,
            ),
        )
    except ProductGateError as error:
        _emit(
            {
                "schemaVersion": 1,
                "error": error.code.value,
                "productStarted": False,
            },
        )
        return EXIT_BLOCKED
    except (OSError, PermissionError, RuntimeError, TypeError, ValueError) as error:
        _emit(
            {
                "schemaVersion": 1,
                "error": type(error).__name__,
                "productStarted": False,
            },
        )
        return EXIT_INVALID if isinstance(error, (TypeError, ValueError)) else EXIT_START_FAILED
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
