"""Canonical input archive defense tests."""

from dataclasses import replace
from hashlib import sha256
from io import BytesIO
import tarfile
import unittest

from backend.app.broker.archive import (
    ArchiveLimits,
    InputPayload,
    build_canonical_input_archive,
    validate_canonical_input_archive,
)
from backend.app.runtime.errors import ErrorCode, RuntimeBackendError
from backend.app.runtime.models import InputFile, ValidatedInputArchive
from backend.tests.runtime.support import ARCHIVE_LIMITS, INPUT, INPUT_CONTENT


def custom_archive(
    *,
    name: str = "input.in",
    content: bytes = INPUT_CONTENT,
    member_type: bytes = tarfile.REGTYPE,
    mode: str = "w",
) -> bytes:
    output = BytesIO()
    with tarfile.open(fileobj=output, mode=mode, format=tarfile.USTAR_FORMAT) as archive:
        member = tarfile.TarInfo(name)
        member.size = len(content) if member_type == tarfile.REGTYPE else 0
        member.type = member_type
        member.mode = 0o644
        if member_type in {tarfile.SYMTYPE, tarfile.LNKTYPE}:
            member.linkname = "input.in"
        archive.addfile(member, BytesIO(content) if member.size else None)
    return output.getvalue()


def two_member_archive() -> bytes:
    output = BytesIO()
    with tarfile.open(fileobj=output, mode="w", format=tarfile.USTAR_FORMAT) as archive:
        for name in ("input.in", "extra.in"):
            member = tarfile.TarInfo(name)
            member.size = len(INPUT_CONTENT)
            member.type = tarfile.REGTYPE
            archive.addfile(member, BytesIO(INPUT_CONTENT))
    return output.getvalue()


class CanonicalArchiveTests(unittest.TestCase):
    def test_round_trip_is_deterministic_and_payload_is_redacted_from_repr(self) -> None:
        payloads = (InputPayload(INPUT.name, INPUT_CONTENT),)
        first = build_canonical_input_archive(payloads, (INPUT,), ARCHIVE_LIMITS)
        second = build_canonical_input_archive(payloads, (INPUT,), ARCHIVE_LIMITS)
        self.assertEqual(first, second)
        validated = validate_canonical_input_archive(first, (INPUT,), ARCHIVE_LIMITS)
        self.assertEqual(validated.manifest, (INPUT,))
        self.assertEqual(validated.archive_sha256, sha256(first).hexdigest())
        self.assertEqual(validated.payload, first)
        self.assertNotIn(INPUT_CONTENT.decode("ascii"), repr(validated))

    def test_only_validator_can_construct_validated_archive(self) -> None:
        with self.assertRaises(RuntimeBackendError) as context:
            ValidatedInputArchive(
                (INPUT,),
                "a" * 64,
                10_240,
                b"unsafe",
                _marker=object(),
            )
        self.assertEqual(context.exception.code, ErrorCode.INVALID_SPEC)

    def test_builder_rejects_name_size_and_hash_drift(self) -> None:
        cases = (
            (InputPayload("other.in", INPUT_CONTENT), INPUT),
            (InputPayload(INPUT.name, INPUT_CONTENT + b"x"), INPUT),
            (InputPayload(INPUT.name, INPUT_CONTENT), replace(INPUT, sha256="f" * 64)),
        )
        for payload, expected in cases:
            with self.subTest(payload=payload.name), self.assertRaises(RuntimeBackendError) as context:
                build_canonical_input_archive((payload,), (expected,), ARCHIVE_LIMITS)
            self.assertEqual(context.exception.code, ErrorCode.INPUT_ARCHIVE_REJECTED)

    def test_traversal_absolute_windows_and_unicode_names_are_rejected(self) -> None:
        for name in ("../input.in", "/input.in", "C:\\input.in", "입력.in"):
            with self.subTest(name=name), self.assertRaises(RuntimeBackendError) as context:
                validate_canonical_input_archive(
                    custom_archive(name=name),
                    (INPUT,),
                    ARCHIVE_LIMITS,
                )
            self.assertEqual(context.exception.code, ErrorCode.INPUT_ARCHIVE_REJECTED)
        with self.assertRaises(RuntimeBackendError) as context:
            InputPayload("../input.in", INPUT_CONTENT)
        self.assertEqual(context.exception.code, ErrorCode.INPUT_ARCHIVE_REJECTED)

    def test_links_devices_directories_and_fifo_are_rejected(self) -> None:
        for member_type in (
            tarfile.SYMTYPE,
            tarfile.LNKTYPE,
            tarfile.CHRTYPE,
            tarfile.BLKTYPE,
            tarfile.DIRTYPE,
            tarfile.FIFOTYPE,
            tarfile.GNUTYPE_SPARSE,
        ):
            with self.subTest(member_type=member_type), self.assertRaises(RuntimeBackendError) as context:
                validate_canonical_input_archive(
                    custom_archive(member_type=member_type),
                    (INPUT,),
                    ARCHIVE_LIMITS,
                )
            self.assertEqual(context.exception.code, ErrorCode.INPUT_ARCHIVE_REJECTED)

    def test_compression_metadata_trailing_bytes_and_limits_are_rejected(self) -> None:
        canonical = build_canonical_input_archive(
            (InputPayload(INPUT.name, INPUT_CONTENT),),
            (INPUT,),
            ARCHIVE_LIMITS,
        )
        cases = (
            custom_archive(mode="w:gz"),
            custom_archive(),
            two_member_archive(),
            canonical + b"\0" * tarfile.BLOCKSIZE,
        )
        for archive in cases:
            with self.subTest(bytes=len(archive)), self.assertRaises(RuntimeBackendError) as context:
                validate_canonical_input_archive(archive, (INPUT,), ARCHIVE_LIMITS)
            self.assertEqual(context.exception.code, ErrorCode.INPUT_ARCHIVE_REJECTED)

        too_small = ArchiveLimits(
            max_archive_bytes=10_240,
            max_file_count=1,
            max_total_bytes=INPUT.bytes - 1,
        )
        with self.assertRaises(RuntimeBackendError) as context:
            validate_canonical_input_archive(canonical, (INPUT,), too_small)
        self.assertEqual(context.exception.code, ErrorCode.INPUT_ARCHIVE_REJECTED)
        with self.assertRaises(RuntimeBackendError):
            build_canonical_input_archive(
                (InputPayload(INPUT.name, INPUT_CONTENT),),
                (INPUT,),
                too_small,
            )

        first = InputFile(name="Input.in", sha256="1" * 64, bytes=1)
        second = InputFile(name="input.in", sha256="2" * 64, bytes=1)
        with self.assertRaises(RuntimeBackendError):
            build_canonical_input_archive(
                (InputPayload("Input.in", b"a"), InputPayload("input.in", b"b")),
                (first, second),
                ARCHIVE_LIMITS,
            )


if __name__ == "__main__":
    unittest.main()
