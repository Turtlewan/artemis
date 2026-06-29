---
status: ready
coder_effort: medium
cross_model_review: true
---

# harden-background-invariants

Make the two shared background JSON stores concurrency-safe by construction so the latent
auth-counter / queue races are closed even if the single-uvicorn-worker assumption is ever broken.
Rationale + adjudication: `docs/findings/tier1-concurrency-audit-2026-06-29.md`.

## Files to change
- `src/artemis/file_lock.py` — **create** (cross-platform advisory file lock helper).
- `src/artemis/identity/app_auth.py` — **modify** (`DeviceRegistry` read-modify-write under file lock).
- `src/artemis/proactive/tier1_queue.py` — **modify** (`Tier1Queue` `_items` mutate+persist under a `threading.Lock`).
- `tests/test_file_lock.py` — **create**.
- `tests/test_app_auth.py` · `tests/test_tier1_queue.py` — **modify** (add the concurrency-guard assertions; if `test_tier1_queue.py` does not exist, create it).

## Exact changes

### Task 1 — cross-platform advisory file lock + apply to `DeviceRegistry`

**`src/artemis/file_lock.py` (new).** Blocking exclusive lock on a sidecar lockfile, POSIX `fcntl` /
Windows `msvcrt`, usable as a context manager:

```python
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
        msvcrt.locking(fd, msvcrt.LK_LCK, 1)

    def _release(fd: int) -> None:
        os.lseek(fd, 0, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)

else:
    import fcntl

    def _acquire(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_EX)

    def _release(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_UN)
```

**`src/artemis/identity/app_auth.py`.** Import the helper and wrap every `DeviceRegistry`
read-modify-write so the read and the dependent write are one critical section. `DeviceRegistry`
holds no in-memory cache (each call re-reads the file), so a process-level file lock fully closes the
cross-process counter lost-update.

- Add `from artemis.file_lock import file_lock`.
- In `register`, `remove`, and `bump_counter`, wrap the `_read_all()` → mutate → `_write_all()` body
  in `with file_lock(self._path):`. Example for `bump_counter`:

```python
    def bump_counter(self, device_id: str, new_counter: int) -> None:
        """Persist a caller-validated strictly greater counter."""
        with file_lock(self._path):
            devices = self._read_all()
            device = devices.get(device_id)
            if device is None:
                raise AuthError
            devices[device_id] = RegisteredDevice(
                device_id=device.device_id,
                public_key_b64=device.public_key_b64,
                counter=new_counter,
                paired_at=device.paired_at,
            )
            self._write_all(devices)
```

  Apply the same `with file_lock(self._path):` wrapper to the bodies of `register` and `remove`.
  `get`, `list`, and the `_read_all`/`_write_all` helpers are unchanged (pure read or already-atomic write).

### Task 2 — guard `Tier1Queue` in-memory state with a `threading.Lock`

**`src/artemis/proactive/tier1_queue.py`.** `Tier1Queue` caches `_items` in memory; the documented
risk is a future path calling `enqueue` from a second thread while a drain runs. Add a re-entrant-free
`threading.Lock` covering each mutate+persist, and the drain's snapshot + per-item mutation.

- In `__init__`, add `self._lock = threading.Lock()` (the module already imports `threading`).
- Wrap the bodies of `enqueue`, `_remove`, and `_fail` in `with self._lock:` (each does an `_items`
  mutation followed by `_persist()` — both must be inside the lock).
- In `_drain_async`, take the snapshot and each per-item `_remove`/`_fail` under the lock. Keep the
  `await _handle_with_delivery_count(...)` call **outside** the lock (never hold a lock across an
  await). Concretely: snapshot `items = list(self._items.values())` under the lock at the top; for each
  item, the terminal `self._remove(item)` / `self._fail(...)` calls already re-acquire the lock via
  their own `with self._lock:`, so do **not** double-wrap — instead remove the per-call wrapper risk by
  having `_drain_async` call the existing `_remove`/`_fail` (now lock-guarded) directly.

> Note for the builder: `_remove` and `_fail` acquire `self._lock`; `_drain_async` must NOT hold the
> lock when it calls them (would deadlock a non-reentrant Lock). Take the lock only for the initial
> `list(self._items.values())` snapshot, release before the loop, then let `_remove`/`_fail` self-guard.

## Acceptance criteria
1. New helper → `with file_lock(tmp_path / "x.json"): pass` acquires and releases without error on this
   host; a second `file_lock` on the same path in the same process after the block exits succeeds.
   Verify: `uv run pytest tests/test_file_lock.py -q`.
2. `DeviceRegistry.bump_counter` still raises `AuthError` for an unknown device and persists the new
   counter for a known one, now inside the lock. Verify: `uv run pytest tests/test_app_auth.py -q`.
3. `Tier1Queue.enqueue` + drain still coalesce, persist, and remove on confirmed delivery exactly as
   before (no behavioural change); drain does not deadlock. Verify: `uv run pytest tests/test_tier1_queue.py -q`.
4. No regression. Verify: full `uv run mypy` clean + `uv run pytest -q` green.

## Commands to run
```sh
uv run pytest tests/test_file_lock.py tests/test_app_auth.py tests/test_tier1_queue.py -q
uv run mypy
uv run pytest -q
```
