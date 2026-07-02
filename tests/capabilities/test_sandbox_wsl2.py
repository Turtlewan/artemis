from __future__ import annotations

import asyncio
import base64
import json
import shlex
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest

from artemis.capabilities.sandbox import SubprocessSandbox
from artemis.capabilities.fetch_sandbox import FetchSandbox
from artemis.capabilities.sandbox_wsl2 import (
    _ISOLATE_SCRIPT,
    SandboxCaps,
    Wsl2SandboxRunner,
    _parse_isolate_output,
    _policy_for,
    _secrets_b64,
    _to_wsl_path,
    _validate_secret_name,
    default_sandbox,
    run_isolated,
)


class _FakeProcess:
    def __init__(self, stdout: bytes = b"11\nhello world", stderr: bytes = b"") -> None:
        self.returncode = 0
        self.stdout = stdout
        self.stderr = stderr
        self.killed = False
        self.stdin_payload: bytes | None = None

    async def communicate(self, input: bytes | None = None) -> tuple[bytes, bytes]:
        self.stdin_payload = input
        return self.stdout, self.stderr

    def kill(self) -> None:
        self.killed = True


def test_sandbox_caps_defaults() -> None:
    caps = SandboxCaps()

    assert caps.memory_mb == 512
    assert caps.cpu_pct == 100
    assert caps.pids_max == 128
    assert caps.timeout_s == 60.0


def test_policy_absent_defaults_to_no_network_and_default_caps(tmp_path: Path) -> None:
    policy = _policy_for(tmp_path)

    assert policy.egress_domains == []
    assert policy.caps == SandboxCaps()


def test_policy_present_parses_egress_and_caps(tmp_path: Path) -> None:
    (tmp_path / "sandbox_policy.json").write_text(
        (
            '{"egress_domains":["api.example.com"],"memory_mb":256,'
            '"cpu_pct":50,"pids_max":64,"timeout_s":12.5}'
        ),
        encoding="utf-8",
    )

    policy = _policy_for(tmp_path)

    assert policy.egress_domains == ["api.example.com"]
    assert policy.caps == SandboxCaps(
        memory_mb=256,
        cpu_pct=50,
        pids_max=64,
        timeout_s=12.5,
    )


@pytest.mark.asyncio
async def test_run_isolated_converts_wslpath_and_exports_caps(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    created: list[tuple[str, ...]] = []
    fake_process = _FakeProcess(stdout=b"4001\nabcd")
    monkeypatch.delenv("WSLENV", raising=False)

    async def fake_create_subprocess_exec(*cmd: str, **kwargs: object) -> _FakeProcess:
        created.append(cmd)
        env = kwargs["env"]
        assert isinstance(env, dict)
        assert env["MEM_MAX"] == str(256 * 1024 * 1024)
        assert env["CPU_MAX"] == "50000 100000"
        assert env["PIDS_MAX"] == "64"
        assert env["ULIMIT_T"] == "13"
        assert env["WSLENV"] == "MEM_MAX:CPU_MAX:PIDS_MAX:ULIMIT_T:ULIMIT_V"
        return fake_process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    code, output, truncated = await run_isolated(
        tmp_path,
        egress_domains=["api.example.com"],
        caps=SandboxCaps(memory_mb=256, cpu_pct=50, pids_max=64, timeout_s=12.5),
        command=["python3", "-m", "pytest"],
        timeout_s=20,
    )

    # _to_wsl_path is pure Python now (wslpath mangles backslashes over the interop layer)
    expected_wsl_path = _to_wsl_path(tmp_path)
    assert created
    assert created[0][:7] == ("wsl.exe", "-u", "root", "--", "bash", "-s", "--")
    assert created[0][7] == expected_wsl_path
    assert created[0][8] == "api.example.com"
    assert created[0][10:] == ("python3", "-m", "pytest")
    assert fake_process.stdin_payload is not None
    assert b"set -euo pipefail" in fake_process.stdin_payload
    payload = fake_process.stdin_payload.decode()
    assert "ARTEMIS_SECRETS_B64=''" in payload
    marker = 'eval "$(printf \'%s\' "$ARTEMIS_SECRETS_B64" | base64 -d'
    assert payload.count(marker) == 1
    assert payload.index("unset ARTEMIS_SECRETS_B64") < payload.index(
        'OUT=$(ip netns exec "$NS" unshare'
    )
    assert code == 0
    assert output == "abcd"
    assert truncated is True


@pytest.mark.parametrize(
    "bad_name",
    [
        "1FOO",
        "FOO-BAR",
        "FOO;ls",
        "PATH",
        "MEM_MAX",
        "LD_AUDIT",
        "GLIBC_TUNABLES",
        "_",
        "",
        "FOO BAR",
    ],
)
def test_validate_secret_name_rejects_unsafe_or_reserved(bad_name: str) -> None:
    with pytest.raises(ValueError):
        _validate_secret_name(bad_name)


@pytest.mark.parametrize("good_name", ["GITHUB_TOKEN", "_PRIVATE", "API_KEY2"])
def test_validate_secret_name_accepts_safe_names(good_name: str) -> None:
    _validate_secret_name(good_name)


@pytest.mark.asyncio
async def test_invalid_secret_name_fails_before_subprocess(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    created: list[tuple[str, ...]] = []

    async def fake_create_subprocess_exec(*cmd: str, **kwargs: object) -> _FakeProcess:
        created.append(cmd)
        return _FakeProcess()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    with pytest.raises(ValueError):
        await run_isolated(
            tmp_path,
            egress_domains=[],
            caps=SandboxCaps(),
            command=["python3", "-c", "print('nope')"],
            timeout_s=20,
            secrets={"PATH": "evil"},
        )

    assert created == []


@pytest.mark.asyncio
async def test_run_isolated_keeps_secrets_out_of_argv_env_and_plaintext_stdin(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    created: list[tuple[str, ...]] = []
    captured_env: dict[str, str] = {}
    fake_process = _FakeProcess()
    secret_value = "sekret-value-123"
    secrets = {"GITHUB_TOKEN": secret_value}
    blob = base64.b64encode(json.dumps(secrets, separators=(",", ":")).encode()).decode()
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("WSLENV", raising=False)

    async def fake_create_subprocess_exec(*cmd: str, **kwargs: object) -> _FakeProcess:
        created.append(cmd)
        env = kwargs["env"]
        assert isinstance(env, dict)
        captured_env.update(env)
        return fake_process

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)

    await run_isolated(
        tmp_path,
        egress_domains=[],
        caps=SandboxCaps(),
        command=["python3", "-c", "print('ok')"],
        timeout_s=20,
        secrets=secrets,
    )

    assert created
    assert secret_value not in " ".join(created[0])
    env_values = "\n".join(captured_env.values())
    assert secret_value not in env_values
    assert "GITHUB_TOKEN" not in env_values
    assert captured_env["WSLENV"] == "MEM_MAX:CPU_MAX:PIDS_MAX:ULIMIT_T:ULIMIT_V"
    assert fake_process.stdin_payload is not None
    payload = fake_process.stdin_payload.decode()
    assert secret_value not in payload
    assert f"export GITHUB_TOKEN={secret_value}" not in payload
    assert blob in payload
    assert 'eval "$(printf \'%s\' "$ARTEMIS_SECRETS_B64" | base64 -d' in payload


def test_secret_value_never_plaintext_in_templated_script() -> None:
    secret_value = "sekret-value-123"
    secrets = {"GITHUB_TOKEN": secret_value}
    blob = _secrets_b64(secrets)
    script = _ISOLATE_SCRIPT.replace("__ARTEMIS_SECRETS_B64__", blob)

    assert blob in script
    assert secret_value not in script
    assert f"export GITHUB_TOKEN={secret_value}" not in script


def test_decode_export_block_suppresses_decode_errors_and_is_outer_shell() -> None:
    marker = 'eval "$(printf \'%s\' "$ARTEMIS_SECRETS_B64" | base64 -d'
    assert _ISOLATE_SCRIPT.count(marker) == 1
    block_start = _ISOLATE_SCRIPT.index("ARTEMIS_SECRETS_B64='__ARTEMIS_SECRETS_B64__'")
    out_start = _ISOLATE_SCRIPT.index('OUT=$(ip netns exec "$NS" unshare')
    block = _ISOLATE_SCRIPT[block_start:out_start]

    assert "| base64 -d 2>/dev/null | python3 -c" in block
    assert "' 2>/dev/null)\" || abort secrets-decode" in block
    assert "unset ARTEMIS_SECRETS_B64" in block
    assert "ARTEMIS_SECRETS_EXPORTS" not in _ISOLATE_SCRIPT
    assert block_start < out_start


def test_secret_export_quoting_round_trips_hostile_values() -> None:
    value = "space ' $VAR `tick`\nline"
    blob = _secrets_b64({"HOSTILE_VALUE": value})
    decoded = json.loads(base64.b64decode(blob).decode())
    export_line = "export HOSTILE_VALUE=" + shlex.quote(decoded["HOSTILE_VALUE"])

    assert shlex.split(export_line) == ["export", f"HOSTILE_VALUE={value}"]


def test_default_sandbox_falls_back_when_probe_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(cmd: object, *args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(["wsl.exe"], 1, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert isinstance(default_sandbox(), SubprocessSandbox)


def test_hardened_flag_contract() -> None:
    assert Wsl2SandboxRunner().hardened is True
    assert getattr(SubprocessSandbox(), "hardened", False) is False


def test_reliable_truncation_parsing() -> None:
    exact_output = "x" * 4000
    long_output = "x" * 4000

    output, truncated = _parse_isolate_output(f"4000\n{exact_output}".encode(), b"")
    assert output == exact_output
    assert truncated is False

    output, truncated = _parse_isolate_output(f"4001\n{long_output}".encode(), b"")
    assert output == long_output
    assert truncated is True


@pytest.fixture
def live_wsl() -> Iterator[None]:
    try:
        completed = subprocess.run(
            [
                "wsl.exe",
                "-u",
                "root",
                "--",
                "bash",
                "-c",
                (
                    "command -v ip iptables nginx dnsmasq setpriv unshare >/dev/null && "
                    "nginx -V 2>&1 | grep -q ssl_preread && "
                    "id -u artemis-cap >/dev/null && "
                    "test -w /sys/fs/cgroup/cgroup.procs"
                ),
            ],
            check=False,
            capture_output=True,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.SubprocessError, OSError) as exc:
        pytest.skip(f"WSL2 sandbox not provisioned: {exc}")

    if completed.returncode != 0:
        pytest.skip("WSL2 sandbox not provisioned")
    yield


@pytest.mark.asyncio
async def test_live_no_network_default_blocks_egress(live_wsl: None, tmp_path: Path) -> None:
    code, output, _truncated = await run_isolated(
        tmp_path,
        egress_domains=[],
        caps=SandboxCaps(timeout_s=20.0),
        command=[
            "python3",
            "-c",
            (
                "import urllib.request; "
                "urllib.request.urlopen('https://example.com', timeout=5).read()"
            ),
        ],
        timeout_s=30.0,
    )

    assert code != 0
    assert output


@pytest.mark.asyncio
async def test_live_transparent_proxy_allows_one(live_wsl: None, tmp_path: Path) -> None:
    code, output, _truncated = await run_isolated(
        tmp_path,
        egress_domains=["example.com"],
        caps=SandboxCaps(timeout_s=30.0),
        command=[
            "python3",
            "-c",
            (
                "import urllib.request; "
                "resp=urllib.request.urlopen('https://example.com', timeout=10); "
                "print(resp.status)"
            ),
        ],
        timeout_s=40.0,
    )

    assert code == 0, output
    assert "200" in output


@pytest.mark.asyncio
async def test_live_transparent_proxy_blocks_another(live_wsl: None, tmp_path: Path) -> None:
    code, output, _truncated = await run_isolated(
        tmp_path,
        egress_domains=["example.com"],
        caps=SandboxCaps(timeout_s=20.0),
        command=[
            "python3",
            "-c",
            (
                "import urllib.request; "
                "urllib.request.urlopen('https://www.python.org', timeout=5).read()"
            ),
        ],
        timeout_s=30.0,
    )

    assert code != 0
    assert output


@pytest.mark.asyncio
async def test_live_cgroup_memory_cap_kills_overallocation(live_wsl: None, tmp_path: Path) -> None:
    code, _output, _truncated = await run_isolated(
        tmp_path,
        egress_domains=[],
        caps=SandboxCaps(memory_mb=256, timeout_s=20.0),
        command=["python3", "-c", "x = bytearray(1024 * 1024 * 1024); print(len(x))"],
        timeout_s=30.0,
    )

    assert code != 0


@pytest.mark.asyncio
async def test_live_tmpfs_cleanup(live_wsl: None, tmp_path: Path) -> None:
    await run_isolated(
        tmp_path,
        egress_domains=[],
        caps=SandboxCaps(timeout_s=20.0),
        command=["python3", "-c", "print('ok')"],
        timeout_s=30.0,
    )

    completed = subprocess.run(
        [
            "wsl.exe",
            "-u",
            "root",
            "--",
            "bash",
            "-lc",
            (
                "find /tmp -maxdepth 1 -name 'artemis-*' -print -quit; "
                "find /sys/fs/cgroup -maxdepth 1 -name 'artemis-*' -print -quit"
            ),
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
    )

    assert completed.stdout.strip() == ""


@pytest.mark.asyncio
async def test_live_secret_reaches_capability_process_only(live_wsl: None, tmp_path: Path) -> None:
    sentinel = "artemis-live-secret-sentinel"
    (tmp_path / "entry.py").write_text(
        "import os\n"
        "print('match' if os.environ.get('ARTEMIS_TEST_SECRET') "
        f"== {sentinel!r} else 'nomatch')\n",
        encoding="utf-8",
    )

    result = await FetchSandbox().run(
        tmp_path,
        entrypoint="entry.py",
        argv=[],
        egress_domains=[],
        timeout_s=30.0,
        secrets={"ARTEMIS_TEST_SECRET": sentinel},
    )

    assert result.exit_code == 0, result.output
    assert result.output.strip() == "match"
    assert sentinel not in result.output
