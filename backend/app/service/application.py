"""Product assembly for authenticated local OpenTCAD lifecycle services."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from hashlib import sha256
import hmac
from pathlib import Path
from uuid import UUID, uuid5

from backend.app.broker.backup_control import SQLiteBackupControlStore
from backend.app.broker.backup_service import (
    AuthenticatedSQLiteBackupService,
    ScheduledSQLiteBackupRunner,
)
from backend.app.broker.sqlite_snapshot import SQLiteOfflineSnapshotManager
from backend.app.broker.state_composition import BrokerStartupRequest
from backend.app.product.gates import ProductActivationToken, ProductGateReport

from .credentials import (
    NativeCredentialStore,
    load_backup_keyring,
    load_or_create_secret,
)
from .anti_rollback import NativeRestoreFloorStore
from .local_api import LocalApiBind, LocalApiServer, LocalBrokerApi
from .product_composition import ProductDurableBrokerComposition
from .scheduler import (
    ScheduledBackupLoop,
    ScheduledBackupLoopConfiguration,
)
from .static_assets import LocalStaticAssets
from .status import LocalProductStatus
from .worker import (
    LocalBrokerWorker,
    LocalLifecycleCoordinator,
    WorkerEnvelope,
    WorkerOperation,
)


LOCAL_PRODUCT_SERVICE_ENABLED = True


@dataclass(frozen=True, slots=True)
class LocalServiceConfiguration:
    installation_id: str
    startup_id: str
    backup_root: Path
    schedule_ids: tuple[str, ...]
    bind: LocalApiBind = LocalApiBind()
    recovery_page_limit: int = 100

    def __post_init__(self) -> None:
        for value in (self.installation_id, self.startup_id, *self.schedule_ids):
            try:
                parsed = UUID(value)
            except (AttributeError, TypeError, ValueError) as error:
                raise TypeError("Local service IDs must be UUIDs.") from error
            if str(parsed) != value:
                raise TypeError("Local service IDs must be canonical UUIDs.")
        root = self.backup_root
        if (
            not isinstance(root, Path)
            or not root.is_dir()
            or root.is_symlink()
            or not self.schedule_ids
            or len(set(self.schedule_ids)) != len(self.schedule_ids)
            or not isinstance(self.bind, LocalApiBind)
            or not isinstance(self.recovery_page_limit, int)
            or isinstance(self.recovery_page_limit, bool)
            or not 1 <= self.recovery_page_limit <= 1_000
        ):
            raise TypeError("Local service configuration is invalid.")
        object.__setattr__(self, "schedule_ids", tuple(self.schedule_ids))


class OpenTcadLocalService:
    """Owns startup recovery, API admission, scheduled backups, and shutdown."""

    def __init__(
        self,
        configuration: LocalServiceConfiguration,
        activation: ProductActivationToken,
        composition: ProductDurableBrokerComposition,
        control: SQLiteBackupControlStore,
        snapshot_manager: SQLiteOfflineSnapshotManager,
        credentials: NativeCredentialStore,
        *,
        static_assets: LocalStaticAssets | None = None,
        status_report: ProductGateReport | None = None,
    ) -> None:
        if not isinstance(configuration, LocalServiceConfiguration):
            raise TypeError("Local service requires configuration.")
        if not isinstance(activation, ProductActivationToken):
            raise TypeError("Local service requires product activation.")
        if not isinstance(composition, ProductDurableBrokerComposition):
            raise TypeError("Local service requires product composition.")
        if (
            composition.activation_manifest_sha256
            != activation.manifest_sha256
        ):
            raise PermissionError("Local service activation does not match broker.")
        if not isinstance(control, SQLiteBackupControlStore):
            raise TypeError("Local service requires backup control.")
        if control.installation_id != configuration.installation_id:
            raise PermissionError("Local service installation ID mismatch.")
        if not isinstance(snapshot_manager, SQLiteOfflineSnapshotManager):
            raise TypeError("Local service requires snapshot manager.")
        if not isinstance(credentials, NativeCredentialStore):
            raise TypeError("Local service requires native credentials.")
        if (static_assets is None) != (status_report is None):
            raise TypeError("Local browser assets and status report must be paired.")
        if static_assets is not None and not isinstance(static_assets, LocalStaticAssets):
            raise TypeError("Local service static assets are invalid.")
        if status_report is not None and (
            not isinstance(status_report, ProductGateReport)
            or not status_report.ready
            or status_report.manifest_sha256 != activation.manifest_sha256
        ):
            raise PermissionError("Local service status report is not activated.")

        keyring = load_backup_keyring(credentials)
        bearer_root = load_or_create_secret(
            credentials,
            "opentcad",
            "local-api-v1",
        )
        bearer = hmac.new(
            bearer_root,
            b"OpenTCAD local browser session v1\x00"
            + configuration.startup_id.encode("ascii"),
            sha256,
        ).digest()
        backup_service = AuthenticatedSQLiteBackupService(
            snapshot_manager,
            control,
            keyring,
        )
        scheduled_runner = ScheduledSQLiteBackupRunner(
            backup_service,
            control,
            configuration.backup_root,
        )
        coordinator = LocalLifecycleCoordinator(
            composition,
            control,
            backup_service,
            scheduled_runner,
            NativeRestoreFloorStore(credentials),
        )
        self._configuration = configuration
        self._composition = composition
        self._control = control
        self._worker = LocalBrokerWorker(coordinator)
        self._status_report = status_report
        self._started = False
        self._server = LocalApiServer(
            LocalBrokerApi(self._worker),
            bearer,
            configuration.bind,
            static_assets=static_assets,
            status_provider=(self._status if status_report is not None else None),
        )
        self._scheduler = ScheduledBackupLoop(
            scheduled_runner,
            ScheduledBackupLoopConfiguration(
                configuration.schedule_ids,
                configuration.installation_id,
            ),
        )

    def _status(self) -> LocalProductStatus:
        report = self._status_report
        if report is None:
            raise RuntimeError("Local browser status is not configured.")
        return LocalProductStatus.activated(
            report,
            self._composition.runtime_kind,
            service_ready=self._started,
            recovery_ready=self._composition.ready,
            scheduler_running=self._scheduler.running,
            scheduler_degraded=bool(self._scheduler.failures),
        )

    @property
    def started(self) -> bool:
        return self._started

    @property
    def port(self) -> int:
        return self._server.port

    @property
    def startup_id(self) -> str:
        return self._configuration.startup_id

    @property
    def browser_url(self) -> str:
        return self._server.browser_url

    async def start(self) -> None:
        if self._started:
            return
        for schedule_id in self._configuration.schedule_ids:
            await asyncio.to_thread(
                self._control.current_schedule,
                schedule_id,
            )
        await self._worker.start()
        startup_payload = BrokerStartupRequest(
            self._configuration.startup_id,
            self._configuration.recovery_page_limit,
        )
        request_id = str(
            uuid5(UUID(self._configuration.startup_id), "local-service-recovery"),
        )
        request_hash = sha256(
            (
                self._configuration.startup_id
                + ":"
                + str(self._configuration.recovery_page_limit)
            ).encode(),
        ).hexdigest()
        try:
            await self._worker.submit(
                WorkerEnvelope(
                    request_id,
                    request_hash,
                    WorkerOperation.STARTUP_RECOVERY,
                    startup_payload,
                ),
            )
            await self._scheduler.start()
            await self._server.start()
            self._started = True
        except Exception:
            await self._scheduler.close()
            await self._server.close()
            await self._worker.close()
            raise

    async def close(self) -> None:
        await self._server.close()
        await self._scheduler.close()
        await self._worker.close()
        self._started = False
