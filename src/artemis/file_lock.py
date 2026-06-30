"""Cross-platform exclusive advisory file lock for shared-JSON stores."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


@contextmanager
def file_lock(target: Path) -> Iterator[None]:
    """Hold an exclusive advisory lock for the duration of the block.

    Locks a sidecar ``<target>.lock`` file (never the data file itself, so the
    atomic os.replace swap is unaffected). Blocking acquire. Cross-process on
    both POSIX (fcntl) and Windows (msvcrt).
    """
    lock_path = target.with_name(target.name + ".lock")
    lock_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        _acquire(fd)
        try:
            yield
        finally:
            _release(fd)
    finally:
        os.close(fd)


if os.name == "nt":
    import msvcrt

    def _acquire(fd: int) -> None:
        # Block on a 1-byte exclusive lock at offset 0.
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_LOCK, 1)

    def _release(fd: int) -> None:
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)


else:
    import fcntl

    def _acquire(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_EX)  # type: ignore[attr-defined]

    def _release(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_UN)  # type: ignore[attr-defined]
