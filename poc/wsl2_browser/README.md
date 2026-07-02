# WSL2 Headless-Chromium Feasibility Spike

Throwaway proof for launching headless Chromium **inside** the existing hardened WSL2 isolate
(`src/artemis/capabilities/sandbox_wsl2.py`'s netns + nginx SNI-allowlist proxy + de-privileged
setpriv mechanism) and extracting JS-rendered page text through the egress allowlist, to de-risk
replacing the current no-JS `TrafilaturaFetcher` (`src/artemis/reachout/fetch.py`) with a
browser-based fetcher for pages it can't read (e.g. Wikipedia).

**Verdict: FEASIBLE-WITH-CAVEATS.** Headless Chromium runs cleanly inside the exact isolation
mechanism `sandbox_wsl2.py` already uses, stays contained, fits the resource envelope with huge
headroom, and beats the status quo fetcher on the target page in ~1.2s. The one hard caveat: you
**must** use `chrome-headless-shell` (Playwright's minimal automation binary), not full `chrome`
(apt/snap) — full `chrome` makes background TLS connections to Google infrastructure that the
SNI-allowlist proxy correctly blocks, and the resulting retry churn reliably blew a 60s budget.

## Provisioning

```bash
# Full chrome via apt pulls the Ubuntu 24.04 SNAP (chromium-browser is a transitional package) --
# this was slow (~10+ min, stalled on core/gnome/mesa/cups base-snap downloads) and, per the
# finding above, the wrong binary to use anyway. Do NOT use this path for the real fetcher.
#   wsl.exe -d Ubuntu -- sudo apt-get install -y chromium-browser

# What actually worked, fast (~3 min total): Playwright's chromium download via a throwaway venv,
# used only to fetch the browser binaries -- the `playwright` Python package itself is NOT used
# at runtime (render.py drives chrome-headless-shell as a subprocess, stdlib only).
wsl.exe -d Ubuntu -- sudo apt-get install -y python3.12-venv
wsl.exe -d Ubuntu -- sudo python3 -m venv /opt/pwvenv
wsl.exe -d Ubuntu -- sudo /opt/pwvenv/bin/pip install playwright
wsl.exe -d Ubuntu -- sudo /opt/pwvenv/bin/playwright install chromium
wsl.exe -d Ubuntu -- sudo /opt/pwvenv/bin/playwright install-deps chromium   # runtime .so deps (nspr, nss, etc.)

# Copy to a world-readable path (the isolate de-privileges to uid 4000; /root/.cache is 700):
wsl.exe -d Ubuntu -- sudo mkdir -p /opt/chromium_headless_shell
wsl.exe -d Ubuntu -- sudo cp -r /root/.cache/ms-playwright/chromium_headless_shell-*/chrome-headless-shell-linux64/. /opt/chromium_headless_shell/
wsl.exe -d Ubuntu -- sudo chmod -R a+rX /opt/chromium_headless_shell
```

Note on invoking `wsl.exe` from a Windows git-bash shell: set `MSYS_NO_PATHCONV=1` on every call.
Without it, MSYS silently rewrites unix-looking arguments (e.g. `/opt/chromium/chrome`) into
mangled Windows paths before `wsl.exe` ever sees them — this cost real debugging time and is not
a WSL/isolate issue, it's a git-bash argv-translation quirk. `run.py` (invoked via native Windows
Python, not git-bash) is unaffected and needs no such workaround.

## Layout

- `isolate.sh` — standalone copy of `sandbox_wsl2.py`'s `_ISOLATE_SCRIPT` (netns, veth, nginx
  SNI/Host allowlist proxy, dnsmasq DNS stub, cgroup+ulimit caps, mount+pid ns, setpriv de-priv).
  Adds a `memory.peak` read after the run for the resource-envelope check, and a `DEBUG_KEEP=1`
  escape hatch (skips cleanup) used during debugging. NOT wired to `src/`, not a src/ edit.
- `run.py` — host-side runner: `python run.py <url> <allowlist-csv> [--mem-mb N] [--timeout S]`.
- `capability/render.py` — in-isolate script: launches `chrome-headless-shell --headless
  --dump-dom`, extracts visible text with stdlib `html.parser` (no pip deps available in-isolate).
- `capability/ssrf_probe.py` — in-isolate script: curls localhost/LAN targets to prove no route.
- `capability/hello.py` — trivial no-op capability, used to isolate "does the cage work" from
  "does chrome behave" while debugging.

## Results

_Verified on this host 2026-07-02 (Ubuntu 24.04 WSL2, kernel 6.6.87, Chrome for Testing 149.0.7827.55
/ chrome-headless-shell build 1228, via Playwright's downloader)._

| # | Check | Result | Evidence |
|---|---|---|---|
| 1 | Chromium launches headless in-netns, de-privileged | ✅ PASS | `chrome-headless-shell` launches in 0.17-0.85s through the full netns+mount+pid-ns+cgroup+setpriv chain. `--no-sandbox` is only required if chrome runs **as root**; since the isolate already de-privileges to uid 4000 before exec, it was empirically **not required** in the full chain (tested both ways) — kept anyway for robustness since it costs nothing and avoids relying on chrome's internal namespace-sandbox needing capabilities `setpriv --bounding-set=-all` already stripped. |
| 2 | JS extraction beats status quo (Wikipedia) | ✅ PASS | `TrafilaturaFetcher` confirmed to fail: direct `httpx.get` on `en.wikipedia.org/wiki/Python_(programming_language)` returns **403** (bot/UA block, not actually a JS-rendering gap), trafilatura extracts 0 chars. The sandboxed fetch, allowlist=`en.wikipedia.org` only, returned **95KB of correct clean text** (full article, nav through footer) in 1.2-1.4s, peak memory 148-163MB. |
| 3 | Egress containment holds for browser traffic | ✅ PASS | Fetching `https://www.bing.com` against an `example.com`-only allowlist returned **empty text**; nginx logged `no host in upstream` (SNI `www.bing.com` not in the map → default-deny). QUIC/UDP: `--disable-quic` passed as defense-in-depth, but the real boundary is structural — `iptables -L OUTPUT` in the netns shows no ACCEPT rule for udp/443 under uid 4000, only udp/53→DNS_STUB is accepted, everything else (QUIC included) hits the terminal `DROP` for that uid. |
| 4 | Asset-domain reality | ✅ PASS — first-party-only is enough for text | Wikipedia fetch with allowlist=`en.wikipedia.org` only produced the **complete** article text (95KB, full TOC through the copyright footer) despite ~47+ blocked subresource requests (`upload.wikimedia.org` images/styles etc. all correctly denied, logged as `no host in upstream`). Re-running with `en.wikipedia.org,upload.wikimedia.org` allowlisted made **no measurable difference** to the extracted text (154KB peak mem vs 150KB, same ~1.2s) — MediaWiki serves full article text server-rendered in the initial HTML, so asset domains only matter if the fetcher also needs images, not for text extraction. |
| 5 | SSRF/localhost blocked | ✅ PASS | With a Python `http.server` bound to `127.0.0.1:8030` on the WSL **host** (outside the isolate), a curl from inside the isolate's netns to `http://127.0.0.1:8030` failed instantly (`Couldn't connect to server` — the netns's own loopback has nothing bound there, it cannot reach the host's). A curl to the host's real LAN IP (`172.26.202.180:8030`) timed out (caught by the terminal default-deny `DROP` for uid 4000 — port 8030 has no allow rule). |
| 6 | Resource envelope | ✅ PASS, large headroom | Peak memory (read from cgroup `memory.peak`, which aggregates the whole chrome process tree) ranged **76MB** (`about:blank`) to **163MB** (Wikipedia, full article). Retested against the **production default cap** (`SandboxCaps.memory_mb = 512`) — fits comfortably, no need to raise it for a single in-flight fetch. On an 8GB box this is a small fraction; the real constraint for concurrency is running N fetches in parallel (≈150MB × N), not a single fetch. |
| 7 | Latency | ✅ PASS, with a sharp caveat | Cold isolate-setup + chrome-headless-shell launch + render + extract: **0.8-1.4s** across multiple pages/repeats (Wikipedia averaged ~1.25s). httpx baseline (`example.com`, host-side, no sandbox): **0.25s**. So ~3-5x slower than the no-JS fetcher, comfortably sub-2-second — **but only with chrome-headless-shell**. The same fetch with full desktop `chrome` reliably took **45-60s+ or hung outright** (see finding below) — a 40-75x regression from picking the wrong binary. cgroup CPU quota was NOT the bottleneck: re-tested chrome-headless-shell under a 1-core quota (`cpu.max = "100000 100000"`) and it was still 1.36s — the earlier "raise to 4 cores" hypothesis was a red herring chased before the real cause (below) was found. |

## Load-bearing findings

**1. Use `chrome-headless-shell`, never full `chrome`, inside the sandbox.** This is the single
most important finding. Full `chrome` (from the Ubuntu 24.04 apt/snap package or Playwright's
`chromium` download) opens background TLS connections at startup to Google infrastructure —
observed via packet capture: `redirector.gvt1.com`, `accounts.google.com`,
`android.clients.google.com` (component updater / sign-in-consistency / GCM-style checks). The
SNI-allowlist proxy correctly rejects all of them (not on the allowlist), but chrome retries
persistently, and that churn reliably consumed 45-60+ seconds — sometimes indefinitely — even for
a trivial `about:blank` or a single-domain fetch. A large, well-known "disable background
networking" CI flag set (Puppeteer's defaults) did **not** fix it. Switching to
`chrome-headless-shell` — Playwright's purpose-built minimal automation binary, which lacks this
background-service integration entirely — fixed it completely: same isolate, same allowlist, sub-
second every time. The real fetcher spec must pin this binary choice explicitly, not "any
chromium".

**2. The isolation mechanism itself (netns/nginx-SNI-proxy/cgroup/setpriv) needed zero changes**
to host a browser — every hang and failure during this spike traced back to chrome-specific
behavior (crashpad needing an explicit `--user-data-dir` + `$HOME` under a non-root uid with no
writable home; the background-networking churn above), never to the isolate's network, cgroup, or
privilege-drop layers. Egress containment, SSRF blocking, and the DNS-sinkhole/SNI-redirect design
all worked exactly as `sandbox_wsl2.py` intends, first try, once chrome itself behaved.

**3. Minimum viable flag set + environment for the isolate.** `--headless --no-sandbox
--disable-gpu --disable-dev-shm-usage --disable-quic --user-data-dir=<writable-tmp-dir>
--disable-crash-reporter --dump-dom <url>`, plus `HOME` and `XDG_RUNTIME_DIR` explicitly set to
that same writable tmp dir (both are needed — without them, crashpad fails outright with
`--database is required`, and dbus/dconf produce large amounts of harmless-but-noisy stderr).
`--virtual-time-budget` + `--run-all-compositor-stages-before-draw` were tried first (common
recipe for "wait for JS to settle") and were flaky here (occasionally 20-45s+ even for
`about:blank`) — plain `--dump-dom`, which waits for the `load` event, was fast and deterministic
and is what the real fetcher should use, with a hard outer timeout as the safety net regardless.

**4. Allowlist shape for the real fetcher: first-party domain only, by default.** Check 4 showed
asset subdomains (CDN/image hosts) are not needed for usable text — only add them if a future
requirement needs images/rendered layout, not for text extraction. Keep the allowlist minimal
(smaller attack surface, matches the fail-closed design intent).

**5. Resource/latency budget for the real spec:** the current default cap (`SandboxCaps` 512MB
memory / 60s timeout) is already sufficient per-fetch — no change needed there. Budget ~2s
wall-clock per fetch (cold launch + render + extract) as the realistic ceiling for a single-domain
page under this design; that is the number a fetch-timeout default should be sized against, not
the sub-second httpx figure it replaces.
