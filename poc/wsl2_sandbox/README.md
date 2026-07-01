# WSL2 Isolation PoC

Throwaway proof for running untrusted capability code inside WSL2 with no-network-by-default,
a per-run DNS egress allowlist, resource caps, and a text-only data path.

## Provisioning

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

## Results

_Verified on this host 2026-07-01 (Ubuntu WSL2 v2, distro Python 3.12). All scenarios run via
`wsl.exe -d Ubuntu -- bash …` as the **default user** — no `-u root`._

| # | Check | Result | One-line note |
|---|---|---|---|
| 1 | Provision: `command -v iptables dnsmasq` prints both paths. | ✅ PASS | `apt-get install -y iptables dnsmasq` → `/usr/sbin/iptables` + `/usr/sbin/dnsmasq`. The package auto-enables a system `dnsmasq.service` but it stays `failed` (no conflict on `127.0.0.1:53`; systemd-resolved holds `127.0.0.53`). |
| 2 | Baseline: `python run.py hello` exits 0, output contains `hello`, prints `PASS`. | ✅ PASS | exit 0, `hello`, ~0.1 s. |
| 3 | No-network default: `python run.py net-blocked` fetch fails and scenario prints `PASS`. | ✅ PASS | Empty allowlist → `unshare --net` full isolation → DNS resolution fails (`gaierror -3`); fetch fails as expected. |
| 4 | Egress allowlist: `python run.py net-allowed` allows `example.com` and blocks `bing.com`. | ✅ PASS | `example.com OK 200` + `bing.com BLOCKED URLError`. See **Network model** — allowlist branch drops `--net` and gates via DNS-sinkhole. |
| 5 | Resource caps: `python run.py hog` is killed/non-zero within wall-clock < 35 s. | ✅ PASS | Killed exit 137 at ~31–33 s. **Killed by the `ulimit -t 30` CPU-time cap, NOT the cgroup memory cap** — see **Resource caps**. |
| 6 | Data path + cleanup: `python run.py datapath` returns only one JSON line and leaves no `/tmp/artemis-*` work dirs. | ✅ PASS | Only `{"result": "datapath-ok"}` returned; `out.txt` stays in the tmpfs `WORK`; `ls /tmp/artemis-* \| wc -l` → 0 (trap cleanup fired). |
| 7 | Unprivileged verdict: record which checks 2-6 ran without `-u root`, and flag any that needed privilege. | ✅ PASS | **Checks 2–6 all ran unprivileged.** `unshare --net/--pid/--mount` and `systemd-run --scope` all work without root. Only provisioning (check 1 `apt-get`) needed sudo (passwordless on this host). |

## Findings (for enabler #2 — the real `FetchSandbox` / `SandboxRunner`)

**Network model — the spec's two mechanisms are mutually exclusive; resolved in `isolate.sh`.**
The spec said run *always* inside `unshare --net` **and** use a dnsmasq DNS-sinkhole allowlist. A
fully-isolated netns has no route out, so even an *allowed* domain is unreachable (check 4 failed
that way initially). Resolution: `--net` is now **conditional** — empty allowlist = pure no-network
(`--net`); non-empty allowlist = **host connectivity + a private (mount-namespaced) `resolv.conf`
pointing at the sinkhole dnsmasq**, which forwards only listed domains and returns `0.0.0.0` for
everything else. (Deviation from the spec's literal "always `--net`"; matches the DNS-sinkhole
mechanism the spec described in prose.)

**⚠️ DNS-sinkhole is a soft gate (leaky by design).** The allowlist tier gates **DNS only**. A
capability that connects to a hard-coded IP, or ships its own resolver / uses DoH, bypasses it
entirely. Adequate to *prove the mechanism* in this spike; **not** an egress boundary to trust for
untrusted code. Production upgrade (enabler #2, do NOT build in the spike per spec note):
transparent proxy (`tinyproxy` + `iptables … REDIRECT`) or an `iptables` egress **IP**-allowlist
(resolve allowed domains → allow only those IPs, default-drop the rest).

**⚠️ Resource caps: cgroup limits are NOT enforced unprivileged.** `systemd-run --scope
-p MemoryMax=… -p CPUQuota=…` *succeeds* unprivileged but the limits are **silently ignored** — the
memory controller isn't delegated to the unprivileged user's cgroup subtree (verified: a 1 GB
allocation under `MemoryMax=256M` succeeded). What actually bounds a runaway capability here is the
**`ulimit -t 30` CPU-time** limit (killed `hog` at exit 137), plus `ulimit -v 524288` on the
ulimit-fallback path. Enabler #2 must get real memory caps via one of: root-invoked `systemd-run`,
explicit cgroup **delegation** setup (`systemd` user-delegation of the memory controller), or rely
on `ulimit -v` (per-process virtual-memory) as the floor.

**Privilege verdict.** The whole isolation path (netns, pid-ns, mount-ns, tmpfs data path, CPU-time
cap) runs **unprivileged** on this host. Only one-time provisioning needs sudo. Enabler #2 does
**not** need a setuid/root-invocation wrapper for isolation itself — only if it wants enforced
**cgroup** memory/CPU caps (see above) or an `iptables`-based hard egress boundary.

