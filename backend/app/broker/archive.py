"""Canonical in-memory archive construction and fail-closed validation."""

from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
from hmac import compare_digest
from io import BytesIO
import tarfile

from backend.app.runtime.errors import ErrorCode, RuntimeBackendError, RuntimePhase
from backend.app.runtime.models import (
    InputFile,
    ValidatedInputArchive,
    _make_validated_input_archive,
)


USTAR_NAME_BYTES = 100
CANONICAL_MODE = 0o400
CANONICAL_UID = 65_534
CANONICAL_GID = 65_534
CANONICAL_MTIME = 0


def _reject(detail: str) -> None:
    raise RuntimeBackendError(
        ErrorCode.INPUT_ARCHIVE_REJECTED,
        RuntimePhase.INPUT,
        detail=detail,
    )


@dataclass(frozen=True, slots=True)
class ArchiveLimits:
    max_archive_bytes: int
    max_file_count: int
    max_total_bytes: int

    def __post_init__(self) -> None:
        values = (
            ("max_archive_bytes", self.max_archive_bytes, 10_240, 1_099_511_627_776),
            ("max_file_count", self.max_file_count, 1, 100_000),
            ("max_total_bytes", self.max_total_bytes, 1, 1_099_511_627_776),
        )
        for name, value, minimum, maximum in values:
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or value < minimum
                or value > maximum
            ):
                _reject(f"limits.{name}:out-of-range")


@dataclass(frozen=True, slots=True)
class InputPayload:
    name: str
    content: bytes = field(repr=False)

    def __post_init__(self) -> None:
        if not _safe_member_name(self.name):
            _reject("payload.name:safe-ustar-name-required")
        if not isinstance(self.content, bytes) or not self.content:
            _reject("payload.content:non-empty-bytes-required")

    @property
    def record(self) -> InputFile:
        return InputFile(
            name=self.name,
            sha256=sha256(self.content).hexdigest(),
            bytes=len(self.content),
        )


def _manifest_tuple(expected_manifest: tuple[InputFile, ...]) -> tuple[InputFile, ...]:
    try:
        manifest = tuple(expected_manifest)
    except TypeError:
        _reject("manifest:tuple-required")
    if not manifest or any(not isinstance(item, InputFile) for item in manifest):
        _reject("manifest:input-file-records-required")
    folded_names: set[str] = set()
    for item in manifest:
        try:
            encoded_name = item.name.encode("ascii")
        except UnicodeEncodeError:
            _reject("manifest.name:ascii-required")
        if len(encoded_name) > USTAR_NAME_BYTES:
            _reject("manifest.name:ustar-limit")
        folded = item.name.casefold()
        if folded in folded_names:
            _reject("manifest.name:case-collision")
        folded_names.add(folded)
    return manifest


def _payload_tuple(payloads: tuple[InputPayload, ...]) -> tuple[InputPayload, ...]:
    try:
        values = tuple(payloads)
    except TypeError:
        _reject("payloads:tuple-required")
    if not values or any(not isinstance(item, InputPayload) for item in values):
        _reject("payloads:input-payload-records-required")
    return values


def _match_payloads(
    payloads: tuple[InputPayload, ...],
    manifest: tuple[InputFile, ...],
) -> None:
    if len(payloads) != len(manifest):
        _reject("payloads:count-mismatch")
    for index, (payload, expected) in enumerate(zip(payloads, manifest, strict=True)):
        record = payload.record
        if record.name != expected.name:
            _reject(f"payloads[{index}]:name-mismatch")
        if record.bytes != expected.bytes:
            _reject(f"payloads[{index}]:size-mismatch")
        if not compare_digest(record.sha256, expected.sha256):
            _reject(f"payloads[{index}]:hash-mismatch")


def build_canonical_input_archive(
    payloads: tuple[InputPayload, ...],
    expected_manifest: tuple[InputFile, ...],
    limits: ArchiveLimits,
) -> bytes:
    """Build one deterministic uncompressed USTAR stream from flat files."""

    manifest = _manifest_tuple(expected_manifest)
    _enforce_manifest_limits(manifest, limits)
    values = _payload_tuple(payloads)
    _match_payloads(values, manifest)

    output = BytesIO()
    with tarfile.open(fileobj=output, mode="w", format=tarfile.USTAR_FORMAT) as archive:
        for payload in values:
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
    return result


def _safe_member_name(name: object) -> bool:
    if not isinstance(name, str) or not name or name in {".", ".."}:
        return False
    if "/" in name or "\\" in name:
        return False
    try:
        return len(name.encode("ascii")) <= USTAR_NAME_BYTES
    except UnicodeEncodeError:
        return False


def _enforce_manifest_limits(
    manifest: tuple[InputFile, ...],
    limits: ArchiveLimits,
) -> None:
    if not isinstance(limits, ArchiveLimits):
        _reject("archive:limits-required")
    if len(manifest) > limits.max_file_count:
        _reject("archive:file-count-limit")
    if sum(item.bytes for item in manifest) > limits.max_total_bytes:
        _reject("archive:total-byte-limit")


def validate_canonical_input_archive(
    payload: bytes,
    expected_manifest: tuple[InputFile, ...],
    limits: ArchiveLimits,
) -> ValidatedInputArchive:
    """Validate without filesystem extraction and return a policy-only archive type."""

    if not isinstance(payload, bytes) or not payload:
        _reject("archive:non-empty-bytes-required")
    manifest = _manifest_tuple(expected_manifest)
    _enforce_manifest_limits(manifest, limits)
    if len(payload) > limits.max_archive_bytes:
        _reject("archive:stream-byte-limit")
    if len(payload) % tarfile.BLOCKSIZE != 0:
        _reject("archive:block-alignment-required")

    recovered: list[InputPayload] = []
    try:
        with tarfile.open(fileobj=BytesIO(payload), mode="r:") as archive:
            for index, member in enumerate(archive):
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
                source = archive.extractfile(member)
                if source is None:
                    _reject(f"archive.members[{index}]:content-missing")
                content = source.read(expected.bytes + 1)
                if len(content) != expected.bytes:
                    _reject(f"archive.members[{index}]:content-size-mismatch")
                recovered.append(InputPayload(member.name, content))
    except RuntimeBackendError:
        raise
    except (EOFError, OSError, tarfile.TarError, ValueError):
        _reject("archive:malformed-ustar")

    values = tuple(recovered)
    _match_payloads(values, manifest)
    canonical = build_canonical_input_archive(values, manifest, limits)
    if not compare_digest(canonical, payload):
        _reject("archive:non-canonical-stream")
    archive_hash = sha256(payload).hexdigest()
    return _make_validated_input_archive(
        manifest,
        archive_hash,
        len(payload),
        payload,
    )
