#!/usr/bin/env python3
"""Runs inside the isolate. Attempts to reach localhost + a LAN address to prove the
netns has no route to them except the SNI-allowlist proxy. Prints PROBE_RESULT lines."""

from __future__ import annotations

import subprocess
import sys


def probe(name: str, url: str) -> None:
    try:
        result = subprocess.run(
            ["curl", "-m", "3", "-sS", "-o", "/dev/null", "-w", "%{http_code}", url],
            capture_output=True,
            text=True,
            timeout=5,
        )
        status = (
            "REACHED"
            if result.returncode == 0
            else f"BLOCKED (curl exit {result.returncode}: {result.stderr.strip()[:200]})"
        )
    except subprocess.TimeoutExpired:
        status = "BLOCKED (timeout)"
    print(f"PROBE_RESULT {name} {url} {status}")


def main() -> int:
    targets = sys.argv[1:] or ["http://127.0.0.1:8030", "http://192.168.1.1:8030"]
    for i, url in enumerate(targets):
        probe(f"target{i}", url)
    return 0


if __name__ == "__main__":
    sys.exit(main())
