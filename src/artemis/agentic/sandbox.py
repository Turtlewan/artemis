"""Sandbox seam for Rung 2 command execution.

Windows commands are launched as argv-only processes inside an AppContainer with
no network capabilities and a Job Object on top. The AppContainer package SID is
granted access to the workspace before launch; the process cwd is pinned to the
workspace root. Scoped outbound networking is intentionally deferred: v1 treats
``allow_network=None`` as deny-all and rejects non-empty destination sets.
"""

from __future__ import annotations

import asyncio
import ctypes
import hashlib
import os
import platform
import subprocess
import threading
from collections.abc import Sequence
from ctypes import wintypes
from pathlib import Path
from typing import ClassVar, Protocol, cast

from pydantic import BaseModel, ConfigDict

_OUTPUT_LIMIT = 1_048_576
_WAIT_OBJECT_0 = 0
_WAIT_TIMEOUT = 258
_INFINITE = 0xFFFFFFFF
_CREATE_SUSPENDED = 0x00000004
_CREATE_UNICODE_ENVIRONMENT = 0x00000400
_EXTENDED_STARTUPINFO_PRESENT = 0x00080000
_STARTF_USESTDHANDLES = 0x00000100
_PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES = 0x00020009
_HANDLE_FLAG_INHERIT = 0x00000001
_DUPLICATE_SAME_ACCESS = 0x00000002
_JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x00002000
_JOB_OBJECT_LIMIT_PROCESS_MEMORY = 0x00000100
_JOB_OBJECT_LIMIT_JOB_MEMORY = 0x00000200
_JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS = 9
_STILL_ACTIVE = 259


class CommandResult(BaseModel):
    """Deterministic subprocess result returned by the command spine."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False


class Sandbox(Protocol):
    """Swap-able command sandbox seam."""

    async def run(
        self,
        argv: Sequence[str],
        *,
        workspace_root: Path,
        allow_network: frozenset[str] | None = None,
        timeout_s: int = 30,
    ) -> CommandResult: ...


class SandboxUnavailableError(RuntimeError):
    """Raised when the requested sandbox cannot be exercised fail-closed."""


class WindowsAppContainerSandbox:
    """Windows AppContainer + Job Object sandbox with deny-all networking."""

    _profile_prefix: ClassVar[str] = "artemis-rung2"

    async def run(
        self,
        argv: Sequence[str],
        *,
        workspace_root: Path,
        allow_network: frozenset[str] | None = None,
        timeout_s: int = 30,
    ) -> CommandResult:
        """Run ``argv`` with shell evaluation disabled and bounded output."""
        if platform.system() != "Windows":
            raise SandboxUnavailableError("WindowsAppContainerSandbox requires Windows")
        if not argv:
            return CommandResult(exit_code=2, stdout="", stderr="argv must not be empty")
        if allow_network:
            return CommandResult(
                exit_code=2,
                stdout="",
                stderr="scoped allow_network is deferred; v1 supports deny-all only",
            )

        workspace = workspace_root.resolve()
        workspace.mkdir(parents=True, exist_ok=True)
        if not _mpssvc_running():
            return CommandResult(
                exit_code=2,
                stdout="",
                stderr="MPSSVC is not running; refusing sandbox launch fail-closed",
            )

        try:
            return await asyncio.to_thread(
                _run_appcontainer_process,
                tuple(str(part) for part in argv),
                workspace,
                timeout_s,
            )
        except SandboxUnavailableError as exc:
            return CommandResult(exit_code=2, stdout="", stderr=str(exc))
        except OSError as exc:
            return CommandResult(exit_code=2, stdout="", stderr=f"sandbox launch failed: {exc}")


class DockerSandbox:
    """Mac-gated Docker/remote seam placeholder for ``--network none`` parity."""

    async def run(
        self,
        argv: Sequence[str],
        *,
        workspace_root: Path,
        allow_network: frozenset[str] | None = None,
        timeout_s: int = 30,
    ) -> CommandResult:
        del argv, workspace_root, allow_network, timeout_s
        if platform.system() != "Darwin":
            raise SandboxUnavailableError("Mac-gated DockerSandbox is unavailable on this dev box")
        raise SandboxUnavailableError("Mac-gated DockerSandbox is not built in the Windows profile")


class _SecurityAttributes(ctypes.Structure):
    _fields_ = [
        ("nLength", wintypes.DWORD),
        ("lpSecurityDescriptor", wintypes.LPVOID),
        ("bInheritHandle", wintypes.BOOL),
    ]


class _ProcessInformation(ctypes.Structure):
    _fields_ = [
        ("hProcess", wintypes.HANDLE),
        ("hThread", wintypes.HANDLE),
        ("dwProcessId", wintypes.DWORD),
        ("dwThreadId", wintypes.DWORD),
    ]


class _STARTUPINFO(ctypes.Structure):
    _fields_ = [
        ("cb", wintypes.DWORD),
        ("lpReserved", wintypes.LPWSTR),
        ("lpDesktop", wintypes.LPWSTR),
        ("lpTitle", wintypes.LPWSTR),
        ("dwX", wintypes.DWORD),
        ("dwY", wintypes.DWORD),
        ("dwXSize", wintypes.DWORD),
        ("dwYSize", wintypes.DWORD),
        ("dwXCountChars", wintypes.DWORD),
        ("dwYCountChars", wintypes.DWORD),
        ("dwFillAttribute", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("wShowWindow", wintypes.WORD),
        ("cbReserved2", wintypes.WORD),
        ("lpReserved2", wintypes.LPBYTE),
        ("hStdInput", wintypes.HANDLE),
        ("hStdOutput", wintypes.HANDLE),
        ("hStdError", wintypes.HANDLE),
    ]


class _STARTUPINFOEX(ctypes.Structure):
    _fields_ = [
        ("StartupInfo", _STARTUPINFO),
        ("lpAttributeList", wintypes.LPVOID),
    ]


class _SecurityCapabilities(ctypes.Structure):
    _fields_ = [
        ("AppContainerSid", wintypes.LPVOID),
        ("Capabilities", wintypes.LPVOID),
        ("CapabilityCount", wintypes.DWORD),
        ("Reserved", wintypes.DWORD),
    ]


class _JobObjectBasicLimitInformation(ctypes.Structure):
    _fields_ = [
        ("PerProcessUserTimeLimit", ctypes.c_int64),
        ("PerJobUserTimeLimit", ctypes.c_int64),
        ("LimitFlags", wintypes.DWORD),
        ("MinimumWorkingSetSize", ctypes.c_size_t),
        ("MaximumWorkingSetSize", ctypes.c_size_t),
        ("ActiveProcessLimit", wintypes.DWORD),
        ("Affinity", ctypes.c_size_t),
        ("PriorityClass", wintypes.DWORD),
        ("SchedulingClass", wintypes.DWORD),
    ]


class _IoCounters(ctypes.Structure):
    _fields_ = [
        ("ReadOperationCount", ctypes.c_uint64),
        ("WriteOperationCount", ctypes.c_uint64),
        ("OtherOperationCount", ctypes.c_uint64),
        ("ReadTransferCount", ctypes.c_uint64),
        ("WriteTransferCount", ctypes.c_uint64),
        ("OtherTransferCount", ctypes.c_uint64),
    ]


class _JobObjectExtendedLimitInformation(ctypes.Structure):
    _fields_ = [
        ("BasicLimitInformation", _JobObjectBasicLimitInformation),
        ("IoInfo", _IoCounters),
        ("ProcessMemoryLimit", ctypes.c_size_t),
        ("JobMemoryLimit", ctypes.c_size_t),
        ("PeakProcessMemoryUsed", ctypes.c_size_t),
        ("PeakJobMemoryUsed", ctypes.c_size_t),
    ]


def _run_appcontainer_process(
    argv: tuple[str, ...],
    workspace: Path,
    timeout_s: int,
) -> CommandResult:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    userenv = ctypes.WinDLL("userenv", use_last_error=True)
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)

    _configure_winapi(kernel32, userenv, advapi32)
    package_name = _profile_name(workspace)
    package_sid = _appcontainer_sid(userenv, package_name)
    sid_string = _sid_string(advapi32, kernel32, package_sid)

    temp_dir = workspace / ".agent_tmp"
    temp_dir.mkdir(exist_ok=True)
    _grant_workspace_acl(workspace, sid_string)
    _grant_workspace_acl(temp_dir, sid_string)
    executable = Path(argv[0])
    if executable.is_absolute():
        _grant_read_execute_acl(executable.parent, sid_string)

    stdout_read, stdout_write = _create_pipe(kernel32)
    stderr_read, stderr_write = _create_pipe(kernel32)
    stdin_read, stdin_write = _create_pipe(kernel32)
    handles = [stdout_read, stdout_write, stderr_read, stderr_write, stdin_read, stdin_write]
    job_handle = wintypes.HANDLE()
    process_info = _ProcessInformation()
    attr_list = None
    attr_buffer: ctypes.Array[ctypes.c_byte] | None = None

    try:
        _disable_inherit(kernel32, stdout_read)
        _disable_inherit(kernel32, stderr_read)
        _disable_inherit(kernel32, stdin_write)
        startup = _STARTUPINFOEX()
        startup.StartupInfo.cb = ctypes.sizeof(_STARTUPINFOEX)
        startup.StartupInfo.dwFlags = _STARTF_USESTDHANDLES
        startup.StartupInfo.hStdInput = stdin_read
        startup.StartupInfo.hStdOutput = stdout_write
        startup.StartupInfo.hStdError = stderr_write

        security_capabilities = _SecurityCapabilities(
            AppContainerSid=package_sid,
            Capabilities=None,
            CapabilityCount=0,
            Reserved=0,
        )
        attr_buffer, attr_size = _attribute_buffer(kernel32)
        attr_list = ctypes.cast(attr_buffer, wintypes.LPVOID)
        if not kernel32.InitializeProcThreadAttributeList(
            attr_list,
            1,
            0,
            ctypes.byref(attr_size),
        ):
            _raise_last_error("InitializeProcThreadAttributeList")
        if not kernel32.UpdateProcThreadAttribute(
            attr_list,
            0,
            _PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES,
            ctypes.byref(security_capabilities),
            ctypes.sizeof(security_capabilities),
            None,
            None,
        ):
            _raise_last_error("UpdateProcThreadAttribute")
        startup.lpAttributeList = attr_list

        command_line = ctypes.create_unicode_buffer(subprocess.list2cmdline(argv))
        env = _environment_block({"TEMP": str(temp_dir), "TMP": str(temp_dir)})
        env_buffer = ctypes.create_unicode_buffer(env)
        flags = _EXTENDED_STARTUPINFO_PRESENT | _CREATE_UNICODE_ENVIRONMENT | _CREATE_SUSPENDED
        if not kernel32.CreateProcessW(
            None,
            command_line,
            None,
            None,
            True,
            flags,
            env_buffer,
            str(workspace),
            ctypes.byref(startup),
            ctypes.byref(process_info),
        ):
            _raise_last_error("CreateProcessW")

        _close_many(kernel32, [stdout_write, stderr_write, stdin_read, stdin_write])
        handles = [stdout_read, stderr_read]
        job_handle = _create_job(kernel32)
        if not kernel32.AssignProcessToJobObject(job_handle, process_info.hProcess):
            _raise_last_error("AssignProcessToJobObject")
        if kernel32.ResumeThread(process_info.hThread) == wintypes.DWORD(-1).value:
            _raise_last_error("ResumeThread")

        stdout_task = _HandleReader(stdout_read)
        stderr_task = _HandleReader(stderr_read)
        stdout_task.start()
        stderr_task.start()
        wait = kernel32.WaitForSingleObject(process_info.hProcess, max(timeout_s, 1) * 1000)
        timed_out = wait == _WAIT_TIMEOUT
        if timed_out:
            kernel32.TerminateJobObject(job_handle, 124)
            kernel32.WaitForSingleObject(process_info.hProcess, _INFINITE)
        elif wait != _WAIT_OBJECT_0:
            _raise_last_error("WaitForSingleObject")

        exit_code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(process_info.hProcess, ctypes.byref(exit_code)):
            _raise_last_error("GetExitCodeProcess")
        code = 124 if timed_out and exit_code.value == _STILL_ACTIVE else int(exit_code.value)
        stdout = stdout_task.result()
        stderr = stderr_task.result()
        stdout, stderr = _cap_combined(stdout, stderr)
        return CommandResult(exit_code=code, stdout=stdout, stderr=stderr, timed_out=timed_out)
    finally:
        if attr_list is not None:
            kernel32.DeleteProcThreadAttributeList(attr_list)
        if package_sid:
            advapi32.FreeSid(package_sid)
        _close_many(
            kernel32,
            [
                process_info.hThread,
                process_info.hProcess,
                job_handle,
                *handles,
            ],
        )


def _configure_winapi(
    kernel32: ctypes.WinDLL,
    userenv: ctypes.WinDLL,
    advapi32: ctypes.WinDLL,
) -> None:
    userenv.CreateAppContainerProfile.argtypes = [
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.LPVOID),
    ]
    userenv.CreateAppContainerProfile.restype = ctypes.c_long
    userenv.DeriveAppContainerSidFromAppContainerName.argtypes = [
        wintypes.LPCWSTR,
        ctypes.POINTER(wintypes.LPVOID),
    ]
    userenv.DeriveAppContainerSidFromAppContainerName.restype = ctypes.c_long
    advapi32.ConvertSidToStringSidW.argtypes = [
        wintypes.LPVOID,
        ctypes.POINTER(wintypes.LPWSTR),
    ]
    advapi32.ConvertSidToStringSidW.restype = wintypes.BOOL
    advapi32.FreeSid.argtypes = [wintypes.LPVOID]
    advapi32.FreeSid.restype = wintypes.LPVOID
    kernel32.InitializeProcThreadAttributeList.argtypes = [
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.c_size_t),
    ]
    kernel32.InitializeProcThreadAttributeList.restype = wintypes.BOOL
    kernel32.UpdateProcThreadAttribute.restype = wintypes.BOOL
    kernel32.CreateProcessW.restype = wintypes.BOOL


def _profile_name(workspace: Path) -> str:
    digest = hashlib.sha256(str(workspace).encode("utf-8")).hexdigest()[:24]
    return f"{WindowsAppContainerSandbox._profile_prefix}-{digest}"


def _appcontainer_sid(userenv: ctypes.WinDLL, package_name: str) -> wintypes.LPVOID:
    package_sid = wintypes.LPVOID()
    created = userenv.CreateAppContainerProfile(
        package_name,
        package_name,
        "Artemis Rung 2 command sandbox",
        None,
        0,
        ctypes.byref(package_sid),
    )
    if created < 0:
        derived = userenv.DeriveAppContainerSidFromAppContainerName(
            package_name,
            ctypes.byref(package_sid),
        )
        if derived < 0:
            raise SandboxUnavailableError(
                f"AppContainer profile unavailable: HRESULT 0x{derived & 0xFFFFFFFF:08x}"
            )
    return package_sid


def _sid_string(
    advapi32: ctypes.WinDLL,
    kernel32: ctypes.WinDLL,
    package_sid: wintypes.LPVOID,
) -> str:
    raw = wintypes.LPWSTR()
    if not advapi32.ConvertSidToStringSidW(package_sid, ctypes.byref(raw)):
        _raise_last_error("ConvertSidToStringSidW")
    try:
        return str(raw.value)
    finally:
        kernel32.LocalFree(raw)


def _grant_workspace_acl(path: Path, sid_string: str) -> None:
    subprocess.run(
        ["icacls", str(path), "/grant", f"*{sid_string}:(OI)(CI)M", "/T", "/C"],
        check=True,
        capture_output=True,
        text=True,
        shell=False,
    )


def _grant_read_execute_acl(path: Path, sid_string: str) -> None:
    subprocess.run(
        ["icacls", str(path), "/grant", f"*{sid_string}:(OI)(CI)RX", "/T", "/C"],
        check=True,
        capture_output=True,
        text=True,
        shell=False,
    )


def _create_pipe(kernel32: ctypes.WinDLL) -> tuple[wintypes.HANDLE, wintypes.HANDLE]:
    read_handle = wintypes.HANDLE()
    write_handle = wintypes.HANDLE()
    attrs = _SecurityAttributes(ctypes.sizeof(_SecurityAttributes), None, True)
    if not kernel32.CreatePipe(
        ctypes.byref(read_handle),
        ctypes.byref(write_handle),
        ctypes.byref(attrs),
        0,
    ):
        _raise_last_error("CreatePipe")
    return read_handle, write_handle


def _disable_inherit(kernel32: ctypes.WinDLL, handle: wintypes.HANDLE) -> None:
    if not kernel32.SetHandleInformation(handle, _HANDLE_FLAG_INHERIT, 0):
        _raise_last_error("SetHandleInformation")


def _attribute_buffer(
    kernel32: ctypes.WinDLL,
) -> tuple[ctypes.Array[ctypes.c_byte], ctypes.c_size_t]:
    size = ctypes.c_size_t()
    kernel32.InitializeProcThreadAttributeList(None, 1, 0, ctypes.byref(size))
    return (ctypes.c_byte * size.value)(), size


def _environment_block(overrides: dict[str, str]) -> str:
    env = dict(os.environ)
    env.update(overrides)
    return "\0".join(f"{key}={value}" for key, value in sorted(env.items())) + "\0\0"


def _create_job(kernel32: ctypes.WinDLL) -> wintypes.HANDLE:
    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        _raise_last_error("CreateJobObjectW")
    limits = _JobObjectExtendedLimitInformation()
    limits.BasicLimitInformation.LimitFlags = (
        _JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        | _JOB_OBJECT_LIMIT_PROCESS_MEMORY
        | _JOB_OBJECT_LIMIT_JOB_MEMORY
    )
    limits.ProcessMemoryLimit = 512 * 1024 * 1024
    limits.JobMemoryLimit = 768 * 1024 * 1024
    if not kernel32.SetInformationJobObject(
        job,
        _JOB_OBJECT_EXTENDED_LIMIT_INFORMATION_CLASS,
        ctypes.byref(limits),
        ctypes.sizeof(limits),
    ):
        _raise_last_error("SetInformationJobObject")
    return cast(wintypes.HANDLE, job)


class _HandleReader:
    def __init__(self, handle: wintypes.HANDLE) -> None:
        self._handle = handle
        self._value = ""
        self._thread = threading.Thread(target=self._read, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def result(self) -> str:
        self._thread.join(timeout=5)
        return self._value

    def _read(self) -> None:
        self._value = _read_handle_sync(self._handle)


def _read_handle_sync(handle: wintypes.HANDLE) -> str:
    if handle.value is None:
        return ""
    fd = msvcrt_open_osfhandle(int(handle.value), os.O_RDONLY)
    chunks: list[bytes] = []
    retained = 0
    with os.fdopen(fd, "rb", closefd=True) as stream:
        while True:
            data = stream.read(65_536)
            if not data:
                break
            if retained < _OUTPUT_LIMIT:
                chunk = data[: _OUTPUT_LIMIT - retained]
                chunks.append(chunk)
                retained += len(chunk)
    return b"".join(chunks).decode("utf-8", errors="replace")


def msvcrt_open_osfhandle(handle: int, flags: int) -> int:
    import msvcrt

    return msvcrt.open_osfhandle(handle, flags)


def _cap_combined(stdout: str, stderr: str) -> tuple[str, str]:
    encoded_out = stdout.encode("utf-8", errors="replace")
    encoded_err = stderr.encode("utf-8", errors="replace")
    remaining = _OUTPUT_LIMIT
    out = encoded_out[:remaining]
    remaining -= len(out)
    err = encoded_err[:remaining]
    return out.decode("utf-8", errors="replace"), err.decode("utf-8", errors="replace")


def _mpssvc_running() -> bool:
    if platform.system() != "Windows":
        return False
    result = subprocess.run(
        ["sc", "query", "mpssvc"],
        check=False,
        capture_output=True,
        text=True,
        shell=False,
    )
    return result.returncode == 0 and "RUNNING" in result.stdout


def _close_many(kernel32: ctypes.WinDLL, handles: Sequence[wintypes.HANDLE | int | None]) -> None:
    for handle in handles:
        if handle is None:
            continue
        value = handle.value if isinstance(handle, wintypes.HANDLE) else handle
        if value:
            kernel32.CloseHandle(handle)


def _raise_last_error(api: str) -> None:
    error = ctypes.get_last_error()
    raise OSError(error, f"{api} failed")
