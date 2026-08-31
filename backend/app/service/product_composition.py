"""M3 evidence-gated bridge into the immutable M2 durable composition."""

from __future__ import annotations

import asyncio

from backend.app.broker.lease import OwnerLeasePolicy
from backend.app.broker.orchestrator import SandboxBroker
from backend.app.broker.runtime_fence_activation import DurableRuntimeFenceActivator
from backend.app.broker.state import DurableJobStateStore
from backend.app.broker.state_composition import DurableBrokerComposition
from backend.app.broker.sqlite_state import SQLiteJobStateStore
from backend.app.product.gates import ProductActivationToken
from backend.app.runtime.models import RuntimeKind
from backend.app.runtime.product_fence_authority import ProductRuntimeFenceAuthority
from backend.app.runtime.protocol import RuntimeBackend


PRODUCT_DURABLE_COMPOSITION_ENABLED = True


class ProductDurableBrokerComposition(DurableBrokerComposition):
    """Activates the M2 composition only for one evidence-bound backend."""

    def __init__(
        self,
        broker: SandboxBroker,
        backend: RuntimeBackend,
        store: DurableJobStateStore,
        activation: ProductActivationToken,
        lease_policy: OwnerLeasePolicy = OwnerLeasePolicy(),
    ) -> None:
        if not isinstance(broker, SandboxBroker):
            raise TypeError("Product composition requires SandboxBroker.")
        if not isinstance(backend, RuntimeBackend):
            raise TypeError("Product composition requires RuntimeBackend.")
        if not isinstance(store, SQLiteJobStateStore):
            raise TypeError("Product composition requires SQLiteJobStateStore.")
        if not isinstance(activation, ProductActivationToken):
            raise TypeError("Product composition requires product activation.")
        if not isinstance(lease_policy, OwnerLeasePolicy):
            raise TypeError("Product composition requires OwnerLeasePolicy.")
        fingerprint = getattr(backend, "activation_manifest_sha256", None)
        if (
            backend.name is RuntimeKind.MOCK
            or getattr(broker, "_backend", None) is not backend
            or broker.runtime_kind is not backend.name
            or broker.runtime_fence_authority is not backend.fence_authority
            or backend.name not in activation.approved_backends
            or fingerprint != activation.manifest_sha256
            or not isinstance(backend.fence_authority, ProductRuntimeFenceAuthority)
        ):
            raise PermissionError("Product runtime activation does not match broker.")

        self._broker = broker
        self._store = store
        self._lease_policy = lease_policy
        self._activation_manifest_sha256 = activation.manifest_sha256
        self._fence_activator = DurableRuntimeFenceActivator(
            store,
            backend.fence_authority,
            backend.name,
        )
        self._startup_lock = asyncio.Lock()
        self._startup_report = None

    @property
    def activation_manifest_sha256(self) -> str:
        return self._activation_manifest_sha256

    @property
    def runtime_kind(self) -> RuntimeKind:
        return self._broker.runtime_kind
