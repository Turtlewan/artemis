#!/usr/bin/env python3
"""In-isolate render script: launch headless Chromium, dump rendered DOM, extract visible text.

Runs INSIDE the WSL2 isolate as the de-privileged capability process (uid 4000, no network
namespace access beyond the SNI-allowlist proxy). Uses Chromium's `--headless --dump-dom`
to get post-JS-render HTML (no CDP/websocket dependency, no pip packages needed — stdlib only).

IMPORTANT: use `chrome-headless-shell`, not full `chrome`, as the binary (see README "Load-bearing
findings"). Full chrome makes background TLS connections to Google infrastructure domains
(redirector.gvt1.com, accounts.google.com, android.clients.google.com) that the SNI-allowlist
proxy correctly rejects, but chrome retries them repeatedly and that churn was observed to blow
past a 60s budget even for a single-domain fetch. chrome-headless-shell is a purpose-built
automation binary that doesn't have this background-service baggage at all.

Usage: python3 render.py <url> [chromium-binary]
Prints extracted visible text to stdout. Exit 0 on success, non-zero + stderr diagnostic on
failure (timeout, chromium crash, DNS/egress block, etc).
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from html.parser import HTMLParser


class _TextExtractor(HTMLParser):
    """Minimal visible-text extractor: strips tags/script/style, collapses whitespace."""

    def __init__(self) -> None:
        super().__init__()
        self._skip_depth = 0
        self._chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("script", "style", "noscript", "template"):
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style", "noscript", "template") and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            stripped = data.strip()
            if stripped:
                self._chunks.append(stripped)

    def text(self) -> str:
        joined = " ".join(self._chunks)
        return re.sub(r"\s+", " ", joined).strip()


def extract_text(html: str) -> str:
    parser = _TextExtractor()
    parser.feed(html)
    return parser.text()


def render(url: str, chromium_bin: str, timeout_s: int = 60) -> str:
    profile_dir = tempfile.mkdtemp(prefix="chrome-profile-")

    # USERNS SPIKE: by default DROP --no-sandbox so Chrome must engage its own
    # (unprivileged user-namespace) sandbox. Chrome refuses to start without a working
    # sandbox, so a successful render here PROVES the userns sandbox engaged inside the
    # isolate. Set CHROME_NO_SANDBOX=1 to restore the old --no-sandbox behaviour for A/B.
    sandbox_flags: list[str] = (
        ["--no-sandbox", "--disable-setuid-sandbox"]
        if os.environ.get("CHROME_NO_SANDBOX") == "1"
        else []
    )
    cmd = [
        chromium_bin,
        "--headless",
        *sandbox_flags,
        "--disable-gpu",
        "--disable-dev-shm-usage",  # tmpfs /dev/shm may be tiny in the isolate; use /tmp instead
        "--disable-quic",  # force TCP so the SNI-allowlist proxy sees all traffic (no UDP/443 bypass)
        f"--user-data-dir={profile_dir}",  # crashpad needs an explicit, writable database dir under uid 4000
        "--disable-crash-reporter",
        # Belt-and-braces: chrome-headless-shell doesn't open background Google-service connections
        # in testing, but this is Puppeteer's well-known CI/headless flag set, kept as defense in
        # depth in case a future build regains any of that behavior.
        "--no-first-run",
        "--disable-background-networking",
        "--disable-background-timer-throttling",
        "--disable-backgrounding-occluded-windows",
        "--disable-renderer-backgrounding",
        "--disable-client-side-phishing-detection",
        "--disable-component-extensions-with-background-pages",
        "--disable-component-update",
        "--disable-domain-reliability",
        "--disable-hang-monitor",
        "--disable-ipc-flooding-protection",
        "--disable-sync",
        "--disable-default-apps",
        "--disable-extensions",
        "--disable-features=Translate,BackForwardCache,MediaRouter,OptimizationHints,AutofillServerCommunication",
        "--metrics-recording-only",
        "--enable-automation",
        "--password-store=basic",
        "--use-mock-keychain",
        # NOTE: --virtual-time-budget + --run-all-compositor-stages-before-draw was tried first
        # but is flaky here (observed 20-45s+ wall-clock for a trivial about:blank, sometimes
        # exceeding a 45s timeout) — a known Chromium quirk, not reliable. Plain --dump-dom waits
        # for the 'load' event instead, which is deterministic and was reliably fast in testing.
        "--dump-dom",
        url,
    ]
    # HOME inherited from the isolate's root shell (/root) is not writable by uid 4000 —
    # crashpad/chrome fall back to $HOME for default paths and fail obscurely without it.
    # XDG_RUNTIME_DIR unset -> chrome retries dbus/dconf against /run/user/0 (not writable by
    # uid 4000) repeatedly; pointing it at a writable dir cuts that retry noise.
    env = dict(os.environ)
    env["HOME"] = profile_dir
    env["XDG_RUNTIME_DIR"] = profile_dir
    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=timeout_s,
        env=env,
    )
    if proc.returncode != 0:
        sys.stderr.write(f"chromium exit {proc.returncode}\nSTDERR:\n{proc.stderr[-4000:]}\n")
        raise SystemExit(proc.returncode or 1)
    return proc.stdout


def main() -> int:
    if len(sys.argv) < 2:
        sys.stderr.write("usage: render.py <url> [chromium-binary]\n")
        return 2
    url = sys.argv[1]
    chromium_bin = sys.argv[2] if len(sys.argv) > 2 else "chromium"
    try:
        html = render(url, chromium_bin)
    except subprocess.TimeoutExpired as exc:
        partial_err = exc.stderr or b""
        if isinstance(partial_err, bytes):
            partial_err = partial_err.decode(errors="replace")
        sys.stderr.write(
            f"timeout after render attempt on {url}\nPARTIAL STDERR:\n{partial_err[-3000:]}\n"
        )
        return 124
    text = extract_text(html)
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
