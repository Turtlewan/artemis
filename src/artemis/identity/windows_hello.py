"""Windows Hello consent gate for the owner-private unlock path (m2-win-b, ADR-033).

THREAT BOUNDARY (accepted Phase-1 risk). This is a **process-level software gate,
not a TPM-attested cryptographic binding**. ``verify()`` returns a bool that the
key provider trusts before DPAPI-unsealing the scope keys separately. A local
attacker with in-process code execution (DLL injection, a compromised dependency,
a malicious tool) can bypass it. Accepted until Phase 2 moves the gesture to the
Tauri client window (ADR-025) and the Mac Secure-Enclave broker; the threat model
assumes the process image is not compromised.

CONSOLE-HWND REQUIREMENT. Windows Hello's desktop-app verification must be bound
to a foreground window. A console process supplies its console window handle via
``kernel32.GetConsoleWindow()``. When there is no console window (handle ``0`` —
e.g. a windowless/service host) we **fail closed** with ``NoConsoleWindowError``
rather than fall back to a window-less prompt that may silently not appear.

WINSDK DEVIATION (m2-win-b build, owner-approved). ``winsdk`` 1.0.0b10 does **not**
expose ``IUserConsentVerifierInterop`` / ``RequestVerificationForWindowAsync`` at
the Python level — only the bare UWP ``UserConsentVerifier.request_verification_async``,
which does not reliably prompt for a Win32/console process. So ``verify()`` bridges
to the interop directly through a ``ctypes`` COM shim. The parameterized IID of
``IAsyncOperation<UserConsentVerificationResult>`` is computed with the documented
WinRT ``pinterface`` GUID algorithm (SHA-1 over the type signature); the algorithm
is unit-checked against the published ``IReference<bool>`` IID in the tests.

RATE LIMITING. Delegated to Windows Hello's own OS/TPM lockout (~5 failed gestures
→ lockout). There is no app-level counter for the live gesture — the non-gesture
(test) paths mock ``verify`` and never loop against the OS counter.
"""

from __future__ import annotations

import asyncio
import ctypes
import hashlib
import sys
import time
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from ctypes import POINTER, byref, c_int32, c_uint32, c_void_p, c_wchar_p, wintypes


class HelloError(Exception):
    """Base error for the Windows Hello consent gate."""


class NoConsoleWindowError(HelloError):
    """Raised when the process has no console window to anchor the Hello prompt."""


# --- WinRT / COM constants -------------------------------------------------

# Activatable class whose activation factory implements IUserConsentVerifierInterop.
_USER_CONSENT_VERIFIER_CLASS = "Windows.Security.Credentials.UI.UserConsentVerifier"

# IUserConsentVerifierInterop (userconsentverifierinterop.h).
_IID_USER_CONSENT_VERIFIER_INTEROP = uuid.UUID("39E050C3-4E74-441A-8DC0-B81104DF949C")

# IAsyncInfo (well-known, non-parameterised).
_IID_ASYNC_INFO = uuid.UUID("00000036-0000-0000-C000-000000000046")

# WinRT parameterised-type GUID namespace (Windows.Foundation spec, §"Parameterized
# types"): the v5-UUID namespace SHA-1'd with the type signature.
_WINRT_PINTERFACE_NAMESPACE = uuid.UUID("11f47ad5-7b73-42c0-abae-878b1e16adee")

# Type signature of IAsyncOperation<UserConsentVerificationResult>:
#   pinterface({IAsyncOperation`1 GUID};enum(<runtimeclass name>;<underlying type>))
# IAsyncOperation`1 pinterface GUID = 9FC2B0BB-E446-44E2-AA61-9CAB8F636AF2;
# UserConsentVerificationResult is an i4-backed enum.
_ASYNC_OP_RESULT_SIGNATURE = (
    "pinterface({9fc2b0bb-e446-44e2-aa61-9cab8f636af2};"
    "enum(Windows.Security.Credentials.UI.UserConsentVerificationResult;i4))"
)

# AsyncStatus (Windows.Foundation): Started=0, Completed=1, Canceled=2, Error=3.
_ASYNC_STATUS_STARTED = 0
_ASYNC_STATUS_COMPLETED = 1

# UserConsentVerificationResult.Verified == 0.
_RESULT_VERIFIED = 0

# UserConsentVerifierAvailability.Available == 0.
_AVAILABILITY_AVAILABLE = 0

# RoInitialize apartment type (multithreaded — matches winsdk's default).
_RO_INIT_MULTITHREADED = 1

# Tolerated HRESULTs from RoInitialize when the thread is already initialised.
_S_FALSE = 0x00000001
_RPC_E_CHANGED_MODE = -0x7FFEFEFA  # 0x80010106 as a signed int32


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_uint32),
        ("Data2", ctypes.c_uint16),
        ("Data3", ctypes.c_uint16),
        ("Data4", ctypes.c_ubyte * 8),
    ]

    @classmethod
    def from_uuid(cls, value: uuid.UUID) -> _GUID:
        # The in-memory COM GUID layout is exactly uuid.bytes_le.
        return cls.from_buffer_copy(value.bytes_le)


def _parameterized_iid(signature: str) -> uuid.UUID:
    """Compute a WinRT parameterised-interface IID (v5 UUID over the signature)."""
    digest = bytearray(
        hashlib.sha1(_WINRT_PINTERFACE_NAMESPACE.bytes + signature.encode("utf-8")).digest()[:16]
    )
    digest[6] = (digest[6] & 0x0F) | 0x50  # version 5
    digest[8] = (digest[8] & 0x3F) | 0x80  # RFC 4122 variant
    return uuid.UUID(bytes=bytes(digest))


def _check_hr(hr: int, what: str) -> None:
    """Raise on a failed HRESULT (high bit set → negative as a signed int32)."""
    if hr < 0:
        raise HelloError(f"{what} failed (HRESULT 0x{hr & 0xFFFFFFFF:08X})")


def _com_method(ptr: c_void_p, index: int, *argtypes: type) -> Callable[..., int]:
    """Bind vtable slot ``index`` of the COM object at ``ptr`` as ``HRESULT(this, ...)``."""
    vtable = ctypes.cast(ptr, POINTER(POINTER(c_void_p)))[0]
    proto = ctypes.WINFUNCTYPE(c_int32, c_void_p, *argtypes)
    return proto(vtable[index])


def hello_available() -> bool:
    """Return True only when a Windows Hello verifier device is configured and ready.

    Mirrors ``UserConsentVerifier.CheckAvailabilityAsync() == Available``. Returns
    False on any non-Windows host.

    The winsdk coroutine is driven on a private worker thread rather than the
    caller's thread: ``unlock()`` is invoked from the async FastAPI ``lifespan``,
    where ``asyncio.run()`` on the running loop would raise ``RuntimeError`` — the
    worker thread has no running loop, so it is safe from any context.
    """
    if sys.platform != "win32":
        return False

    from winsdk.windows.security.credentials.ui import UserConsentVerifier

    async def _check() -> int:
        return int(await UserConsentVerifier.check_availability_async())

    with ThreadPoolExecutor(max_workers=1) as pool:
        availability = pool.submit(lambda: asyncio.run(_check())).result()
    return availability == _AVAILABILITY_AVAILABLE


def verify(message: str) -> bool:
    """Prompt for a Windows Hello gesture anchored to the console window.

    Returns True only on a verified gesture; returns False on cancel/timeout/any
    non-verified result (fail closed). Raises ``NoConsoleWindowError`` when there
    is no console window to anchor the prompt, and ``HelloError`` on a COM failure.
    Never unseals anything itself — the caller gates the DPAPI unseal on the bool.
    """
    if sys.platform != "win32":
        raise HelloError("Windows Hello is only available on win32")

    # Declare exact signatures: a default-prototyped GetConsoleWindow returns c_int,
    # which TRUNCATES the 64-bit HWND on win64 (a wrong window handle). Pointer-args
    # are likewise pinned so nothing is silently narrowed.
    kernel32 = ctypes.windll.kernel32
    kernel32.GetConsoleWindow.argtypes = []
    kernel32.GetConsoleWindow.restype = wintypes.HWND

    combase = ctypes.windll.combase
    combase.RoInitialize.argtypes = [c_int32]
    combase.RoInitialize.restype = c_int32
    combase.WindowsCreateString.argtypes = [c_wchar_p, c_uint32, POINTER(c_void_p)]
    combase.WindowsCreateString.restype = c_int32
    combase.WindowsDeleteString.argtypes = [c_void_p]
    combase.WindowsDeleteString.restype = c_int32
    combase.RoGetActivationFactory.argtypes = [c_void_p, POINTER(_GUID), POINTER(c_void_p)]
    combase.RoGetActivationFactory.restype = c_int32

    hwnd = kernel32.GetConsoleWindow()
    if not hwnd:
        raise NoConsoleWindowError("no console window to anchor the Windows Hello prompt")

    # Initialise the apartment; tolerate an already-initialised thread (S_OK /
    # S_FALSE / RPC_E_CHANGED_MODE). Never uninitialise — leave the process as-is.
    hr = combase.RoInitialize(_RO_INIT_MULTITHREADED)
    if hr < 0 and hr != _RPC_E_CHANGED_MODE:
        _check_hr(hr, "RoInitialize")

    class_hs = c_void_p()
    msg_hs = c_void_p()
    interop = c_void_p()
    async_op = c_void_p()
    async_info = c_void_p()
    try:
        _check_hr(
            combase.WindowsCreateString(
                c_wchar_p(_USER_CONSENT_VERIFIER_CLASS),
                len(_USER_CONSENT_VERIFIER_CLASS),
                byref(class_hs),
            ),
            "WindowsCreateString(class)",
        )
        iid_interop = _GUID.from_uuid(_IID_USER_CONSENT_VERIFIER_INTEROP)
        _check_hr(
            combase.RoGetActivationFactory(class_hs, byref(iid_interop), byref(interop)),
            "RoGetActivationFactory",
        )

        _check_hr(
            combase.WindowsCreateString(c_wchar_p(message), len(message), byref(msg_hs)),
            "WindowsCreateString(message)",
        )
        iid_async = _GUID.from_uuid(_parameterized_iid(_ASYNC_OP_RESULT_SIGNATURE))

        # IUserConsentVerifierInterop::RequestVerificationForWindowAsync — vtable
        # slot 6 (IUnknown 0-2, IInspectable 3-5).
        request = _com_method(
            interop, 6, wintypes.HWND, c_void_p, POINTER(_GUID), POINTER(c_void_p)
        )
        _check_hr(
            request(interop, wintypes.HWND(hwnd), msg_hs, byref(iid_async), byref(async_op)),
            "RequestVerificationForWindowAsync",
        )

        # Await: QI the operation for IAsyncInfo and poll Status until it leaves
        # Started, then read the result.
        query_interface = _com_method(async_op, 0, POINTER(_GUID), POINTER(c_void_p))
        iid_async_info = _GUID.from_uuid(_IID_ASYNC_INFO)
        _check_hr(
            query_interface(async_op, byref(iid_async_info), byref(async_info)),
            "QueryInterface(IAsyncInfo)",
        )

        get_status = _com_method(async_info, 7, POINTER(c_int32))  # IAsyncInfo::get_Status
        status = c_int32(_ASYNC_STATUS_STARTED)
        while True:
            _check_hr(get_status(async_info, byref(status)), "IAsyncInfo.Status")
            if status.value != _ASYNC_STATUS_STARTED:
                break
            time.sleep(0.05)

        if status.value != _ASYNC_STATUS_COMPLETED:
            return False  # canceled or error → fail closed

        get_results = _com_method(async_op, 8, POINTER(c_int32))  # IAsyncOperation::GetResults
        result = c_int32(-1)
        _check_hr(get_results(async_op, byref(result)), "IAsyncOperation.GetResults")
        return result.value == _RESULT_VERIFIED
    finally:
        for ptr in (async_info, async_op, interop):
            if ptr:
                _com_method(ptr, 2)(ptr)  # IUnknown::Release
        for handle in (msg_hs, class_hs):
            if handle:
                combase.WindowsDeleteString(handle)
