from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import tempfile
from typing import Literal

import pytest

from artemis.capabilities.fetch_sandbox import FetchResult, FetchSandbox
from artemis.reachout.js_fetch import JsFetcher

_JS_SMOKE = shutil.which("wsl.exe") is not None and os.environ.get("ARTEMIS_JS_SMOKE") == "1"
_DEFAULT_CHROMIUM_BIN = "/opt/chromium_headless_shell/chrome-headless-shell"


@dataclass(frozen=True)
class SandboxCall:
    capability_dir: Path
    entrypoint: str
    argv: list[str]
    egress_domains: list[str]
    timeout_s: float
    secrets: dict[str, str] | None
    caps_profile: Literal["default", "render"]
    output_limit: int


class StubSandbox(FetchSandbox):
    def __init__(self, result: FetchResult | Exception) -> None:
        self._result = result
        self.calls: list[SandboxCall] = []

    async def run(
        self,
        capability_dir: Path,
        *,
        entrypoint: str,
        argv: list[str],
        egress_domains: list[str],
        timeout_s: float = 60.0,
        secrets: dict[str, str] | None = None,
        caps_profile: Literal["default", "render"] = "default",
        output_limit: int = 4000,
    ) -> FetchResult:
        self.calls.append(
            SandboxCall(
                capability_dir=capability_dir,
                entrypoint=entrypoint,
                argv=argv,
                egress_domains=egress_domains,
                timeout_s=timeout_s,
                secrets=secrets,
                caps_profile=caps_profile,
                output_limit=output_limit,
            )
        )
        if isinstance(self._result, Exception):
            raise self._result
        return self._result


@pytest.mark.asyncio
async def test_fetch_forwards_exact_host_and_truncates_output() -> None:
    url = "https://en.wikipedia.org/wiki/X"
    sandbox = StubSandbox(FetchResult(output="Z" * 50_000, exit_code=0, truncated=True))

    result = await JsFetcher(sandbox=sandbox).fetch(url, max_chars=20_000)

    assert result.url == url
    assert result.domain == "en.wikipedia.org"
    assert result.text == "Z" * 20_000
    assert len(sandbox.calls) == 1
    call = sandbox.calls[0]
    assert call.entrypoint == "render.py"
    assert call.argv == [url, _DEFAULT_CHROMIUM_BIN]
    assert call.egress_domains == ["en.wikipedia.org"]
    assert call.output_limit == 20_000
    assert call.caps_profile == "render"


@pytest.mark.asyncio
async def test_fetch_degrades_on_nonzero_exit() -> None:
    sandbox = StubSandbox(FetchResult(output="blocked", exit_code=1, truncated=False))

    result = await JsFetcher(sandbox=sandbox).fetch("https://example.com/")

    assert result.text == ""
    assert result.domain == "example.com"


@pytest.mark.asyncio
async def test_fetch_degrades_on_missing_wsl() -> None:
    sandbox = StubSandbox(FileNotFoundError("wsl.exe"))

    result = await JsFetcher(sandbox=sandbox).fetch("https://example.com/")

    assert result.text == ""
    assert result.domain == "example.com"


@pytest.mark.asyncio
async def test_fetch_degrades_on_timeout() -> None:
    sandbox = StubSandbox(TimeoutError("slow"))

    result = await JsFetcher(sandbox=sandbox).fetch("https://example.com/")

    assert result.text == ""
    assert result.domain == "example.com"


@pytest.mark.asyncio
async def test_fetch_bad_url_returns_empty_without_sandbox_call() -> None:
    sandbox = StubSandbox(FetchResult(output="unexpected", exit_code=0, truncated=False))

    result = await JsFetcher(sandbox=sandbox).fetch("not a url")

    assert result.url == "not a url"
    assert result.domain == ""
    assert result.text == ""
    assert sandbox.calls == []


@pytest.mark.asyncio
async def test_aclose_is_noop() -> None:
    await JsFetcher(
        sandbox=StubSandbox(FetchResult(output="", exit_code=0, truncated=False))
    ).aclose()


@pytest.mark.skipif(
    not _JS_SMOKE,
    reason="WSL2/chrome-headless-shell not provisioned (set ARTEMIS_JS_SMOKE=1)",
)
@pytest.mark.asyncio
async def test_live_js_fetch_reads_blocked_page() -> None:
    result = await JsFetcher().fetch("https://en.wikipedia.org/wiki/Python_(programming_language)")

    assert len(result.text) > 4000
    assert "python" in result.text.lower()


@pytest.mark.skipif(
    not _JS_SMOKE,
    reason="WSL2/chrome-headless-shell not provisioned (set ARTEMIS_JS_SMOKE=1)",
)
@pytest.mark.asyncio
async def test_live_js_fetch_egress_negative() -> None:
    url = "https://en.wikipedia.org/wiki/Python_(programming_language)"
    with tempfile.TemporaryDirectory() as tmp:
        capability_dir = Path(tmp)
        source = Path(__file__).parents[2] / "src" / "artemis" / "reachout" / "render_script.py"
        shutil.copyfile(source, capability_dir / "render.py")
        result = await FetchSandbox().run(
            capability_dir,
            entrypoint="render.py",
            argv=[url, _DEFAULT_CHROMIUM_BIN],
            egress_domains=["example.com"],
            timeout_s=45.0,
            output_limit=20_000,
        )

    assert result.exit_code != 0 or result.output.strip() == ""
