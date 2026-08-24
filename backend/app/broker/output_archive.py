"""Canonical artifact archive construction and memory-only validation."""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from hmac import compare_digest
from io import BytesIO
import tarfile

from backend.app.runtime.errors import ErrorCode, RuntimeBackendError, RuntimePhase
from backend.app.runtime.models import (
    ArtifactRecord,
    RawArtifactArchive,
    ValidatedArtifactArchive,
    _make_validated_artifact_archive,
)

from .archive import (
    ArchiveLimits,
    CANONICAL_GID,
    CANONICAL_MODE,
    CANONICAL_MTIME,
    CANONICAL_UID,
    _safe_member_name,
)


def _reject(detail: str) -> None:
    raise RuntimeBackendError(
        ErrorCode.OUTPUT_ARCHIVE_REJECTED,
        RuntimePhase.ARTIFACT,
        detail=detail,
    )


@dataclass(frozen=True, slots=True)
class ArtifactPayload:
    name: str
    content: bytes = field(repr=False)

    def __post_init__(self) -> None:
        if not _safe_member_name(self.name):
            _reject("payload.name:safe-ustar-name-required")
        if not isinstance(self.content, bytes):
            _reject("payload.content:bytes-required")

    @property
    def record(self) -> ArtifactRecord:
        return ArtifactRecord(
            name=self.name,
            sha256=sha256(self.content).hexdigest(),
            bytes=len(self.content),
        )


def output_archive_limits(artifact_bytes: int, file_count: int) -> ArchiveLimits:
    """Derive a safe canonical stream ceiling from declared artifact limits."""

    if (
        not isinstance(artifact_bytes, int)
        or isinstance(artifact_bytes, bool)
        or artifact_bytes < 1
        or not isinstance(file_count, int)
        or isinstance(file_count, bool)
        or file_count < 1
    ):
        _reject("limits:positive-integers-required")
    upper_bound = artifact_bytes + file_count * (2 * tarfile.BLOCKSIZE - 1)
    upper_bound += 2 * tarfile.BLOCKSIZE
    record_size = tarfile.RECORDSIZE
    stream_bytes = ((upper_bound + record_size - 1) // record_size) * record_size
    return ArchiveLimits(
        max_archive_bytes=stream_bytes,
        max_file_count=file_count,
        max_total_bytes=artifact_bytes,
    )


def _expected_names(values: tuple[str, ...]) -> tuple[str, ...]:
    try:
        names = tuple(values)
    except TypeError:
        _reject("expected_names:tuple-required")
    if not names or any(not _safe_member_name(name) for name in names):
        _reject("expected_names:safe-ustar-names-required")
    if len(set(names)) != len(names):
        _reject("expected_names:duplicate")
    if len({name.casefold() for name in names}) != len(names):
        _reject("expected_names:case-collision")
    return names


def _manifest_tuple(
    values: tuple[ArtifactRecord, ...],
) -> tuple[ArtifactRecord, ...]:
    try:
        manifest = tuple(values)
    except TypeError:
        _reject("manifest:tuple-required")
    if not manifest or any(not isinstance(item, ArtifactRecord) for item in manifest):
        _reject("manifest:artifact-records-required")
    names = tuple(item.name for item in manifest)
    _expected_names(names)
    return manifest


def _payload_tuple(values: tuple[ArtifactPayload, ...]) -> tuple[ArtifactPayload, ...]:
    try:
        payloads = tuple(values)
    except TypeError:
        _reject("payloads:tuple-required")
    if not payloads or any(not isinstance(item, ArtifactPayload) for item in payloads):
        _reject("payloads:artifact-payloads-required")
    return payloads


def _enforce_limits(
    manifest: tuple[ArtifactRecord, ...],
    limits: ArchiveLimits,
) -> None:
    if not isinstance(limits, ArchiveLimits):
        _reject("limits:archive-limits-required")
    if len(manifest) > limits.max_file_count:
        _reject("archive:file-count-limit")
    if sum(item.bytes for item in manifest) > limits.max_total_bytes:
        _reject("archive:total-byte-limit")


def _write_archive(
    payloads: tuple[ArtifactPayload, ...],
    limits: ArchiveLimits,
) -> RawArtifactArchive:
    output = BytesIO()
    with tarfile.open(fileobj=output, mode="w", format=tarfile.USTAR_FORMAT) as archive:
        for payload in payloads:
            member = tarfile.TarInfo(payload.name)
            member.size = len(payload.content)
            member.mode = CANONICAL_MODE
            member.uid = CANONICAL_UID
            member.gid = CANONICAL_GID
            member.mtime = CANONICAL_MTIME
            member.type = tarfile.REGTYPE
            member.uname = ""
            member.gname = ""
            member.linkname = ""
            archive.addfile(member, BytesIO(payload.content))
    result = output.getvalue()
    if len(result) > limits.max_archive_bytes:
        _reject("archive:stream-byte-limit")
    return RawArtifactArchive(result)


def build_canonical_output_archive(
    payloads: tuple[ArtifactPayload, ...],
    expected_names: tuple[str, ...],
    limits: ArchiveLimits,
) -> RawArtifactArchive:
    """Build one deterministic uncompressed USTAR stream for mock transfer."""

    names = _expected_names(expected_names)
    values = _payload_tuple(payloads)
    if tuple(item.name for item in values) != names:
        _reject("payloads:name-or-order-mismatch")
    manifest = tuple(item.record for item in values)
    _enforce_limits(manifest, limits)
    return _write_archive(values, limits)


def validate_canonical_output_archive(
    archive: RawArtifactArchive,
    expected_names: tuple[str, ...],
    reported_manifest: tuple[ArtifactRecord, ...],
    limits: ArchiveLimits,
) -> ValidatedArtifactArchive:
    """Validate untrusted artifact bytes without extracting to the filesystem."""

    if not isinstance(archive, RawArtifactArchive):
        _reject("archive:raw-artifact-archive-required")
    payload = archive.payload
    names = _expected_names(expected_names)
    manifest = _manifest_tuple(reported_manifest)
    if tuple(item.name for item in manifest) != names:
        _reject("manifest:name-or-order-mismatch")
    _enforce_limits(manifest, limits)
    if not payload:
        _reject("archive:non-empty-bytes-required")
    if len(payload) > limits.max_archive_bytes:
        _reject("archive:stream-byte-limit")
    if len(payload) % tarfile.BLOCKSIZE != 0:
        _reject("archive:block-alignment-required")

    recovered: list[ArtifactPayload] = []
    try:
        with tarfile.open(fileobj=BytesIO(payload), mode="r:") as tar:
            for index, member in enumerate(tar):
                if index >= len(manifest) or index >= limits.max_file_count:
                    _reject("archive:file-count-mismatch")
                expected = manifest[index]
                if not _safe_member_name(member.name):
                    _reject(f"archive.members[{index}]:unsafe-name")
                if member.name != expected.name:
                    _reject(f"archive.members[{index}]:name-mismatch")
                if member.type != tarfile.REGTYPE or not member.isreg():
                    _reject(f"archive.members[{index}]:regular-file-required")
                if member.pax_headers:
                    _reject(f"archive.members[{index}]:pax-forbidden")
                if member.size != expected.bytes:
                    _reject(f"archive.members[{index}]:size-mismatch")
                if member.size > limits.max_total_bytes:
                    _reject(f"archive.members[{index}]:member-byte-limit")
                source = tar.extractfile(member)
                if source is None:
                    _reject(f"archive.members[{index}]:content-missing")
                content = source.read(expected.bytes + 1)
                if len(content) != expected.bytes:
                    _reject(f"archive.members[{index}]:content-size-mismatch")
                recovered.append(ArtifactPayload(member.name, content))
    except RuntimeBackendError:
        raise
    except (EOFError, OSError, tarfile.TarError, ValueError):
        _reject("archive:malformed-ustar")

    values = tuple(recovered)
    if len(values) != len(manifest):
        _reject("archive:file-count-mismatch")
    actual_manifest = tuple(item.record for item in values)
    for index, (actual, expected) in enumerate(
        zip(actual_manifest, manifest, strict=True),
    ):
        if actual.name != expected.name:
            _reject(f"archive.members[{index}]:name-mismatch")
        if actual.bytes != expected.bytes:
            _reject(f"archive.members[{index}]:size-mismatch")
        if not compare_digest(actual.sha256, expected.sha256):
            _reject(f"archive.members[{index}]:hash-mismatch")

    canonical = _write_archive(values, limits).payload
    if not compare_digest(canonical, payload):
        _reject("archive:non-canonical-stream")
    return _make_validated_artifact_archive(
        actual_manifest,
        sha256(payload).hexdigest(),
        len(payload),
        payload,
    )
