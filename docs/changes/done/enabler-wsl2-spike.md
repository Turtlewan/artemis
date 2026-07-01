# Spec: WSL2 isolation spike (enabler #1)

**Identity:** A throwaway PoC proving WSL2 can run untrusted capability code with no-network-by-default + a per-run egress allowlist + resource caps + a text-only data path — the load-bearing unknown before the real `SandboxRunner` is built. Design: [ADR-035](../technical/adr/ADR-035-reach-out-capabilities.md); mechanisms: `docs/findings/enabler-wsl2-isolation-2026-07-01.md`.

> Spike scope: prove the mechanisms in `poc/`, do **not** wire into `src/`. The real `FetchSandbox` + `SandboxRunner` implementation is enabler #2 (separate spec). Deliverable of this spec = the 7 acceptance checks pass on this host + findings recorded in the PoC README.

## Files to change

1. **create** `poc/wsl2_sandbox/isolate.sh` — the in-WSL guest-side isolation wrapper.
2. **create** `poc/wsl2_sandbox/run.py` — the host-side runner (invokes `wsl.exe`, drives scenarios).
3. **create** `poc/wsl2_sandbox/README.md` — provisioning steps + the 7-check results table (fill in as you go).

## Exact changes

### `poc/wsl2_sandbox/isolate.sh` (guest-side)

Bash script run inside the Ubuntu distro. Args: `$1` = capability python file (path inside a tmpfs copy), `$2` = comma-separated egress-allowlist domains (may be empty), `$3` = run-id.

Responsibilities (per the findings):
- **Data path:** `WORK=/tmp/artemis-$3; mkdir -p $WORK; cp "$1" "$WORK/cap.py"`; run with `cwd=$WORK`; `trap 'rm -rf "$WORK"' EXIT`.
- **Egress allowlist (DNS-sinkhole tier):** if `$2` non-empty, write a dnsmasq conf that resolves ONLY the listed domains (`server=/<domain>/8.8.8.8` per domain) and `address=/#/0.0.0.0` for everything else; start `dnsmasq` bound to the netns; point the netns `/etc/resolv.conf` at it. If `$2` empty → no resolver (pure no-network).
- **No-network + caps + exec:** run the capability inside a fresh network namespace with resource caps:
  ```sh
  # no-net namespace (unprivileged — confirmed working on this host):
  # caps via systemd-run --scope (systemd is PID 1 here) OR ulimit fallback:
  systemd-run --scope -q -p MemoryMax=512M -p CPUQuota=100% \
    unshare --net --pid --fork --kill-child \
    bash -c 'ulimit -t 30; cd '"$WORK"'; timeout 35 python3 cap.py'
  ```
  (If `systemd-run --scope` needs privilege in this distro, fall back to `unshare` + `ulimit -t 30 -v 524288` only, and record that in the README.)
- Capture stdout/stderr; **truncate to 4000 chars** (mirror `SubprocessSandbox._truncate`); print as the result.

### `poc/wsl2_sandbox/run.py` (host-side)

```python
# python 3.11+, stdlib only (subprocess). No src/ imports.
# usage: python run.py <scenario>
#   scenarios: hello | net-blocked | net-allowed | hog | datapath
```
- Holds the 5 scenario capability sources as string constants (write each to a temp `.py`, then hand its **WSL path** — `/mnt/c/...` or a copied path — to `isolate.sh`).
  - `hello`: `print("hello")`.
  - `net-blocked`: `import urllib.request; urllib.request.urlopen("https://example.com", timeout=5)` — expected to FAIL (no allowlist passed).
  - `net-allowed`: same fetch to `https://example.com` (allowlist=`example.com`) **and** a fetch to `https://www.bing.com` (NOT listed) — expected: first SUCCEEDS, second FAILS.
  - `hog`: allocate ~2 GB (`b"x"*(2*1024**3)`) and spin CPU — expected: KILLED by the mem/CPU/time cap.
  - `datapath`: write `WORK/out.txt`, print a one-line JSON result — expected: only the printed text returns; `WORK` gone afterward.
- Invokes: `wsl.exe -d Ubuntu -- bash /mnt/.../isolate.sh <capfile> <allowlist> <runid>`; prints exit code + captured output; asserts the expected outcome per scenario and prints `PASS`/`FAIL`.

### `poc/wsl2_sandbox/README.md`

Provisioning commands (below) + a results table with the 7 checks, each marked pass/fail with a one-line note (esp. whether each step needed root, and whether DNS-sinkhole held).

## Acceptance criteria

1. **Provision** → `wsl.exe -d Ubuntu -- bash -lc 'command -v iptables dnsmasq'` prints a path for **both**.
2. **Baseline** → `python run.py hello` → exit 0, output contains `hello`, prints `PASS`.
3. **No-network default** → `python run.py net-blocked` → the fetch FAILS (network unreachable / DNS fail), scenario prints `PASS` (failure is the expected outcome).
4. **Egress allowlist** → `python run.py net-allowed` → `example.com` fetch SUCCEEDS **and** `bing.com` fetch FAILS → prints `PASS`.
5. **Resource caps** → `python run.py hog` → process is KILLED (non-zero exit) within wall-clock < 35 s → prints `PASS`.
6. **Data path + cleanup** → `python run.py datapath` → only the one-line result text is returned; a follow-up `wsl.exe -d Ubuntu -- bash -lc 'ls /tmp/artemis-* 2>/dev/null | wc -l'` returns `0` (tmpfs cleaned) → prints `PASS`.
7. **Unprivileged verdict recorded** → the README states which of checks 2–6 ran without `-u root`, and flags any that required privilege (drives the enabler #2 design: passwordless-sudo wrapper vs setuid vs root-invocation).

## Commands to run

```bash
# provision (one-time, in the Ubuntu distro):
wsl.exe -d Ubuntu -- sudo apt-get update
wsl.exe -d Ubuntu -- sudo apt-get install -y iptables dnsmasq

# run the 5 scenarios:
python poc/wsl2_sandbox/run.py hello
python poc/wsl2_sandbox/run.py net-blocked
python poc/wsl2_sandbox/run.py net-allowed
python poc/wsl2_sandbox/run.py hog
python poc/wsl2_sandbox/run.py datapath

# cleanup check (check 6):
wsl.exe -d Ubuntu -- bash -lc 'ls /tmp/artemis-* 2>/dev/null | wc -l'
```

## Notes for the builder
- Host env-probe (2026-07-01) already confirmed: unprivileged `unshare --net` works, cgroups v2 + systemd present, default NAT. Only `iptables`/`dnsmasq` needed installing (check 1).
- If DNS-sinkhole egress (check 4) proves leaky or awkward, record it and note the transparent-proxy path (tinyproxy + iptables REDIRECT) as the production upgrade — do **not** build the proxy in this spike.
- This is a spike: prefer the shortest script that makes the 7 checks pass. No abstraction, no `SandboxRunner` wiring.
