"""Code-owned solver release profiles bound to an approved manifest digest."""

from __future__ import annotations

from dataclasses import dataclass
import re

from backend.app.broker.archive import ArchiveLimits
from backend.app.runtime.models import ImageIdentity, RuntimeKind
from backend.app.runtime.oci_backend import OciAdapterConfiguration
from backend.app.runtime.policy import SandboxPolicy

from .gates import ProductActivationToken


_SHA256 = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True, slots=True)
class ProductReleaseProfile:
    """One reviewed backend profile; operators cannot supply its commands."""

    manifest_sha256: str
    backend: RuntimeKind
    adapter: OciAdapterConfiguration
    policy: SandboxPolicy
    archive_limits: ArchiveLimits

    def __post_init__(self) -> None:
        if (
            _SHA256.fullmatch(self.manifest_sha256) is None
            or self.backend not in {RuntimeKind.DOCKER, RuntimeKind.PODMAN}
            or not isinstance(self.adapter, OciAdapterConfiguration)
            or self.adapter.kind is not self.backend
            or not isinstance(self.policy, SandboxPolicy)
            or not isinstance(self.archive_limits, ArchiveLimits)
        ):
            raise TypeError("Product release profile is invalid.")

    @property
    def images(self) -> tuple[ImageIdentity, ...]:
        return tuple(
            dict.fromkeys(
                (
                    self.adapter.transfer_image,
                    *(profile.image for profile in self.policy.engine_profiles),
                ),
            ),
        )

    def verify_activation(self, activation: ProductActivationToken) -> None:
        if (
            not isinstance(activation, ProductActivationToken)
            or activation.manifest_sha256 != self.manifest_sha256
            or self.backend not in activation.approved_backends
        ):
            raise PermissionError("Release profile is not activated.")
        for helper_id in (
            self.adapter.input_helper_id,
            self.adapter.output_helper_id,
        ):
            if not activation.permits(
                self.backend,
                self.adapter.transfer_image,
                helper_id,
            ):
                raise PermissionError("Release helper is not activated.")
        for engine in self.policy.engine_profiles:
            if not activation.permits(
                self.backend,
                engine.image,
                engine.entrypoint_id,
            ):
                raise PermissionError("Release engine is not activated.")


# Intentionally empty until license, image, SBOM, corpus, platform, and power
# evidence is approved together. Adding a profile is a reviewed release change.
PRODUCT_RELEASE_PROFILES: tuple[ProductReleaseProfile, ...] = ()


def release_profile_for(
    activation: ProductActivationToken,
    backend: RuntimeKind,
) -> ProductReleaseProfile:
    for profile in PRODUCT_RELEASE_PROFILES:
        if (
            profile.manifest_sha256 == activation.manifest_sha256
            and profile.backend is backend
        ):
            profile.verify_activation(activation)
            return profile
    raise PermissionError("No code-owned release profile matches this activation.")
