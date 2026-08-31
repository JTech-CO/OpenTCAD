"""Fail-closed assembly for preview and activated local product hosts."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, replace
import json
import os
from pathlib import Path
import secrets
import time
from typing import Callable
from uuid import UUID, uuid4, uuid5

from backend.app.broker.backup_control import (
    BackupControlError,
    BackupControlErrorCode,
    BackupScheduleDefinition,
    SQLiteBackupControlStore,
)
from backend.app.broker.durability import DurablePublicationError, sync_file
from backend.app.broker.orchestrator import SandboxBroker
from backend.app.broker.sqlite_snapshot import SQLiteOfflineSnapshotManager
from backend.app.broker.sqlite_state import SQLiteJobStateStore
from backend.app.product.gates import M3ProductGate, ProductGateReport
from backend.app.product.release_profile import (
    ProductReleaseProfile,
    release_profile_for,
)
from backend.app.runtime.models import RuntimeHealth
from backend.app.runtime.oci_backend import OciRuntimeBackend
from backend.app.runtime.product_fence_authority import ProductRuntimeFenceAuthority

from .application import LocalServiceConfiguration, OpenTcadLocalService
from .configuration import LocalUserConfiguration
from .credentials import (
    CredentialStoreError,
    CredentialStoreErrorCode,
    NativeCredentialStore,
    load_or_create_secret,
    native_credential_store,
)
from .local_api import LocalApiBind, LocalApiServer
from .paths import LocalProductPaths
from .product_composition import ProductDurableBrokerComposition
from .static_assets import LocalStaticAssets
from .status import LocalProductStatus


@dataclass(frozen=True, slots=True)
class _InstallationRecord:
    installation_id: str
    credentials_provisioned: bool

    def __post_init__(self) -> None:
        try:
            parsed = UUID(self.installation_id)
        except (AttributeError, TypeError, ValueError) as error:
            raise TypeError("Installation ID is invalid.") from error
        if str(parsed) != self.installation_id or not isinstance(
            self.credentials_provisioned,
            bool,
        ):
            raise TypeError("Installation record is invalid.")

    def as_dict(self) -> dict[str, object]:
        return {
            "schemaVersion": 1,
            "installationId": self.installation_id,
            "credentialsProvisioned": self.credentials_provisioned,
        }


def _write_installation(path: Path, record: _InstallationRecord) -> None:
    raw = (
        json.dumps(record.as_dict(), sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("ascii")
    temporary = path.with_name(f".{path.name}.{uuid4()}.tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            sync_file(temporary)
        except DurablePublicationError:
            raise OSError("OpenTCAD installation durability barrier failed.") from None
        if os.name == "nt":
            import ctypes

            move_file = ctypes.WinDLL(
                "kernel32",
                use_last_error=True,
            ).MoveFileExW
            move_file.argtypes = (
                ctypes.c_wchar_p,
                ctypes.c_wchar_p,
                ctypes.c_uint32,
            )
            move_file.restype = ctypes.c_int
            if not move_file(str(temporary), str(path), 0x00000009):
                raise OSError("OpenTCAD installation publication failed.")
        else:
            os.replace(temporary, path)
            descriptor = os.open(
                path.parent,
                os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
            )
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
    finally:
        temporary.unlink(missing_ok=True)


def _installation(paths: LocalProductPaths) -> _InstallationRecord:
    path = paths.installation_file
    if not path.exists():
        databases = (
            paths.state_database,
            paths.fence_database,
            paths.control_database,
        )
        try:
            backup_exists = paths.backup_root.is_dir() and any(
                paths.backup_root.iterdir(),
            )
        except OSError:
            raise RuntimeError("OpenTCAD installation state is unavailable.") from None
        if any(candidate.exists() for candidate in databases) or backup_exists:
            raise RuntimeError(
                "OpenTCAD installation identity is missing for existing state.",
            )
        record = _InstallationRecord(str(uuid4()), False)
        _write_installation(path, record)
        return record
    try:
        if not path.is_file() or path.is_symlink() or path.stat().st_size > 16_384:
            raise ValueError
        value = json.loads(path.read_text(encoding="ascii"))
        if not isinstance(value, dict) or set(value) != {
            "schemaVersion",
            "installationId",
            "credentialsProvisioned",
        } or value["schemaVersion"] != 1:
            raise ValueError
        return _InstallationRecord(
            value["installationId"],
            value["credentialsProvisioned"],
        )
    except (OSError, UnicodeError, json.JSONDecodeError, TypeError, ValueError):
        raise RuntimeError("OpenTCAD installation record is invalid.") from None


def _credentials(
    paths: LocalProductPaths,
    record: _InstallationRecord,
    factory: Callable[[], NativeCredentialStore],
) -> tuple[NativeCredentialStore, _InstallationRecord]:
    store = factory()
    identifiers = ("local-api-v1", "backup-v1")
    if record.credentials_provisioned:
        for identifier in identifiers:
            try:
                value = store.get("opentcad", identifier)
            except CredentialStoreError:
                raise RuntimeError("OpenTCAD credential provisioning is incomplete.") from None
            if not 32 <= len(value) <= 128:
                raise RuntimeError("OpenTCAD credential provisioning is invalid.")
        return store, record
    for identifier in identifiers:
        load_or_create_secret(store, "opentcad", identifier)
    updated = replace(record, credentials_provisioned=True)
    _write_installation(paths.installation_file, updated)
    return store, updated


class BlockedLocalPreviewHost:
    """Same-origin UI host with no broker, runtime, database, or OS credential use."""

    def __init__(
        self,
        report: ProductGateReport,
        assets: LocalStaticAssets,
        bind: LocalApiBind,
    ) -> None:
        if report.product_enabled:
            raise PermissionError("Blocked preview requires a disabled manifest.")
        self._status = LocalProductStatus.blocked(report)
        self._server = LocalApiServer(
            None,
            secrets.token_bytes(32),
            bind,
            static_assets=assets,
            status_provider=lambda: self._status,
        )

    @property
    def port(self) -> int:
        return self._server.port

    @property
    def browser_url(self) -> str:
        return self._server.browser_url

    async def start(self) -> None:
        await self._server.start()

    async def close(self) -> None:
        await self._server.close()


class M3LocalProductBootstrap:
    def __init__(self, repository_root: str | Path, manifest: str | Path) -> None:
        root = Path(repository_root).resolve(strict=True)
        self._root = root
        self._gate = M3ProductGate.load(manifest, repository_root=root)

    @property
    def report(self) -> ProductGateReport:
        return self._gate.report

    def require_activation(self):
        """Checks approval before callers create local state or acquire locks."""

        return self._gate.require_activation()

    def require_release_profile(
        self,
        configuration: LocalUserConfiguration,
    ) -> ProductReleaseProfile:
        """Resolves all code-owned runtime authority before local side effects."""

        if not isinstance(configuration, LocalUserConfiguration):
            raise TypeError("Release profile requires local configuration.")
        activation = self._gate.require_activation()
        selected = release_profile_for(
            activation,
            configuration.runtime_backend,
        )
        selected.verify_activation(activation)
        return selected

    def preview(
        self,
        assets: LocalStaticAssets,
        bind: LocalApiBind = LocalApiBind(),
    ) -> BlockedLocalPreviewHost:
        return BlockedLocalPreviewHost(self.report, assets, bind)

    async def build_activated(
        self,
        configuration: LocalUserConfiguration,
        paths: LocalProductPaths,
        assets: LocalStaticAssets,
        *,
        profile: ProductReleaseProfile | None = None,
        credential_factory: Callable[[], NativeCredentialStore] = native_credential_store,
    ) -> OpenTcadLocalService:
        """Requires activation before creating directories or contacting the host."""

        activation = self._gate.require_activation()
        selected = profile or self.require_release_profile(configuration)
        selected.verify_activation(activation)
        paths.prepare()
        record = _installation(paths)
        authority = ProductRuntimeFenceAuthority(
            paths.fence_database,
            paths.lock_root,
        )
        backend = OciRuntimeBackend(selected.adapter, activation, authority)
        probe = await backend.probe()
        if probe.health is not RuntimeHealth.AVAILABLE or probe.capabilities is None:
            raise RuntimeError("Approved OCI runtime is unavailable.")
        for image in selected.images:
            await backend.ensure_image(image)

        credentials, record = _credentials(paths, record, credential_factory)
        state = SQLiteJobStateStore(paths.state_database)
        composition = ProductDurableBrokerComposition(
            SandboxBroker(backend, selected.policy, selected.archive_limits),
            backend,
            state,
            activation,
        )
        control = SQLiteBackupControlStore(
            paths.control_database,
            record.installation_id,
        )
        schedule_id = str(
            uuid5(UUID(record.installation_id), "scheduled-backup-v1"),
        )
        try:
            schedule = control.current_schedule(schedule_id)
        except BackupControlError as error:
            if error.code is not BackupControlErrorCode.SCHEDULE_NOT_FOUND:
                raise
            control.configure_schedule(
                BackupScheduleDefinition(
                    schedule_id,
                    record.installation_id,
                    configuration.backup_interval_ms,
                    int(time.time() * 1_000) + configuration.backup_interval_ms,
                ),
            )
        else:
            if schedule.definition.interval_ms != configuration.backup_interval_ms:
                raise RuntimeError("Configured backup interval differs from durable state.")
        return OpenTcadLocalService(
            LocalServiceConfiguration(
                record.installation_id,
                str(uuid4()),
                paths.backup_root,
                (schedule_id,),
                LocalApiBind("127.0.0.1", configuration.api_port),
                configuration.recovery_page_limit,
            ),
            activation,
            composition,
            control,
            SQLiteOfflineSnapshotManager(
                paths.state_database,
                paths.fence_database,
            ),
            credentials,
            static_assets=assets,
            status_report=self.report,
        )
