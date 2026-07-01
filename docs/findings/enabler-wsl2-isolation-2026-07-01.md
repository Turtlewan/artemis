# WSL2 Isolation Sandbox Design — Enabler Research
_Date: 2026-07-01 | Researcher: Claude Sonnet 4.6_

## 1. Repo Grounding: Protocol Shape

**File: `src/artemis/capabilities/sandbox.py`**

```python
@runtime_checkable
class SandboxRunner(Protocol):
    async def run_tests(self, skill_dir: Path) -> VerifyResult: ...

class VerifyResult(BaseModel):
    passed: bool
    output: str
```

The protocol is minimal: one async method, one directory in, one result out. This is the seam behind which any isolation runner plugs in.

**Current implementation: `SubprocessSandbox`**
- Runs `sys.executable -m pytest tests -q` as a host subprocess with `cwd=skill_dir`
- Wall-clock timeout (default 30 s) via `asyncio.wait_for`
- Zero isolation: same network, same PID namespace, same user, same filesystem as the host process

**Call chain:**
- `forge.py` → `CapabilityForge.__init__(sandbox: SandboxRunner)` → `sandbox.run_tests(staging_dir(staged.id))`
- `app.py` → `create_app(sandbox: SandboxRunner | None)` defaults to `SubprocessSandbox()`, accepts injection
- `scan_for_unsafe_imports` in `forge.py` is an AST-level guard that blocks network-importing capabilities from running in the current no-isolation sandbox; the comment explicitly states the WSL2 runner is the real boundary

**What the new runner receives:**
`skill_dir` is a Windows path like `C:\Users\User\artemis\data\capabilities\staging\<id>\`. It contains:
- `tool.py` — the authored capability module
- `tests/` — pytest test module(s)
- A future `sandbox_policy.json` (see §3) for the egress allowlist

---

## 2. Requirements Mapping

| Req | Description |
|-----|-------------|
| (a) | No-network by default |
| (b) | Per-capability egress allowlist (domain-level) |
| (c) | CPU, memory, wall-clock resource caps |
| (d) | Clean data-in / data-out that does NOT punch a hole in isolation |

---

## 3. WSL2 Mechanisms — Per Requirement

### WSL2 Networking Modes (background)

WSL2 has two networking modes configured via `%USERPROFILE%\.wslconfig`:

**NAT mode (default):**
```ini
[wsl2]
networkingMode=nat
```
- WSL2 runs inside a lightweight Hyper-V VM. The VM has a private IP (172.x.x.x range).
- All outbound traffic is SNAT'd by the Windows NAT. Linux iptables rules on the VM control what exits.
- `iptables`/`nftables` within WSL2 fully apply to the VM's traffic before it hits the NAT.
- GOTCHA: `iptables -L` may show nothing even when rules exist — use `iptables -S` to list rules in save format.

**Mirrored mode (Windows 11 22H2+, WSL2 >= 2.0):**
```ini
[wsl2]
networkingMode=mirrored
```
- WSL2 shares the host's network interfaces. No private VM subnet. The Linux side sees the same IPs as Windows.
- GOTCHA: Network namespaces still work for isolation, but inter-namespace traffic routing is different. The default namespace has mirrored adapters; a new namespace starts empty (loopback only) just like in NAT mode. This is actually fine for isolation — a new netns is still isolated.
- GOTCHA: iptables FORWARD chain behavior differs because traffic doesn't transit a router hop inside the VM.

**Verdict: NAT mode is the safer target for isolation.** Mirrored mode can be supported but needs separate testing.

---

### Req (a): No-Network by Default

**Mechanism: Network namespace (`netns`) isolation via `unshare` or `ip netns`**

A new Linux network namespace starts with ONLY a loopback interface and no routing. This is exactly "no network."

Two invocation paths:

**Path 1 — Unprivileged user namespaces (`unshare`):**
```bash
unshare --net --pid --fork -- python -m pytest tests/ -q
```
Requires: `CONFIG_USER_NS=y` (check: `cat /proc/sys/kernel/unprivileged_userns_clone` should be 1)

WSL2 kernel 5.15.x (shipping as of late 2023) has `CONFIG_USER_NS=y`. Check:
```bash
wsl.exe -- uname -r                   # e.g. 5.15.167.4-microsoft-standard-WSL2
wsl.exe -- cat /proc/sys/kernel/unprivileged_userns_clone   # 1 = enabled
```
If enabled, an unprivileged user can create a new netns — no root needed.

**Path 2 — Root via `ip netns` (fallback):**
```bash
wsl.exe -u root -- ip netns add artemis-cap-<run-id>
wsl.exe -u root -- ip netns exec artemis-cap-<run-id> python -m pytest tests/ -q
wsl.exe -u root -- ip netns del artemis-cap-<run-id>
```
Requires root. WSL2 allows passwordless root via `-u root` when the distro's sudoers / root account is unlocked.

**GOTCHA — `unshare` PID 1 issue:** When using `--pid --fork`, the `unshare` process becomes PID 1 inside the new namespace. If PID 1 dies before children, they get SIGKILLed. Use `--kill-child` flag:
```bash
unshare --net --pid --fork --kill-child -- python -m pytest tests/ -q
```

**Recommendation:** Attempt unprivileged `unshare` first; fall back to root `ip netns` with a warning in config. Probe at startup.

---

### Req (b): Per-Capability Egress Allowlist

This is the hardest requirement. iptables/nftables operates on IP addresses, not domain names. Domains resolve to dynamic IPs (googleapis.com → many IPs, rotating). Three approaches:

#### Option B1: DNS Sinkhole + IP-pinned Rules (simplest, fragile on IP rotation)

1. Resolve allowlisted domains to IPs at capability-registration time.
2. Add iptables rules to allow only those IPs:
```bash
iptables -P OUTPUT DROP
iptables -A OUTPUT -d 8.8.8.8 -j ACCEPT       # DNS resolver (only if needed)
iptables -A OUTPUT -d 142.250.0.0/15 -j ACCEPT  # resolved google IPs
# ...
```
Fragile: CDN IPs rotate. Google alone has /8 blocks. Works for fixed-IP APIs, not cloud services.

#### Option B2: Transparent Proxy with Domain Allowlist (recommended)

Run a lightweight HTTP/HTTPS proxy inside the namespace that enforces domain-level allowlisting. Only the proxy is allowed outbound; all other egress is dropped.

Architecture:
```
capability process → TPROXY (iptables redirect port 3128) → tinyproxy/3proxy
                                                              └─ allows only whitelisted domains
                                                              └─ denies everything else
```

For HTTPS, the proxy does a CONNECT tunnel (MITM for domain inspection, or just pass-through with SNI inspection). For a pure allowlist (not content inspection), SNI-based filtering at the proxy level is sufficient.

Setup within the netns:
```bash
# Start proxy in the netns
ip netns exec sandbox-ns tinyproxy -c /tmp/tinyproxy-<id>.conf

# Redirect all TCP 80/443 to proxy (TPROXY requires root)
ip netns exec sandbox-ns iptables -t nat -A OUTPUT -p tcp --dport 80 -j REDIRECT --to-port 3128
ip netns exec sandbox-ns iptables -t nat -A OUTPUT -p tcp --dport 443 -j REDIRECT --to-port 3128
ip netns exec sandbox-ns iptables -A OUTPUT -p tcp --dport 3128 -j ACCEPT
ip netns exec sandbox-ns iptables -P OUTPUT DROP
```

tinyproxy ACL config (generated per-capability):
```
Allow 127.0.0.1
Filter "/tmp/allowlist-<id>"     # domain allowlist file
FilterURLs On
FilterExtended On
```

GOTCHA: TPROXY redirect in a new netns requires iptables NAT support. Check: `lsmod | grep nf_nat` in WSL2. In NAT networking mode, this is present. In mirrored mode, test explicitly.

GOTCHA: Capabilities using raw sockets or UDP (not HTTP/HTTPS) bypass the HTTP proxy. Use a separate iptables rule to DROP non-TCP or non-port-80/443 traffic at the OUTPUT chain.

GOTCHA for HTTPS: Python's `httpx`/`requests` will need to honor the `http_proxy`/`https_proxy` env vars, OR the TPROXY redirect approach intercepts at the network layer regardless. With TPROXY, the library doesn't need to be proxy-aware.

#### Option B3: DNS Allowlist Only (lightweight but bypassable)

Run a custom DNS server inside the netns (dnsmasq in "allow-list" mode) that only resolves whitelisted domains. All other DNS queries return NXDOMAIN. Block all DNS except to this server:
```bash
iptables -A OUTPUT -p udp --dport 53 -d 127.0.0.1 -j ACCEPT
iptables -A OUTPUT -p udp --dport 53 -j DROP
# dnsmasq: only serve whitelisted domains
```
BYPASSABLE: A capability that hard-codes IP addresses bypasses DNS entirely.

**Recommended approach: Option B2 (transparent proxy) for production integrity; Option B3 (DNS sinkhole) as a fast-to-build approximation for the spike.**

**Egress allowlist delivery mechanism:**
The `SandboxRunner.run_tests(skill_dir)` protocol only takes a path. Two options:
1. **Read from skill dir:** The forge writes `sandbox_policy.json` into the staging dir alongside `tool.py`:
   ```json
   { "egress_domains": ["googleapis.com", "oauth2.googleapis.com"] }
   ```
   The WSL2 runner reads this before launching. No protocol change needed.
2. **Extend the protocol:** Add optional kwargs: `async def run_tests(self, skill_dir: Path, *, policy: SandboxPolicy | None = None) -> VerifyResult`. Protocol extension is additive; `SubprocessSandbox` ignores the parameter.

Option 1 (policy file in skill_dir) is simpler and keeps the seam unchanged. **Recommend option 1.**

---

### Req (c): CPU, Memory, Wall-Clock Resource Caps

**Wall-clock timeout:** Already handled by `asyncio.wait_for` in `SubprocessSandbox`. Carry forward.

**CPU time + Memory — two tiers:**

**Tier 1 (no root): `ulimit` per subprocess**
```bash
ulimit -t 30    # CPU seconds hard limit (SIGKILL at limit)
ulimit -v 524288  # virtual memory kB (512 MB)
python -m pytest tests/ -q
```
Can be set in the shell script passed to WSL2. Works unprivileged. Limitation: VM-level limits, not cgroup-enforced; a process can re-exec to escape ulimits.

**Tier 2 (with root or systemd): cgroups v2**
WSL2 5.15+ supports cgroups v2. Check:
```bash
wsl.exe -- cat /sys/fs/cgroup/cgroup.controllers  # should list cpu memory pids
```

Without systemd (default):
```bash
# Create a cgroup
mkdir /sys/fs/cgroup/artemis-<id>
echo "100000 1000000" > /sys/fs/cgroup/artemis-<id>/cpu.max   # 10% of one core
echo "536870912" > /sys/fs/cgroup/artemis-<id>/memory.max      # 512 MB
echo "100" > /sys/fs/cgroup/artemis-<id>/pids.max              # max 100 PIDs
echo $$ > /sys/fs/cgroup/artemis-<id>/cgroup.procs             # add current process
# Run pytest here — it inherits the cgroup
```
Requires root to write to cgroup hierarchy. If running as root for the netns anyway, this is free.

With systemd (opt-in, `/etc/wsl.conf` `systemd=true`):
```bash
systemd-run --scope \
  --property MemoryMax=512M \
  --property CPUQuota=10% \
  --property TasksMax=100 \
  ip netns exec sandbox-ns python -m pytest tests/ -q
```
Cleanest approach if systemd is available. Check: `wsl.exe -- systemctl is-system-running`.

**GOTCHA — WSL2 memory pressure:** WSL2's `.wslconfig` has a global `memory=4GB` cap. Per-cgroup limits work within this global cap but the host machine memory can affect WSL2 available memory.

**Recommendation:** ulimit as baseline (unprivileged, no dependencies), cgroups v2 writes as the hardened path (requires root). Probe at startup which is available.

---

### Req (d): Data-In / Data-Out Without Punching Isolation Holes

**Current data path:**
- `skill_dir` is a Windows path (e.g., `C:\Users\User\artemis\data\capabilities\staging\abc123\`)
- WSL2 mounts Windows drives at `/mnt/c/...`, `/mnt/d/...` etc.
- Reading `tool.py` and `tests/` via `/mnt/c/...` is fine — read-only access to a staging directory
- Writing: tests should not write outside their temp dir; `pytest` captures stdout/stderr

**Three data path options:**

**Option D1 (simplest): Read from `/mnt/c/...` path directly**
```python
# host runner converts: C:\Users\User\... → /mnt/c/Users/User/...
wsl_skill_dir = "$(wslpath -u 'C:\\Users\\User\\...')"
```
Inside the netns, `/mnt/c` is still accessible because the mount namespace is inherited from the parent (unless `--mount` is used in `unshare`).
Risk: the capability's code can WRITE to `/mnt/c` (the Windows filesystem). If the capability is malicious, it can modify files outside the staging dir.
Mitigation: bind-mount the staging dir read-only inside the netns, and block `/mnt/c` writes via the mount namespace.

**Option D2 (recommended): Copy into tmpfs, capture stdout/stderr only**
```bash
# 1. Copy skill_dir into a tmpfs inside WSL2
cp -r /mnt/c/.../staging/abc123 /tmp/artemis-sandbox-abc123

# 2. Run pytest with cwd=/tmp/artemis-sandbox-abc123 inside the netns
# stdout/stderr captured as VerifyResult.output

# 3. Delete /tmp/artemis-sandbox-abc123 after
```
The isolation boundary is clean: capability code only sees a tmpfs copy. No Windows filesystem access. The result (stdout/stderr text) is passed back through the subprocess pipe — this is just text, not a filesystem path, so it cannot be used to escape isolation.

`VerifyResult.output` is already capped at 4000 characters in `SubprocessSandbox._truncate`. Keep this cap.

**Option D3: stdin/stdout JSON envelope**
Pass the code as a JSON envelope on stdin, get results on stdout. More complex, not needed given D2's simplicity.

**Recommendation: Option D2.** Copy to tmpfs, run in netns, capture stdout/stderr, delete. No shared mutable filesystem between host and sandbox during execution.

**Path between host (Python/Windows) and WSL2 subprocess:**
```python
async def run_tests(self, skill_dir: Path) -> VerifyResult:
    # Convert Windows path → WSL path
    result = await asyncio.create_subprocess_exec(
        "wsl.exe", "--", "wslpath", "-u", str(skill_dir),
        stdout=asyncio.subprocess.PIPE
    )
    stdout, _ = await result.communicate()
    wsl_path = stdout.decode().strip()
    
    # Run isolation script via wsl.exe
    script = self._build_script(wsl_path, policy)
    proc = await asyncio.create_subprocess_exec(
        "wsl.exe", "-u", "root", "--", "bash", "-s",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(
        proc.communicate(input=script.encode()), timeout=self._timeout_s
    )
    passed = proc.returncode == 0
    return VerifyResult(passed=passed, output=self._truncate((stdout + stderr).decode()))
```

---

## 4. WSL2 Isolation Script — Concrete Sketch

For the spike, a shell script that `wsl.exe -u root -- bash -s` receives on stdin:

```bash
#!/usr/bin/env bash
set -euo pipefail

SKILL_DIR_WSL="$1"   # passed as arg or embedded
RUN_ID="$(uuidgen | tr -d '-')"
NS="artemis-$RUN_ID"
WORKDIR="/tmp/artemis-run-$RUN_ID"

# Cleanup on exit
cleanup() {
    ip netns del "$NS" 2>/dev/null || true
    rm -rf "$WORKDIR" 2>/dev/null || true
    # Remove cgroup if created
    rmdir /sys/fs/cgroup/artemis-"$RUN_ID" 2>/dev/null || true
}
trap cleanup EXIT

# 1. Copy skill into tmpfs workdir
cp -r "$SKILL_DIR_WSL" "$WORKDIR"

# 2. Create network namespace (no-network by default)
ip netns add "$NS"

# 3. (If egress allowlist provided) add veth pair + iptables rules inside NS
# [see Option B2 above — omitted from spike]

# 4. Set resource limits via cgroups v2 (if available) or ulimit
if [ -d /sys/fs/cgroup ]; then
    mkdir -p /sys/fs/cgroup/artemis-"$RUN_ID"
    echo "100000 1000000" > /sys/fs/cgroup/artemis-"$RUN_ID"/cpu.max
    echo "536870912"      > /sys/fs/cgroup/artemis-"$RUN_ID"/memory.max
    echo "100"            > /sys/fs/cgroup/artemis-"$RUN_ID"/pids.max
    CGROUP_PROCS=/sys/fs/cgroup/artemis-"$RUN_ID"/cgroup.procs
    CGEXEC_CMD="bash -c 'echo \$\$ > $CGROUP_PROCS && exec \"\$@\"' --"
else
    CGEXEC_CMD="bash -c 'ulimit -t 30 -v 524288; exec \"\$@\"' --"
fi

# 5. Run pytest inside the namespace
ip netns exec "$NS" $CGEXEC_CMD \
    python3 -m pytest "$WORKDIR/tests" -q --tb=short 2>&1
```

---

## 5. Feasibility Verdict for WSL2

| Aspect | Verdict | Notes |
|--------|---------|-------|
| No-network default | **Achievable** | `unshare --net` or `ip netns` — both proven in WSL2 5.15+ |
| Egress allowlist | **Achievable, non-trivial** | Transparent proxy (B2) works but adds tinyproxy/dnsmasq dependency; DNS sinkhole (B3) is simpler but bypassable |
| Resource caps | **Achievable** | ulimit = baseline (no root); cgroups v2 = hardened path (root required) |
| Data path | **Achievable** | tmpfs copy + stdout/stderr pipe is clean; no holes |
| Root requirement | **Probable blocker if avoided** | `ip netns add` requires root; `unshare --net` may work unprivileged if `unprivileged_userns_clone=1` |
| Network mode sensitivity | **Risk** | Behavior differs between NAT and mirrored mode; mirrored mode needs explicit testing |
| Parallel runs | **Manageable** | Each run uses a unique NS name and tmpfs dir; cleanup via `trap EXIT` |

**Hard unknowns to resolve in spike:**
1. Is `unprivileged_userns_clone` enabled on this machine? (`cat /proc/sys/kernel/unprivileged_userns_clone`)
2. Is cgroups v2 present? (`ls /sys/fs/cgroup/cgroup.controllers`)
3. Is systemd available? (`systemctl is-system-running` in WSL2)
4. Does iptables NAT (REDIRECT target) work in this WSL2 kernel? (`modprobe nf_nat` test)
5. What WSL2 networking mode is active? (`cat /etc/resolv.conf` — if nameserver is 172.x.x.x, NAT mode)

**Overall feasibility: HIGH** for requirements (a), (c), (d). **MEDIUM** for (b) due to egress proxy complexity. A spike resolving the 5 unknowns above should take 1–2 days.

---

## 6. macOS Backend

The Mac Mini production target has different primitives. Three options:

### Option M1: Lima VM (recommended for cross-platform parity)

[Lima](https://github.com/lima-vm/lima) runs a Linux VM on macOS using Apple's Virtualization.framework (Apple Silicon) or QEMU (Intel). Inside the Lima VM, you get a full Linux environment — the SAME network namespace + cgroups v2 + iptables mechanisms as WSL2.

Implication: The isolation shell script written for WSL2 **runs unchanged inside Lima**. The Python `SandboxRunner` implementation only changes the outer invocation:
- WSL2: `wsl.exe -u root -- bash -s`
- Lima: `limactl shell <instance> -- bash -s` (or `lima -- bash -s`)

One codebase, two thin transport wrappers. The isolation logic is shared.

Lima setup for Artemis:
```yaml
# ~/.lima/artemis-sandbox/lima.yaml
images:
  - location: "https://cloud-images.ubuntu.com/releases/24.04/release/ubuntu-24.04-server-cloudimg-arm64.img"
arch: aarch64
memory: 2GiB
cpus: 2
mounts:
  - location: "~"
    writable: false  # host home read-only inside VM
networks:
  - lima: user-v2  # NAT networking — same model as WSL2 NAT
```

### Option M2: `sandbox-exec` / Seatbelt (macOS-native, deprecated)

macOS has a kernel-level sandbox (`AppleSandbox`) accessible via `sandbox-exec`:
```bash
sandbox-exec -f /path/to/profile.sb python -m pytest tests/ -q
```

Seatbelt profile syntax (Scheme DSL):
```scheme
(version 1)
(deny default)
(allow process-exec)
(allow file-read* (subpath "/tmp/artemis-run"))
(allow network-outbound (remote ip "142.250.80.46:443"))  ; whitelisted IP
(deny network-outbound)
```

Limitations:
- `sandbox-exec` is deprecated since macOS 10.15 (Catalina) but still functional in Sonoma/Sequoia. Apple has not removed it but may.
- Domain-level allowlisting requires IP resolution, same problem as iptables.
- No cgroups; resource limits via `setrlimit` only.
- Requires a different code path from WSL2 — no shared isolation script.

**Not recommended as the primary path** due to deprecation risk and the divergent code path.

### Option M3: OCI container (Docker / Podman)

```bash
docker run --rm --network none \
  --memory 512m --cpus 0.5 \
  -v /path/to/staging/abc123:/workdir:ro \
  python:3.12-slim pytest /workdir/tests -q
```

For egress: `--network none` + a custom Docker network with iptables rules, or use a network policy.

Pros: Standard, well-documented, egress filtering via Docker networks.
Cons: Docker Desktop for Mac is paid for commercial use; Podman is free but has its own quirks; container startup adds latency (~500ms per run); doesn't share the WSL2 invocation pattern.

### Recommended macOS Strategy: Lima

Lima gives parity with WSL2. The isolation script is identical. The only divergence is the invocation line. This maps to a single `Wsl2SandboxRunner` class on Windows and a `LimaSandboxRunner` on macOS, both delegating to the same bash script — or a single `LinuxVmSandboxRunner` with an injected transport (the WSL2 or Lima invocation).

---

## 7. Protocol Extension Needed

The current `SandboxRunner` protocol takes only `skill_dir: Path`. For per-capability egress allowlists, the runner needs to know the allowed domains. Two paths:

**Path 1 (recommended): Policy file in skill_dir**
The forge writes `sandbox_policy.json` into the staging dir:
```json
{
  "egress_domains": ["googleapis.com", "oauth2.googleapis.com"],
  "memory_mb": 512,
  "cpu_pct": 10,
  "timeout_s": 60
}
```
The WSL2 runner reads this before launching. Protocol unchanged. `SubprocessSandbox` ignores the file.

`SkillDraft` in `types.py` would gain an `egress_domains: list[str] = []` field. The forge writes the policy file when staging. This is the cleanest path.

**Path 2: Protocol extension**
```python
class SandboxRunner(Protocol):
    async def run_tests(
        self,
        skill_dir: Path,
        *,
        policy: SandboxPolicy | None = None,
    ) -> VerifyResult: ...
```
`SubprocessSandbox.run_tests` accepts and ignores `policy`. Callers pass it when available.

---

## 8. Risk Register

| Risk | Severity | Notes |
|------|----------|-------|
| `ip netns add` requires root — host process runs as user | HIGH | Mitigated by: (1) setuid wrapper script, (2) WSL2 `-u root` with passwordless sudoers, (3) probe for unprivileged `unshare` first |
| iptables NAT REDIRECT not available in WSL2 kernel | MEDIUM | Test `iptables -t nat -A OUTPUT -p tcp -j REDIRECT` in WSL2 |
| `tinyproxy` not in WSL2 distro | LOW | `apt-get install tinyproxy` once; pre-install in distro setup |
| cgroups v2 not mounted in this WSL2 version | MEDIUM | Fallback to ulimit if not present |
| Parallel runs clash on cgroup/netns names | LOW | Use uuid-based names, cleanup via `trap EXIT` |
| Lima startup latency on Mac Mini | LOW | Lima VM stays running; only `limactl shell` invocation per test run |
| `sandbox_policy.json` not written by forge yet | — | Forge change needed (SkillDraft + stage() write) |
| Windows path → WSL path conversion edge cases (spaces) | LOW | Use `wslpath -u` with proper quoting |

---

## 9. Spike Recommendation

**A spike is needed** before building the full WSL2 runner. Scope: 1–2 dev-days.

Spike tasks:
1. In WSL2 (current machine), run: `unshare --net --pid --fork -- python3 -c "import socket; socket.gethostbyname('google.com')"` — expect failure if isolation works.
2. Verify cgroups v2: `ls /sys/fs/cgroup/cgroup.controllers`
3. Verify iptables NAT: `sudo iptables -t nat -L`
4. Prototype `Wsl2SandboxRunner.run_tests()` with a hard-coded test capability that tries to reach the internet — confirm it's blocked.
5. Add the DNS sinkhole (Option B3) and verify a whitelisted domain works while others fail.
6. Measure per-run latency overhead (netns setup + tmpfs copy + pytest + cleanup).

Spike deliverable: a `poc/wsl2_sandbox.py` + a `poc/test_wsl2_sandbox.py` proving requirements (a) and (c); (b) with B3 (DNS sinkhole) at minimum.

---

## 10. Implementation Sketch (post-spike)

```python
# src/artemis/capabilities/sandbox_wsl2.py

import asyncio
import json
from pathlib import Path
from artemis.capabilities.sandbox import SandboxRunner, VerifyResult

_ISOLATION_SCRIPT = r"""
set -euo pipefail
SKILL_WSL="$1"
DOMAINS="$2"   # comma-separated or empty
RUN_ID="$(cat /proc/sys/kernel/random/uuid | tr -d '-')"
NS="artemis-$RUN_ID"
WORK="/tmp/artemis-$RUN_ID"
cleanup() { ip netns del "$NS" 2>/dev/null||true; rm -rf "$WORK" 2>/dev/null||true; }
trap cleanup EXIT
cp -r "$SKILL_WSL" "$WORK"
ip netns add "$NS"
# TODO: if DOMAINS non-empty, set up dns sinkhole or proxy inside NS
ip netns exec "$NS" bash -c "
  ulimit -t 30 -v 524288
  cd '$WORK'
  python3 -m pytest tests/ -q --tb=short 2>&1
"
""".strip()

class Wsl2SandboxRunner:
    def __init__(self, *, timeout_s: float = 60.0, wsl_distro: str | None = None) -> None:
        self._timeout_s = timeout_s
        self._distro = wsl_distro  # None = default WSL2 distro

    async def run_tests(self, skill_dir: Path) -> VerifyResult:
        # Read policy if present
        policy_file = skill_dir / "sandbox_policy.json"
        domains = ""
        if policy_file.exists():
            p = json.loads(policy_file.read_text())
            domains = ",".join(p.get("egress_domains", []))

        # Convert Windows path to WSL path
        wsl_path = await self._wslpath(skill_dir)

        # Build wsl.exe command
        cmd = ["wsl.exe", "-u", "root"]
        if self._distro:
            cmd += ["-d", self._distro]
        cmd += ["--", "bash", "-s", "--", wsl_path, domains]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(input=_ISOLATION_SCRIPT.encode()),
                timeout=self._timeout_s,
            )
        except TimeoutError:
            proc.kill()
            stdout, stderr = await proc.communicate()
            return VerifyResult(passed=False, output="sandbox timeout exceeded")

        output = (stdout + stderr).decode(errors="replace")[:4000]
        return VerifyResult(passed=proc.returncode == 0, output=output)

    async def _wslpath(self, win_path: Path) -> str:
        proc = await asyncio.create_subprocess_exec(
            "wsl.exe", "--", "wslpath", "-u", str(win_path),
            stdout=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        return stdout.decode().strip()
```

---

## References

- WSL2 kernel source: https://github.com/microsoft/WSL2-Linux-Kernel
- WSL networking modes: https://learn.microsoft.com/en-us/windows/wsl/networking
- Lima: https://github.com/lima-vm/lima
- tinyproxy: https://tinyproxy.github.io/
- Linux cgroups v2: https://www.kernel.org/doc/html/latest/admin-guide/cgroup-v2.html
- macOS sandbox-exec: `man sandbox-exec` (deprecated, available through Sonoma)
- `ip netns` manpage: https://man7.org/linux/man-pages/man8/ip-netns.8.html
