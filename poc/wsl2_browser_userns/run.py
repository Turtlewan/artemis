#!/usr/bin/env python3
"""Host-side runner for the headless-Chromium-in-WSL2-isolate feasibility spike.

Invokes poc/wsl2_browser/isolate.sh (a standalone copy of the sandbox_wsl2.py isolation
mechanism) with a target URL, an egress domain allowlist, and resource caps, then prints
the isolate's output (rendered text, peak memory, stderr tail).

Usage:
    python run.py <url> <comma,separated,allowlist> [--mem-mb N] [--timeout S]

Examples:
    python run.py https://en.wikipedia.org/wiki/Python_(programming_language) en.wikipedia.org
    python run.py https://en.wikipedia.org/wiki/Python_(programming_language) en.wikipedia.org,upload.wikimedia.org
"""

from __future__ import annotations

import argparse
import subprocess
import time
import uuid
from pathlib import Path


def windows_path_to_wsl(path: Path) -> str:
    resolved = path.resolve()
    drive = resolved.drive.rstrip(":").lower()
    if not drive:
        raise ValueError(f"cannot convert path without drive to WSL path: {resolved}")
    return "/mnt/" + drive + "/" + "/".join(resolved.parts[1:])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url")
    parser.add_argument("allowlist", help="comma-separated domains, or '' for no network")
    parser.add_argument("--mem-mb", type=int, default=1536)
    parser.add_argument("--timeout", type=float, default=90.0)
    parser.add_argument(
        "--chromium-bin", default="/opt/chromium_headless_shell/chrome-headless-shell"
    )
    args = parser.parse_args()

    poc_dir = Path(__file__).resolve().parent
    isolate_wsl = windows_path_to_wsl(poc_dir / "isolate.sh")
    capdir_wsl = windows_path_to_wsl(poc_dir / "capability")
    run_id = uuid.uuid4().hex

    env_prefix = (
        f"MEM_MAX={args.mem_mb * 1024 * 1024} "
        f"CPU_MAX='400000 100000' "  # 4 cores — see isolate.sh note on CFS-quota latency amplification
        f"PIDS_MAX=256 "
        f"ULIMIT_T={int(args.timeout)} "
    )

    cmd = [
        "wsl.exe",
        "-u",
        "root",
        "--",
        "bash",
        "-c",
        f"{env_prefix}bash {isolate_wsl} {capdir_wsl} '{args.allowlist}' {run_id} "
        f"python3 render.py '{args.url}' '{args.chromium_bin}'",
    ]

    started = time.monotonic()
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=args.timeout + 30,
    )
    elapsed = time.monotonic() - started

    print(f"=== run_id: {run_id} ===")
    print(f"elapsed_s: {elapsed:.2f}")
    print(f"exit_code: {result.returncode}")
    print("--- stdout ---")
    print(result.stdout)
    print("--- stderr ---")
    print(result.stderr)
    return result.returncode


if __name__ == "__main__":
    raise SystemExit(main())
