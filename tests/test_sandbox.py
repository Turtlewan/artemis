from pathlib import Path

import pytest

from artemis.capabilities.sandbox import SandboxRunner, SubprocessSandbox


def test_subprocess_sandbox_implements_runner() -> None:
    assert isinstance(SubprocessSandbox(), SandboxRunner)


@pytest.mark.asyncio
async def test_subprocess_sandbox_passes_green_tests(tmp_path: Path) -> None:
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_ok.py").write_text(
        "def test_ok() -> None:\n    assert True\n",
        encoding="utf-8",
    )

    result = await SubprocessSandbox().run_tests(tmp_path)

    assert result.passed is True


@pytest.mark.asyncio
async def test_subprocess_sandbox_fails_red_tests(tmp_path: Path) -> None:
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_fail.py").write_text(
        "def test_fail() -> None:\n    assert False\n",
        encoding="utf-8",
    )

    result = await SubprocessSandbox().run_tests(tmp_path)

    assert result.passed is False


@pytest.mark.asyncio
async def test_subprocess_sandbox_requires_tests(tmp_path: Path) -> None:
    result = await SubprocessSandbox().run_tests(tmp_path)

    assert result.passed is False
    assert result.output.startswith("no tests")
