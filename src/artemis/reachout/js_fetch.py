"""JS-rendering fallback fetcher for bot-blocked pages.

``JsFetcher`` renders pages inside the hardened WSL2 ``FetchSandbox`` using the stdlib-only
``render_script.py``. Returned text is untrusted page content; callers must keep using the
web tool's reader quarantine before model synthesis.
"""

from __future__ import annotations

import logging
from pathlib import Path
import shutil
import tempfile
import urllib.parse

from artemis.capabilities.fetch_sandbox import FetchSandbox
from artemis.reachout.fetch import FetchedContent, Fetcher

_log = logging.getLogger(__name__)

DEFAULT_CHROMIUM_BIN = "/opt/chromium_headless_shell/chrome-headless-shell"


class JsFetcher(Fetcher):
    """Render JavaScript pages in the fetch isolate and degrade to empty text on failure."""

    def __init__(
        self,
        *,
        sandbox: FetchSandbox | None = None,
        chromium_bin: str = DEFAULT_CHROMIUM_BIN,
        timeout_s: float = 45.0,
    ) -> None:
        self._sandbox = sandbox if sandbox is not None else FetchSandbox()
        self._chromium_bin = chromium_bin
        self._timeout_s = timeout_s

    async def fetch(self, url: str, *, max_chars: int = 20000) -> FetchedContent:
        """Render ``url`` and return extracted text, or empty text on sandbox/chrome failure."""
        try:
            host = urllib.parse.urlsplit(url).hostname or ""
        except Exception:
            host = ""
        if not host:
            return FetchedContent(url=url, domain="", text="")

        try:
            with tempfile.TemporaryDirectory() as tmp:
                capability_dir = Path(tmp)
                render_script = Path(__file__).parent / "render_script.py"
                shutil.copyfile(render_script, capability_dir / "render.py")
                result = await self._sandbox.run(
                    capability_dir,
                    entrypoint="render.py",
                    argv=[url, self._chromium_bin],
                    egress_domains=[host],
                    timeout_s=self._timeout_s,
                    caps_profile="render",
                    output_limit=max_chars,
                )
        except Exception as exc:
            _log.warning("js_fetch_degraded reason=%s host=%s", type(exc).__name__, host)
            return FetchedContent(url=url, domain=host, text="")

        if result.exit_code != 0:
            _log.warning("js_fetch_degraded reason=%s host=%s", "ExitCode", host)
            return FetchedContent(url=url, domain=host, text="")

        return FetchedContent(url=url, domain=host, text=result.output[:max_chars].strip())

    async def aclose(self) -> None:
        """No-op: the sandbox has no persistent client to close."""
