#!/usr/bin/env python3
"""Host-side runner for the throwaway WSL2 isolation PoC."""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
import textwrap
import time
import uuid
from dataclasses import dataclass
from pathlib import Path


HELLO = """\
print("hello")
"""

NET_BLOCKED = """\
import urllib.request

urllib.request.urlopen("https://example.com", timeout=5)
"""

NET_ALLOWED = """\
import urllib.request

with urllib.request.urlopen("https://example.com", timeout=5) as response:
    print(f"example.com OK {response.status}")

try:
    urllib.request.urlopen("https://www.bing.com", timeout=5)
except Exception as exc:
    print(f"bing.com BLOCKED {type(exc).__name__}")
else:
    raise SystemExit("bing.com unexpectedly succeeded")
"""

HOG = """\
blob = b"x" * (2 * 1024**3)
while True:
    _ = blob[0]
"""

DATAPATH = """\
import json
from pathlib import Path

Path("out.txt").write_text("host must not read this file\\n", encoding="utf-8")
print(json.dumps({"result": "datapath-ok"}))
"""


@dataclass(frozen=True)
class Scenario:
    source: str
    allowlist: str


SCENARIOS = {
    "hello": Scenario(HELLO, ""),
    "net-blocked": Scenario(NET_BLOCKED, ""),
    "net-allowed": Scenario(NET_ALLOWED, "example.com"),
    "hog": Scenario(HOG, ""),
    "datapath": Scenario(DATAPATH, ""),
}


def windows_path_to_wsl(path: Path) -> str:
    resolved = path.resolve()
    drive = resolved.drive.rstrip(":").lower()
    if not drive:
        raise ValueError(f"cannot convert path without drive to WSL path: {resolved}")
    parts = [part for part in resolved.parts[1:]]
    return "/mnt/" + drive + "/" + "/".join(parts)


def run_wsl(args: list[str], timeout: int | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["wsl.exe", "-d", "Ubuntu", "--", *args],
        check=False,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def run_scenario(name: str) -> bool:
    scenario = SCENARIOS[name]
    root = Path(__file__).resolve().parents[2]
    isolate = windows_path_to_wsl(root / "poc" / "wsl2_sandbox" / "isolate.sh")
    run_id = f"{name}-{uuid.uuid4().hex}"

    with tempfile.TemporaryDirectory(prefix="artemis-wsl2-poc-") as tmpdir:
        capfile = Path(tmpdir) / f"{name}.py"
        capfile.write_text(textwrap.dedent(scenario.source), encoding="utf-8")
        capfile_wsl = windows_path_to_wsl(capfile)

        started = time.monotonic()
        result = run_wsl(
            ["bash", isolate, capfile_wsl, scenario.allowlist, run_id],
            timeout=45,
        )
        elapsed = time.monotonic() - started

    combined = result.stdout + result.stderr
    print(f"scenario: {name}")
    print(f"exit code: {result.returncode}")
    print(f"elapsed seconds: {elapsed:.2f}")
    print("captured output:")
    print(combined)

    passed = expected_passed(name, result.returncode, combined, elapsed)
    print("PASS" if passed else "FAIL")
    return passed


def expected_passed(name: str, returncode: int, output: str, elapsed: float) -> bool:
    if name == "hello":
        return returncode == 0 and "hello" in output
    if name == "net-blocked":
        return returncode != 0
    if name == "net-allowed":
        return (
            returncode == 0
            and "example.com OK" in output
            and "bing.com BLOCKED" in output
            and "unexpectedly succeeded" not in output
        )
    if name == "hog":
        return returncode != 0 and elapsed < 35
    if name == "datapath":
        cleanup = run_wsl(
            ["bash", "-lc", "ls /tmp/artemis-* 2>/dev/null | wc -l"],
            timeout=10,
        )
        cleanup_count = cleanup.stdout.strip()
        print(f"cleanup count: {cleanup_count}")
        return (
            returncode == 0
            and output.strip() == '{"result": "datapath-ok"}'
            and cleanup.returncode == 0
            and cleanup_count == "0"
        )
    raise AssertionError(f"unknown scenario: {name}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenario", choices=sorted(SCENARIOS))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    return 0 if run_scenario(args.scenario) else 1


if __name__ == "__main__":
    sys.exit(main())
