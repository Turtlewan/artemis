#!/usr/bin/env python3
"""In-isolate JS render script for the reach-out web fetcher.

This script runs under the WSL2 fetch isolate's system Python, so it is stdlib-only and
must not import from ``artemis``. It launches ``chrome-headless-shell --dump-dom``, then
extracts visible text from the rendered HTML.
"""

from __future__ import annotations

from html.parser import HTMLParser
import os
import re
import subprocess
import sys
import tempfile

DEFAULT_CHROMIUM_BIN = "/opt/chromium_headless_shell/chrome-headless-shell"
_SKIP_TAGS = {"script", "style", "noscript", "template"}


class _TextExtractor(HTMLParser):
    """Minimal visible-text extractor: strips tags and collapses whitespace."""

    def __init__(self) -> None:
        super().__init__()
        self._skip_depth = 0
        self._chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag in _SKIP_TAGS:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS and self._skip_depth > 0:
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
    """Return visible text from rendered HTML, skipping script/style-like containers."""
    parser = _TextExtractor()
    parser.feed(html)
    return parser.text()


def render(url: str, chromium_bin: str, timeout_s: float = 60.0) -> str:
    """Render ``url`` with chrome-headless-shell and return the dumped DOM HTML."""
    with tempfile.TemporaryDirectory(prefix="chrome-profile-") as profile_dir:
        cmd = [
            chromium_bin,
            "--headless",
            "--disable-gpu",
            "--disable-dev-shm-usage",
            "--disable-quic",
            f"--user-data-dir={profile_dir}",
            "--disable-crash-reporter",
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
            "--dump-dom",
            url,
        ]
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
        raise RuntimeError(f"chromium exit {proc.returncode}")
    return proc.stdout


def main() -> int:
    """Render ``argv[1]`` and print extracted text; return non-zero on chrome failure."""
    if len(sys.argv) < 2:
        sys.stderr.write("usage: render.py <url> [chromium-binary]\n")
        return 2

    url = sys.argv[1]
    chromium_bin = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_CHROMIUM_BIN
    try:
        html = render(url, chromium_bin)
    except subprocess.TimeoutExpired:
        sys.stderr.write("chromium timeout\n")
        return 124
    except Exception as exc:
        sys.stderr.write(f"chromium error: {type(exc).__name__}\n")
        return 1

    print(extract_text(html))
    return 0


if __name__ == "__main__":
    sys.exit(main())
