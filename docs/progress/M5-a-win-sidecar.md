# M5-a-win-sidecar — build progress / dep-fix / FORK

Built by Codex (Tasks 2-11 core) + host (Task 1 deps). Host-verified: full `uv run mypy` clean
(313 files), ruff clean, 836 passed / 6 skipped. The dev-buildable core (wire-protocol codec +
state machine + barge-in + IPC contract + orchestrator + all ABCs/fakes) is complete and faithful
to the frozen M5-a contract; real engines are lazy/guarded (voice-dev NOT installed — core builds
against fakes). GATED real-model tasks (12/13) untouched (GPU/mic/Mac).

## DEP-FIX (Task 1, host, owner-approved "fix deps first")
The spec's `[voice-dev]` list did not resolve. Fixes applied to pyproject.toml + uv.lock:
- `livekit-rtc` → `livekit` (livekit-rtc is not a real PyPI package; `livekit` provides `livekit.rtc`).
- `moonshine-voice>=2.0` → `>=0.0.62` (the package is 0.0.x; "v2" referred to the MODEL, not the package).
- `PyAudioWPatch` marked `; sys_platform == 'win32'` (WASAPI loopback is Windows-only; no macOS wheel).
- Added `[tool.uv] environments = [win32/3.12, darwin/3.12]` — scopes uv's resolution universe to
  Artemis's actual targets (Windows dev + Mac prod; NOT linux). This drops the linux split where
  `openwakeword` pulls the cp312-less, linux-only `tflite-runtime`, and the future-Python splits with
  no wheels yet. `requires-python` (>=3.12) unchanged; existing baseline re-verified green (828 passed)
  after the change. **The group now RESOLVES (lock done — AC met).** The full ~5GB `uv sync --group
  voice-dev` heavy install + espeak-ng/cu128 GPU setup remain the GATED on-hardware exercise.

## ⛔ FORK (BIG — planning/owner decision; spec NOT archived, stays in changes/)
**`socket.AF_UNIX` is ABSENT on this Windows Python 3.12.10** (verified: `hasattr(socket,'AF_UNIX')`
== False). The spec's Stop-impact assumption ("Windows AF_UNIX available on the dev box") is FALSE —
CPython on Windows does not expose AF_UNIX here. The frozen M5-a wire protocol uses an AF_UNIX socket
at `<root>/<slot>/run/audio.sock` for brain↔sidecar IPC, so the LIVE socket transport cannot run on
the dev box (the e2e socket test skips gracefully: "AF_UNIX unavailable in this Python build"; the
protocol codec / state machine / barge-in / fakes are all fully tested without a live socket).
Codex correctly built the AF_UNIX contract per the frozen spec and fails-clear if AF_UNIX is missing.
IMPACT: undermines "dev-testable ENTIRELY on Windows" for the socket-IPC path only. The wire FRAMING
(1-byte kind + 4-byte length + body) is transport-agnostic.
DECISION NEEDED: switch the Windows-dev IPC transport to TCP-loopback (127.0.0.1, framing unchanged)
— a small change to `ipc_server.py` + the not-yet-built M5-d brain client, amending the M5-a "AF_UNIX
socket" assumption for the Windows dev twin (Mac/Swift keeps AF_UNIX). Since M5-d is unbuilt, the
transport can be decided now and M5-d built to match. Recommended: TCP-loopback for the Windows twin.
