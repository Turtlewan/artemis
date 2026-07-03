from __future__ import annotations

import sys
import time

import pytest

import artemis.model.cli_support as cli_support


@pytest.mark.asyncio
async def test_run_cli_timeout_kills_and_raises() -> None:
    start = time.monotonic()

    with pytest.raises(TimeoutError):
        await cli_support.run_cli(
            [sys.executable, "-c", "import time; time.sleep(30)"],
            stdin=b"",
            timeout=0.5,
        )

    # The hang is cut at the timeout, not the child's sleep — well under the 30s sleep.
    assert time.monotonic() - start < 10


@pytest.mark.asyncio
async def test_run_cli_completes_within_timeout() -> None:
    returncode, stdout, _stderr = await cli_support.run_cli(
        [sys.executable, "-c", "print('ok')"],
        stdin=b"",
        timeout=30.0,
    )

    assert returncode == 0
    assert stdout.strip() == b"ok"


@pytest.mark.asyncio
async def test_run_cli_no_timeout_still_works() -> None:
    returncode, stdout, _stderr = await cli_support.run_cli(
        [sys.executable, "-c", "import sys; sys.stdout.write(sys.stdin.read())"],
        stdin=b"echo",
    )

    assert returncode == 0
    assert stdout == b"echo"
