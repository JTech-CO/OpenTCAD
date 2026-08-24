"""Canonical output archive defense tests."""

from dataclasses import replace
from hashlib import sha256
from io import BytesIO
import tarfile
import unittest

from backend.app.broker.output_archive import (
    ArtifactPayload,
    build_canonical_output_archive,
    validate_canonical_output_archive,
)
from backend.app.runtime.errors import ErrorCode, RuntimeBackendError
from backend.app.runtime.models import (
    ArtifactRecord,
    RawArtifactArchive,
    ValidatedArtifactArchive,
)
from backend.tests.runtime.support import (
    ARTIFACT,
    ARTIFACT_ARCHIVE,
    ARTIFACT_ARCHIVE_LIMITS,
    ARTIFACT_CONTENT,
)


def custom_archive(
    *,
    name: str = "result.str",
    content: bytes = ARTIFACT_CONTENT,
    member_type: bytes = tarfile.REGTYPE,
    mode: str = "w",
) -> RawArtifactArchive:
    output = BytesIO()
    with tarfile.open(fileobj=output, mode=mode, format=tarfile.USTAR_FORMAT) as archive:
        member = tarfile.TarInfo(name)
        member.size = len(content) if member_type == tarfile.REGTYPE else 0
        member.type = member_type
        member.mode = 0o644
        member.uid = 0
        member.gid = 0
        member.mtime = 1
        if member_type in {tarfile.SYMTYPE, tarfile.LNKTYPE}:
            member.linkname = "result.str"
        archive.addfile(member, BytesIO(content) if member.size else None)
    return RawArtifactArchive(output.getvalue())


class CanonicalOutputArchiveTests(unittest.TestCase):
    def test_round_trip_is_deterministic_allows_empty_and_redacts_payload(self) -> None:
        first = build_canonical_output_archive(
            (ArtifactPayload(ARTIFACT.name, ARTIFACT_CONTENT),),
            (ARTIFACT.name,),
            ARTIFACT_ARCHIVE_LIMITS,
        )
        second = build_canonical_output_archive(
            (ArtifactPayload(ARTIFACT.name, ARTIFACT_CONTENT),),
            (ARTIFACT.name,),
            ARTIFACT_ARCHIVE_LIMITS,
        )
        self.assertEqual(first, second)
        validated = validate_canonical_output_archive(
            first,
            (ARTIFACT.name,),
            (ARTIFACT,),
            ARTIFACT_ARCHIVE_LIMITS,
        )
        self.assertEqual(validated.manifest, (ARTIFACT,))
        self.assertEqual(validated.archive_sha256, sha256(first.payload).hexdigest())
        self.assertNotIn(ARTIFACT_CONTENT.decode("ascii"), repr(first))
        self.assertNotIn(ARTIFACT_CONTENT.decode("ascii"), repr(validated))

        empty_record = ArtifactRecord(
            name="empty.log",
            sha256=sha256(b"").hexdigest(),
            bytes=0,
        )
        empty_archive = build_canonical_output_archive(
            (ArtifactPayload("empty.log", b""),),
            ("empty.log",),
            ARTIFACT_ARCHIVE_LIMITS,
        )
        self.assertEqual(
            validate_canonical_output_archive(
                empty_archive,
                ("empty.log",),
                (empty_record,),
                ARTIFACT_ARCHIVE_LIMITS,
            ).manifest,
            (empty_record,),
        )

        with self.assertRaises(RuntimeBackendError) as context:
            ValidatedArtifactArchive(
                (ARTIFACT,),
                "a" * 64,
                len(first.payload),
                first.payload,
                _marker=object(),
            )
        self.assertEqual(context.exception.code, ErrorCode.INVALID_SPEC)

    def test_paths_links_devices_compression_and_metadata_are_rejected(self) -> None:
        cases = (
            custom_archive(name="../result.str"),
            custom_archive(name="/result.str"),
            custom_archive(name="C:\\result.str"),
            custom_archive(name="결과.str"),
            custom_archive(member_type=tarfile.SYMTYPE),
            custom_archive(member_type=tarfile.LNKTYPE),
            custom_archive(member_type=tarfile.CHRTYPE),
            custom_archive(member_type=tarfile.BLKTYPE),
            custom_archive(member_type=tarfile.DIRTYPE),
            custom_archive(member_type=tarfile.FIFOTYPE),
            custom_archive(member_type=tarfile.GNUTYPE_SPARSE),
            custom_archive(mode="w:gz"),
            custom_archive(),
            RawArtifactArchive(ARTIFACT_ARCHIVE.payload + b"\0" * tarfile.BLOCKSIZE),
            RawArtifactArchive(b"malformed"),
        )
        for archive in cases:
            with self.subTest(archive_bytes=len(archive.payload)), self.assertRaises(
                RuntimeBackendError,
            ) as context:
                validate_canonical_output_archive(
                    archive,
                    (ARTIFACT.name,),
                    (ARTIFACT,),
                    ARTIFACT_ARCHIVE_LIMITS,
                )
            self.assertEqual(context.exception.code, ErrorCode.OUTPUT_ARCHIVE_REJECTED)

    def test_manifest_substitution_limits_order_and_collisions_are_rejected(self) -> None:
        drifted = (
            replace(ARTIFACT, sha256="f" * 64),
            replace(ARTIFACT, bytes=ARTIFACT.bytes - 1),
            replace(ARTIFACT, name="other.str"),
        )
        for record in drifted:
            with self.subTest(record=record), self.assertRaises(RuntimeBackendError) as context:
                validate_canonical_output_archive(
                    ARTIFACT_ARCHIVE,
                    (ARTIFACT.name,),
                    (record,),
                    ARTIFACT_ARCHIVE_LIMITS,
                )
            self.assertEqual(context.exception.code, ErrorCode.OUTPUT_ARCHIVE_REJECTED)

        first = ArtifactPayload("Result.str", b"a")
        second = ArtifactPayload("result.str", b"b")
        with self.assertRaises(RuntimeBackendError) as collision:
            build_canonical_output_archive(
                (first, second),
                (first.name, second.name),
                ARTIFACT_ARCHIVE_LIMITS,
            )
        self.assertEqual(collision.exception.code, ErrorCode.OUTPUT_ARCHIVE_REJECTED)

        too_small = replace(
            ARTIFACT_ARCHIVE_LIMITS,
            max_total_bytes=ARTIFACT.bytes - 1,
        )
        with self.assertRaises(RuntimeBackendError) as limit:
            validate_canonical_output_archive(
                ARTIFACT_ARCHIVE,
                (ARTIFACT.name,),
                (ARTIFACT,),
                too_small,
            )
        self.assertEqual(limit.exception.code, ErrorCode.OUTPUT_ARCHIVE_REJECTED)


if __name__ == "__main__":
    unittest.main()
