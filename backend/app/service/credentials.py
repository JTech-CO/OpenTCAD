"""Fail-closed OS credential stores for local API and backup secrets."""

from __future__ import annotations

import base64
import binascii
import ctypes
from ctypes import POINTER, Structure, byref, c_char_p, c_uint32, c_void_p
from ctypes import wintypes
from enum import StrEnum
from hashlib import sha256
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
from typing import Protocol, runtime_checkable

from backend.app.broker.backup_service import HMACBackupKeyring


NATIVE_CREDENTIAL_STORE_PRODUCT_ENABLED = True
_CREDENTIAL_ID = re.compile(r"^[a-z][a-z0-9.-]{0,127}$")
_SERVICE_ID = re.compile(r"^[a-z][a-z0-9.-]{0,127}$")
_MAX_SECRET_BYTES = 4_096
_SECRET_TOOL_PREFIX = b"opentcad-secret-v1:"


class CredentialStoreErrorCode(StrEnum):
    UNAVAILABLE = "credential-store-unavailable"
    NOT_FOUND = "credential-not-found"
    INVALID = "credential-invalid"


class CredentialStoreError(Exception):
    def __init__(self, code: CredentialStoreErrorCode) -> None:
        if not isinstance(code, CredentialStoreErrorCode):
            raise TypeError("CredentialStoreError requires a stable code.")
        self.code = code
        super().__init__(code.value)

    def as_dict(self) -> dict[str, str]:
        return {"code": self.code.value}


def _validate_identity(service: str, credential_id: str) -> None:
    if (
        not isinstance(service, str)
        or _SERVICE_ID.fullmatch(service) is None
        or not isinstance(credential_id, str)
        or _CREDENTIAL_ID.fullmatch(credential_id) is None
    ):
        raise CredentialStoreError(CredentialStoreErrorCode.INVALID)


def _validate_secret(secret: bytes) -> bytes:
    if (
        not isinstance(secret, bytes)
        or not secret
        or len(secret) > _MAX_SECRET_BYTES
    ):
        raise CredentialStoreError(CredentialStoreErrorCode.INVALID)
    return bytes(secret)


@runtime_checkable
class CredentialStore(Protocol):
    def get(self, service: str, credential_id: str) -> bytes: ...

    def set(self, service: str, credential_id: str, secret: bytes) -> None: ...

    def delete(self, service: str, credential_id: str) -> None: ...


@runtime_checkable
class NativeCredentialStore(CredentialStore, Protocol):
    @property
    def provider(self) -> str: ...


class InMemoryCredentialStore:
    """Test-only key store with the same redacted interface."""

    def __init__(self) -> None:
        self._values: dict[tuple[str, str], bytes] = {}

    def get(self, service: str, credential_id: str) -> bytes:
        _validate_identity(service, credential_id)
        try:
            return bytes(self._values[(service, credential_id)])
        except KeyError:
            raise CredentialStoreError(CredentialStoreErrorCode.NOT_FOUND) from None

    def set(self, service: str, credential_id: str, secret: bytes) -> None:
        _validate_identity(service, credential_id)
        self._values[(service, credential_id)] = _validate_secret(secret)

    def delete(self, service: str, credential_id: str) -> None:
        _validate_identity(service, credential_id)
        self._values.pop((service, credential_id), None)


class _DataBlob(Structure):
    _fields_ = [
        ("cbData", wintypes.DWORD),
        ("pbData", POINTER(ctypes.c_ubyte)),
    ]


def _blob(value: bytes):
    buffer = ctypes.create_string_buffer(value)
    return (
        _DataBlob(
            len(value),
            ctypes.cast(buffer, POINTER(ctypes.c_ubyte)),
        ),
        buffer,
    )


class WindowsDpapiCredentialStore:
    """Current-user DPAPI protection with durable atomic ciphertext files."""

    _UI_FORBIDDEN = 0x1

    def __init__(self, directory: str | os.PathLike[str]) -> None:
        path = Path(directory)
        if (
            sys.platform != "win32"
            or not path.is_dir()
            or path.is_symlink()
        ):
            raise CredentialStoreError(CredentialStoreErrorCode.UNAVAILABLE)
        self._directory = path

    @property
    def provider(self) -> str:
        return "windows-dpapi-file"

    def _path(self, service: str, credential_id: str) -> Path:
        _validate_identity(service, credential_id)
        name = sha256(f"{service}\0{credential_id}".encode()).hexdigest()
        return self._directory / f"{name}.dpapi"

    @staticmethod
    def _protect(secret: bytes, entropy_value: bytes) -> bytes:
        try:
            crypt32 = ctypes.windll.crypt32
            kernel32 = ctypes.windll.kernel32
            source, source_buffer = _blob(secret)
            entropy, entropy_buffer = _blob(entropy_value)
            target = _DataBlob()
            result = crypt32.CryptProtectData(
                byref(source),
                None,
                byref(entropy),
                None,
                None,
                WindowsDpapiCredentialStore._UI_FORBIDDEN,
                byref(target),
            )
            _ = source_buffer, entropy_buffer
            if not result:
                raise OSError
            try:
                return ctypes.string_at(target.pbData, target.cbData)
            finally:
                kernel32.LocalFree(target.pbData)
        except (AttributeError, OSError, ValueError):
            raise CredentialStoreError(CredentialStoreErrorCode.UNAVAILABLE) from None

    @staticmethod
    def _unprotect(ciphertext: bytes, entropy_value: bytes) -> bytes:
        try:
            crypt32 = ctypes.windll.crypt32
            kernel32 = ctypes.windll.kernel32
            source, source_buffer = _blob(ciphertext)
            entropy, entropy_buffer = _blob(entropy_value)
            target = _DataBlob()
            result = crypt32.CryptUnprotectData(
                byref(source),
                None,
                byref(entropy),
                None,
                None,
                WindowsDpapiCredentialStore._UI_FORBIDDEN,
                byref(target),
            )
            _ = source_buffer, entropy_buffer
            if not result:
                raise OSError
            try:
                return ctypes.string_at(target.pbData, target.cbData)
            finally:
                kernel32.LocalFree(target.pbData)
        except (AttributeError, OSError, ValueError):
            raise CredentialStoreError(CredentialStoreErrorCode.UNAVAILABLE) from None

    def get(self, service: str, credential_id: str) -> bytes:
        path = self._path(service, credential_id)
        try:
            if not path.is_file() or path.is_symlink():
                raise FileNotFoundError
            ciphertext = path.read_bytes()
            if not ciphertext or len(ciphertext) > _MAX_SECRET_BYTES * 4:
                raise OSError
            secret = self._unprotect(
                ciphertext,
                f"{service}\0{credential_id}".encode(),
            )
            return _validate_secret(secret)
        except FileNotFoundError:
            raise CredentialStoreError(CredentialStoreErrorCode.NOT_FOUND) from None
        except CredentialStoreError:
            raise
        except OSError:
            raise CredentialStoreError(CredentialStoreErrorCode.UNAVAILABLE) from None

    def set(self, service: str, credential_id: str, secret: bytes) -> None:
        path = self._path(service, credential_id)
        value = _validate_secret(secret)
        ciphertext = self._protect(
            value,
            f"{service}\0{credential_id}".encode(),
        )
        temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
        descriptor: int | None = None
        try:
            descriptor = os.open(
                temporary,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                0o600,
            )
            with os.fdopen(descriptor, "wb", closefd=True) as stream:
                descriptor = None
                stream.write(ciphertext)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        except OSError:
            if descriptor is not None:
                os.close(descriptor)
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
            raise CredentialStoreError(CredentialStoreErrorCode.UNAVAILABLE) from None

    def delete(self, service: str, credential_id: str) -> None:
        path = self._path(service, credential_id)
        try:
            path.unlink(missing_ok=True)
        except OSError:
            raise CredentialStoreError(CredentialStoreErrorCode.UNAVAILABLE) from None


class _WindowsCredential(Structure):
    _fields_ = [
        ("Flags", wintypes.DWORD),
        ("Type", wintypes.DWORD),
        ("TargetName", wintypes.LPWSTR),
        ("Comment", wintypes.LPWSTR),
        ("LastWritten", wintypes.FILETIME),
        ("CredentialBlobSize", wintypes.DWORD),
        ("CredentialBlob", POINTER(ctypes.c_ubyte)),
        ("Persist", wintypes.DWORD),
        ("AttributeCount", wintypes.DWORD),
        ("Attributes", c_void_p),
        ("TargetAlias", wintypes.LPWSTR),
        ("UserName", wintypes.LPWSTR),
    ]


class WindowsCredentialManagerStore:
    """Windows Credential Manager generic credentials under the current user."""

    _GENERIC = 1
    _PERSIST_LOCAL_MACHINE = 2
    _NOT_FOUND = 1168

    def __init__(self) -> None:
        if sys.platform != "win32":
            raise CredentialStoreError(CredentialStoreErrorCode.UNAVAILABLE)
        try:
            self._advapi = ctypes.WinDLL("Advapi32.dll", use_last_error=True)
            self._advapi.CredWriteW.argtypes = (
                POINTER(_WindowsCredential),
                wintypes.DWORD,
            )
            self._advapi.CredWriteW.restype = wintypes.BOOL
            self._advapi.CredReadW.argtypes = (
                wintypes.LPCWSTR,
                wintypes.DWORD,
                wintypes.DWORD,
                POINTER(POINTER(_WindowsCredential)),
            )
            self._advapi.CredReadW.restype = wintypes.BOOL
            self._advapi.CredDeleteW.argtypes = (
                wintypes.LPCWSTR,
                wintypes.DWORD,
                wintypes.DWORD,
            )
            self._advapi.CredDeleteW.restype = wintypes.BOOL
            self._advapi.CredFree.argtypes = (c_void_p,)
        except (AttributeError, OSError):
            raise CredentialStoreError(CredentialStoreErrorCode.UNAVAILABLE) from None

    @property
    def provider(self) -> str:
        return "windows-credential-manager"

    @staticmethod
    def _target(service: str, credential_id: str) -> str:
        _validate_identity(service, credential_id)
        return f"OpenTCAD/{service}/{credential_id}"

    def get(self, service: str, credential_id: str) -> bytes:
        target = self._target(service, credential_id)
        pointer = POINTER(_WindowsCredential)()
        if not self._advapi.CredReadW(
            target,
            self._GENERIC,
            0,
            byref(pointer),
        ):
            code = ctypes.get_last_error()
            raise CredentialStoreError(
                CredentialStoreErrorCode.NOT_FOUND
                if code == self._NOT_FOUND
                else CredentialStoreErrorCode.UNAVAILABLE,
            )
        try:
            credential = pointer.contents
            if (
                credential.CredentialBlobSize < 1
                or credential.CredentialBlobSize > _MAX_SECRET_BYTES
                or not credential.CredentialBlob
            ):
                raise CredentialStoreError(CredentialStoreErrorCode.UNAVAILABLE)
            return _validate_secret(
                ctypes.string_at(
                    credential.CredentialBlob,
                    credential.CredentialBlobSize,
                ),
            )
        finally:
            self._advapi.CredFree(pointer)

    def set(self, service: str, credential_id: str, secret: bytes) -> None:
        target = self._target(service, credential_id)
        value = _validate_secret(secret)
        buffer = (ctypes.c_ubyte * len(value)).from_buffer_copy(value)
        credential = _WindowsCredential()
        credential.Type = self._GENERIC
        credential.TargetName = target
        credential.CredentialBlobSize = len(value)
        credential.CredentialBlob = ctypes.cast(
            buffer,
            POINTER(ctypes.c_ubyte),
        )
        credential.Persist = self._PERSIST_LOCAL_MACHINE
        credential.UserName = service
        if not self._advapi.CredWriteW(byref(credential), 0):
            raise CredentialStoreError(CredentialStoreErrorCode.UNAVAILABLE)

    def delete(self, service: str, credential_id: str) -> None:
        target = self._target(service, credential_id)
        if not self._advapi.CredDeleteW(target, self._GENERIC, 0):
            code = ctypes.get_last_error()
            if code != self._NOT_FOUND:
                raise CredentialStoreError(CredentialStoreErrorCode.UNAVAILABLE)


class SecretToolCredentialStore:
    """Linux Secret Service adapter; secrets only cross stdin/stdout pipes."""

    def __init__(self, executable: str = "secret-tool") -> None:
        if not sys.platform.startswith("linux"):
            raise CredentialStoreError(CredentialStoreErrorCode.UNAVAILABLE)
        resolved = shutil.which(executable)
        if resolved is None:
            raise CredentialStoreError(CredentialStoreErrorCode.UNAVAILABLE)
        self._executable = resolved

    @property
    def provider(self) -> str:
        return "linux-secret-service"

    def _run(
        self,
        arguments: tuple[str, ...],
        *,
        input_value: bytes | None = None,
    ) -> subprocess.CompletedProcess[bytes]:
        # Secret Service is on the user's session bus, not the system bus.
        # Do not inherit unrelated application secrets or loader overrides.
        environment = {
            key: os.environ[key]
            for key in ("PATH", "HOME", "DBUS_SESSION_BUS_ADDRESS", "XDG_RUNTIME_DIR")
            if key in os.environ
        }
        environment.update({"LANG": "C", "LC_ALL": "C"})
        try:
            return subprocess.run(
                (self._executable, *arguments),
                input=input_value,
                capture_output=True,
                timeout=15,
                check=False,
                env=environment,
            )
        except (OSError, subprocess.TimeoutExpired):
            raise CredentialStoreError(CredentialStoreErrorCode.UNAVAILABLE) from None

    def get(self, service: str, credential_id: str) -> bytes:
        _validate_identity(service, credential_id)
        result = self._run(
            ("lookup", "service", service, "credential", credential_id),
        )
        if result.returncode == 1 and not result.stdout and not result.stderr:
            raise CredentialStoreError(CredentialStoreErrorCode.NOT_FOUND)
        if result.returncode != 0:
            raise CredentialStoreError(CredentialStoreErrorCode.UNAVAILABLE)
        if not result.stdout:
            raise CredentialStoreError(CredentialStoreErrorCode.UNAVAILABLE)
        raw = result.stdout
        if len(raw) > (_MAX_SECRET_BYTES * 2) + len(_SECRET_TOOL_PREFIX) + 8:
            raise CredentialStoreError(CredentialStoreErrorCode.UNAVAILABLE)
        line = raw[:-1] if raw.endswith(b"\n") else raw
        line = line[:-1] if line.endswith(b"\r") else line
        if (
            b"\n" in line
            or b"\r" in line
            or not line.startswith(_SECRET_TOOL_PREFIX)
        ):
            raise CredentialStoreError(CredentialStoreErrorCode.UNAVAILABLE)
        try:
            secret = base64.b64decode(
                line[len(_SECRET_TOOL_PREFIX):],
                altchars=b"-_",
                validate=True,
            )
        except (binascii.Error, ValueError):
            raise CredentialStoreError(CredentialStoreErrorCode.UNAVAILABLE) from None
        return _validate_secret(secret)

    def set(self, service: str, credential_id: str, secret: bytes) -> None:
        _validate_identity(service, credential_id)
        value = _validate_secret(secret)
        encoded = _SECRET_TOOL_PREFIX + base64.urlsafe_b64encode(value)
        result = self._run(
            (
                "store",
                "--label",
                f"{service}:{credential_id}",
                "service",
                service,
                "credential",
                credential_id,
            ),
            input_value=encoded,
        )
        if result.returncode != 0:
            raise CredentialStoreError(CredentialStoreErrorCode.UNAVAILABLE)

    def delete(self, service: str, credential_id: str) -> None:
        _validate_identity(service, credential_id)
        result = self._run(
            ("clear", "service", service, "credential", credential_id),
        )
        if result.returncode not in {0, 1}:
            raise CredentialStoreError(CredentialStoreErrorCode.UNAVAILABLE)


class MacOSKeychainCredentialStore:
    """macOS Security.framework generic-password adapter without argv secrets."""

    _ITEM_NOT_FOUND = -25300

    def __init__(self) -> None:
        if sys.platform != "darwin":
            raise CredentialStoreError(CredentialStoreErrorCode.UNAVAILABLE)
        try:
            self._security = ctypes.cdll.LoadLibrary(
                "/System/Library/Frameworks/Security.framework/Security",
            )
            self._core = ctypes.cdll.LoadLibrary(
                "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation",
            )
            self._security.SecKeychainFindGenericPassword.restype = ctypes.c_int32
            self._security.SecKeychainFindGenericPassword.argtypes = (
                c_void_p,
                c_uint32,
                c_void_p,
                c_uint32,
                c_void_p,
                POINTER(c_uint32),
                POINTER(c_void_p),
                POINTER(c_void_p),
            )
            self._security.SecKeychainAddGenericPassword.restype = ctypes.c_int32
            self._security.SecKeychainAddGenericPassword.argtypes = (
                c_void_p,
                c_uint32,
                c_void_p,
                c_uint32,
                c_void_p,
                c_uint32,
                c_void_p,
                POINTER(c_void_p),
            )
            self._security.SecKeychainItemModifyAttributesAndData.restype = (
                ctypes.c_int32
            )
            self._security.SecKeychainItemModifyAttributesAndData.argtypes = (
                c_void_p,
                c_void_p,
                c_uint32,
                c_void_p,
            )
            self._security.SecKeychainItemDelete.restype = ctypes.c_int32
            self._security.SecKeychainItemDelete.argtypes = (c_void_p,)
            self._security.SecKeychainItemFreeContent.restype = ctypes.c_int32
            self._security.SecKeychainItemFreeContent.argtypes = (
                c_void_p,
                c_void_p,
            )
            self._core.CFRelease.argtypes = (c_void_p,)
        except (AttributeError, OSError):
            raise CredentialStoreError(CredentialStoreErrorCode.UNAVAILABLE) from None

    @property
    def provider(self) -> str:
        return "macos-keychain"

    def _find(
        self,
        service: str,
        credential_id: str,
        *,
        include_data: bool,
    ) -> tuple[int, c_void_p, int, c_void_p]:
        _validate_identity(service, credential_id)
        service_bytes = service.encode("ascii")
        account_bytes = credential_id.encode("ascii")
        length = c_uint32()
        data = c_void_p()
        item = c_void_p()
        status = self._security.SecKeychainFindGenericPassword(
            None,
            len(service_bytes),
            c_char_p(service_bytes),
            len(account_bytes),
            c_char_p(account_bytes),
            byref(length) if include_data else None,
            byref(data) if include_data else None,
            byref(item),
        )
        return status, item, length.value, data

    def get(self, service: str, credential_id: str) -> bytes:
        status, item, length, data = self._find(
            service,
            credential_id,
            include_data=True,
        )
        if status == self._ITEM_NOT_FOUND:
            raise CredentialStoreError(CredentialStoreErrorCode.NOT_FOUND)
        if status != 0 or not data or length < 1 or length > _MAX_SECRET_BYTES:
            raise CredentialStoreError(CredentialStoreErrorCode.UNAVAILABLE)
        try:
            return _validate_secret(ctypes.string_at(data, length))
        finally:
            self._security.SecKeychainItemFreeContent(None, data)
            if item:
                self._core.CFRelease(item)

    def set(self, service: str, credential_id: str, secret: bytes) -> None:
        _validate_identity(service, credential_id)
        value = _validate_secret(secret)
        status, item, _, _ = self._find(
            service,
            credential_id,
            include_data=False,
        )
        value_buffer = ctypes.create_string_buffer(value)
        try:
            if status == self._ITEM_NOT_FOUND:
                service_bytes = service.encode("ascii")
                account_bytes = credential_id.encode("ascii")
                status = self._security.SecKeychainAddGenericPassword(
                    None,
                    len(service_bytes),
                    c_char_p(service_bytes),
                    len(account_bytes),
                    c_char_p(account_bytes),
                    len(value),
                    ctypes.cast(value_buffer, c_void_p),
                    None,
                )
            elif status == 0 and item:
                status = self._security.SecKeychainItemModifyAttributesAndData(
                    item,
                    None,
                    len(value),
                    ctypes.cast(value_buffer, c_void_p),
                )
            if status != 0:
                raise CredentialStoreError(CredentialStoreErrorCode.UNAVAILABLE)
        finally:
            if item:
                self._core.CFRelease(item)

    def delete(self, service: str, credential_id: str) -> None:
        status, item, _, _ = self._find(
            service,
            credential_id,
            include_data=False,
        )
        if status == self._ITEM_NOT_FOUND:
            return
        try:
            if status != 0 or not item:
                raise CredentialStoreError(CredentialStoreErrorCode.UNAVAILABLE)
            if self._security.SecKeychainItemDelete(item) != 0:
                raise CredentialStoreError(CredentialStoreErrorCode.UNAVAILABLE)
        finally:
            if item:
                self._core.CFRelease(item)


def native_credential_store(
    *,
    windows_directory: str | os.PathLike[str] | None = None,
) -> NativeCredentialStore:
    if sys.platform == "win32":
        if windows_directory is not None:
            return WindowsDpapiCredentialStore(windows_directory)
        return WindowsCredentialManagerStore()
    if sys.platform.startswith("linux"):
        return SecretToolCredentialStore()
    if sys.platform == "darwin":
        return MacOSKeychainCredentialStore()
    raise CredentialStoreError(CredentialStoreErrorCode.UNAVAILABLE)


def load_or_create_secret(
    store: CredentialStore,
    service: str,
    credential_id: str,
    *,
    byte_count: int = 32,
) -> bytes:
    if not isinstance(store, CredentialStore):
        raise TypeError("Secret provisioning requires CredentialStore.")
    if (
        not isinstance(byte_count, int)
        or isinstance(byte_count, bool)
        or byte_count < 32
        or byte_count > 128
    ):
        raise CredentialStoreError(CredentialStoreErrorCode.INVALID)
    try:
        return store.get(service, credential_id)
    except CredentialStoreError as error:
        if error.code is not CredentialStoreErrorCode.NOT_FOUND:
            raise
    generated = secrets.token_bytes(byte_count)
    store.set(service, credential_id, generated)
    recovered = store.get(service, credential_id)
    if recovered != generated:
        raise CredentialStoreError(CredentialStoreErrorCode.UNAVAILABLE)
    return recovered


def load_backup_keyring(
    store: CredentialStore,
    *,
    service: str = "opentcad",
    key_id: str = "backup-v1",
) -> HMACBackupKeyring:
    secret = load_or_create_secret(store, service, key_id)
    return HMACBackupKeyring(key_id, {key_id: secret})
