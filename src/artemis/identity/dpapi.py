"""Windows DPAPI helpers for sealing and unsealing local owner secrets."""

from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from typing import ClassVar


class DpapiError(Exception):
    """Raised when Windows DPAPI is unavailable or an operation fails."""


type CharBuffer = ctypes.Array[ctypes.c_char]


class DATA_BLOB(ctypes.Structure):  # noqa: N801
    """ctypes representation of the Windows DPAPI DATA_BLOB structure."""

    _fields_: ClassVar = [
        ("cbData", wintypes.DWORD),
        ("pbData", ctypes.POINTER(ctypes.c_char)),
    ]


def _require_windows() -> None:
    if sys.platform != "win32":
        raise DpapiError("DPAPI is only available on Windows")


def _blob_from_bytes(data: bytes) -> tuple[DATA_BLOB, CharBuffer]:
    buffer = (
        ctypes.create_string_buffer(data, len(data)) if data else ctypes.create_string_buffer(0)
    )
    return DATA_BLOB(
        wintypes.DWORD(len(data)), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_char))
    ), buffer


def _configure_dpapi() -> tuple[ctypes.WinDLL, ctypes.WinDLL]:
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32

    crypt32.CryptProtectData.argtypes = [
        ctypes.POINTER(DATA_BLOB),
        wintypes.LPCWSTR,
        ctypes.POINTER(DATA_BLOB),
        wintypes.LPVOID,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(DATA_BLOB),
    ]
    crypt32.CryptProtectData.restype = wintypes.BOOL

    crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(DATA_BLOB),
        ctypes.POINTER(wintypes.LPWSTR),
        ctypes.POINTER(DATA_BLOB),
        wintypes.LPVOID,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(DATA_BLOB),
    ]
    crypt32.CryptUnprotectData.restype = wintypes.BOOL

    kernel32.LocalFree.argtypes = [wintypes.HLOCAL]
    kernel32.LocalFree.restype = wintypes.HLOCAL

    return crypt32, kernel32


def _free_local(kernel32: ctypes.WinDLL, blob: DATA_BLOB) -> None:
    if blob.pbData:
        kernel32.LocalFree(ctypes.cast(blob.pbData, wintypes.HLOCAL))


def dpapi_seal(plaintext: bytes, *, entropy: bytes) -> bytes:
    """Seal ``plaintext`` to the current Windows user with required DPAPI entropy."""
    _require_windows()
    crypt32, kernel32 = _configure_dpapi()
    plaintext_blob, plaintext_buffer = _blob_from_bytes(plaintext)
    entropy_blob, _entropy_buffer = _blob_from_bytes(entropy)
    protected_blob = DATA_BLOB()

    try:
        # dwFlags=0 -> user-scope; never CRYPTPROTECT_LOCAL_MACHINE (=4, machine-scope, wrong)
        result: wintypes.BOOL = crypt32.CryptProtectData(
            ctypes.byref(plaintext_blob),
            None,
            ctypes.byref(entropy_blob),
            None,
            None,
            0,
            ctypes.byref(protected_blob),
        )
        if not result:
            raise DpapiError(f"CryptProtectData failed with error {ctypes.GetLastError()}")

        try:
            return ctypes.string_at(protected_blob.pbData, int(protected_blob.cbData))
        finally:
            _free_local(kernel32, protected_blob)
    finally:
        # Best-effort wipe of the plaintext (DEK) copy held in the ctypes buffer.
        ctypes.memset(plaintext_buffer, 0, len(plaintext_buffer))


def dpapi_unseal(blob: bytes, *, entropy: bytes) -> bytearray:
    """Unseal a DPAPI blob to mutable bytes.

    DPAPI here protects against offline disk theft and cross-user access. It does not protect
    against a same-user-credential attacker such as malware or session hijack; that boundary is
    deferred to m2-win-b (Hello) and the Mac SE broker.
    """
    _require_windows()
    crypt32, kernel32 = _configure_dpapi()
    protected_blob, _protected_buffer = _blob_from_bytes(blob)
    entropy_blob, _entropy_buffer = _blob_from_bytes(entropy)
    plaintext_blob = DATA_BLOB()

    result: wintypes.BOOL = crypt32.CryptUnprotectData(
        ctypes.byref(protected_blob),
        None,
        ctypes.byref(entropy_blob),
        None,
        None,
        0,
        ctypes.byref(plaintext_blob),
    )
    if not result:
        raise DpapiError(f"CryptUnprotectData failed with error {ctypes.GetLastError()}")

    try:
        return bytearray(ctypes.string_at(plaintext_blob.pbData, int(plaintext_blob.cbData)))
    finally:
        _free_local(kernel32, plaintext_blob)
