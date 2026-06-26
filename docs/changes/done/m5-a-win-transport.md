---
spec: m5-a-win-transport
status: ready
token_profile: lean
autonomy_level: L2
---

## Intent
Resolve the M5-a-win-sidecar AF_UNIX fork: this Windows Python 3.12.10 has no `socket.AF_UNIX`, so
the frozen-protocol Unix-socket IPC can't run live on the dev box (the e2e socket test currently
skips). Add a transport seam to `IPCServer` that uses AF_UNIX where available (Mac/Linux) and a
**TCP-loopback** socket on `127.0.0.1` otherwise (Windows), keeping the wire **framing byte-for-byte
identical**. This makes the sidecar fully dev-testable on Windows and gives the (unbuilt) M5-d brain
client a defined rendezvous. Completes M5-a-win-sidecar.

## Key decisions
- **Transport is platform-selected inside `IPCServer.start()`** — the only divergence point. AF_UNIX
  present → bind `audio.sock`, `chmod 0600` (current behaviour, unchanged for Mac). AF_UNIX absent →
  bind `AF_INET`/`SOCK_STREAM` on `("127.0.0.1", 0)` (ephemeral port; **127.0.0.1 ONLY, never
  0.0.0.0**). The accept loop, frame demux, `send_event`/`send_mic_pcm`, and dispatch are already
  transport-agnostic (they use `loop.sock_accept` / `asyncio.open_connection(sock=...)`) — do NOT
  touch them.
- **Port rendezvous = a portfile.** On the TCP path, after `listen()`, read the OS-assigned port via
  `server_socket.getsockname()[1]` and write it (decimal text) to `<data_root>/<slot>/run/audio.port`
  via atomic `.tmp` + `os.replace`, best-effort `chmod 0600`. This mirrors how `audio.sock`'s path was
  the known rendezvous. The AF_UNIX path writes NO portfile (and removes a stale one).
- **Bare loopback, no handshake** (owner decision 2026-06-26). Matches the sidecar's existing
  local-trust posture (peer-uid check already omitted on Windows; "no DEK crosses this socket"). Mac
  production keeps the filesystem-isolated AF_UNIX socket. The Windows-dev exposure (any local process
  may connect to the loopback port) is an accepted dev-only risk.
- **M5-d contract (forward note, not built here):** the brain client connects to `audio.sock` when
  `socket.AF_UNIX` exists, else reads `audio.port` and connects to `127.0.0.1:<port>`. Recorded as a
  banner on `docs/changes/M5-d-voice-loop-orchestrator.md` so the M5-d build follows it. The M5-a Swift
  sidecar (`M5-a-audio-sidecar.md`, Mac) keeps AF_UNIX — no change.

## Gotchas / edge cases
- **Bind 127.0.0.1, not 0.0.0.0** — binding the wildcard would expose the mic-audio/command channel to
  the network. Loopback only.
- **Atomic portfile write** (`.tmp` + `os.replace`) so a client never reads a partial/empty port; write
  the portfile only AFTER `listen()` succeeds (the port isn't assigned until bind, and the client must
  not connect before listen).
- **`endpoint()` accessor** — add a small public read-only accessor (e.g. `IPCServer.endpoint() ->
  tuple`) returning `("unix", socket_path)` or `("tcp", "127.0.0.1", port)` so the e2e test (and later
  M5-d) connects without re-deriving the selection logic. The selection must be computed once in
  `start()` and stored, so `endpoint()` reflects the actual bound transport.
- **`close()` cleanup** — remove `audio.sock` on the AF_UNIX path (current) AND remove `audio.port` on
  the TCP path. Don't leave a stale portfile pointing at a dead port.
- **`chmod 0600` on Windows is best-effort** — `os.chmod` on Windows only toggles the read-only bit; do
  not assert the mode on Windows. The portfile content (a port number) is not a secret under the bare-
  loopback decision.
- **The frozen wire protocol is unchanged** — kinds (0x01/0x02/0x03), framing (1-byte kind + 4-byte BE
  length + body), AudioFormat, events/commands all stay exactly as built. Only the socket family +
  rendezvous-file differ.

## Tasks
1. **Add the transport seam to `IPCServer`.** In `src/artemis/sidecar/audio/ipc_server.py`: compute the
   transport once in `start()` (AF_UNIX if `getattr(socket, "AF_UNIX", None)` else TCP-loopback);
   AF_UNIX branch unchanged (bind `audio.sock` + `chmod 0600`, remove stale portfile); TCP branch binds
   `("127.0.0.1", 0)`, `listen()`, `setblocking(False)`, then atomically writes the assigned port to
   `audio.port` (best-effort `chmod 0600`). Store the resolved transport + port; add a public
   `endpoint()` accessor. Extend `close()` to remove `audio.port` on the TCP path. Leave the accept
   loop / framing / dispatch untouched. — files: `src/artemis/sidecar/audio/ipc_server.py` — done when:
   `uv run --frozen mypy` is clean; `IPCServer.start()` binds without raising on this Windows host (no
   AF_UNIX), `endpoint()` returns `("tcp", "127.0.0.1", <port>)`, and `audio.port` exists with the bound
   port; on an AF_UNIX host the behaviour/`audio.sock`/0600 path is unchanged (no portfile).
2. **Un-skip + generalise the e2e socket test.** In `tests/sidecar/test_audio_e2e.py`: remove the
   `AF_UNIX-unavailable → skip` guard; connect over the server's actual transport via `endpoint()`
   (TCP-loopback on Windows, AF_UNIX elsewhere); keep the separate `ARTEMIS_AUDIO_HW` real-audio skip.
   Add an assertion that on the TCP path `audio.port` is written and matches `endpoint()`. — files:
   `tests/sidecar/test_audio_e2e.py` — done when: `uv run --frozen pytest -q tests/sidecar/test_audio_e2e.py`
   runs the full wakeDetected→speechStart→speechEnd + play→playbackStarted/Finished + barge-in flow over
   a live socket on THIS Windows host (no AF_UNIX skip; only the audio-hardware test skips).
3. **Record the M5-d transport contract.** Add a short amendment banner to
   `docs/changes/M5-d-voice-loop-orchestrator.md` stating the brain client's connection rule (AF_UNIX →
   `audio.sock`; else read `audio.port` → `127.0.0.1:<port>`). Doc-only. — files:
   `docs/changes/M5-d-voice-loop-orchestrator.md` — done when: the banner is present near the spec's
   transport/assumptions section.

## Files to touch
- `src/artemis/sidecar/audio/ipc_server.py` — add the AF_UNIX-or-TCP-loopback transport seam + portfile + `endpoint()`; extend `close()`.
- `tests/sidecar/test_audio_e2e.py` — un-skip; connect via `endpoint()`; assert the portfile on the TCP path.
- `docs/changes/M5-d-voice-loop-orchestrator.md` — transport-contract banner (doc-only).

## Acceptance criteria
- `uv run --frozen mypy` clean; `uv run --frozen ruff check . && uv run --frozen ruff format --check .` clean.
- `uv run --frozen pytest -q` — full suite green; the e2e socket test now RUNS on this Windows host (the AF_UNIX skip is gone), only the `ARTEMIS_AUDIO_HW` real-audio test skips.
- `IPCServer` binds TCP-loopback on this host, publishes `audio.port`, and `endpoint()` reports `("tcp","127.0.0.1",<port>)`; the AF_UNIX path is unchanged on AF_UNIX hosts.

## Commands to run
```bash
uv run --frozen mypy
uv run --frozen ruff check . && uv run --frozen ruff format --check .
uv run --frozen pytest -q
```
