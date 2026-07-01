---
spec: enabler-wsl2-runner
status: ready
token_profile: balanced
autonomy_level: L2
risk: high
coder_effort: high
# domain: security — untrusted-code execution boundary. Dispatched apex-spec-reviewer (security) pass required.
---

# Spec: Hardened root-backed WSL2 SandboxRunner

**Identity:** Production `Wsl2SandboxRunner` behind the `SandboxRunner` seam — root-backed WSL2 isolate (transparent-proxy egress + cgroups-v2 caps + tmpfs) plus the shared `run_isolated` helper and `default_sandbox()` probe.
→ why: see docs/technical/adr/ADR-036-hardened-wsl2-sandbox.md and docs/technical/adr/ADR-035-reach-out-capabilities.md (decision 7). Contracts: docs/drafts/enabler-sandbox-DESIGN-BRIEF.md (C1/C2/C3). Proven mechanism hardened here: poc/wsl2_sandbox/isolate.sh + README.md.

## Assumptions
- Passwordless `wsl.exe -u root` is available on the dev host (ADR-036 confirms) → impact: Stop (probe must fall back to SubprocessSandbox, never hard-fail)
- WSL2 distro is provisioned with `iptables`, `nginx` + `libnginx-mod-stream`, `dnsmasq`, `util-linux` (`setpriv`/`unshare`), cgroups-v2 available to root, a dedicated untrusted UID (`artemis-cap`, 4000), `.wslconfig` `networkingMode=nat`, `/etc/wsl.conf` `systemd=true` (provisioning documented in module docstring + Commands) → impact: Caution (live WSL tests skip when absent; provisioning is a one-time manual step, not build-time)
- The C2 command is passed as trailing positional args (`"$@"` after run_id), not a single re-split string, so no shell-quoting of the command is needed → impact: Low
- The untrusted command runs inside a **private mount+pid namespace** (`unshare --mount --pid --fork`) with `/` made `rprivate` (fail-closed, not swallowed — a failed `--make-rprivate` aborts so the `/mnt` tmpfs can't propagate host-wide), `/mnt` masked by tmpfs (Windows drives invisible), and `/proc` remounted (`mount -t proc proc /proc`) so the capability sees only its own pid ns, not host PIDs/cmdlines/other sandbox run_ids → impact: Stop (unmasked `/mnt/c` is a host-filesystem escape; host `/proc` leaks other runs; the reviewer must confirm both)
- Setup **fails closed**: `set -euo pipefail` + an explicit `abort` guard after every security-critical step (cgroup writes, netns, ipv6-off, dnsmasq, nginx, each iptables rule) means the untrusted command never runs if isolation setup failed → impact: Stop
- The capability's DNS is pinned to a single in-ns stub resolver (`127.0.0.1:53`, dnsmasq resolving everything to a dummy IP, `--conf-file=/dev/null` so no ambient config is read); startup is **verified** (`kill -0 "$DNSPID"` after a short settle — backgrounding always returns success, so the old `& disown || abort` was dead code); all other DNS (UDP+TCP/53 to any other host) is dropped, closing the DNS-exfil covert channel → impact: Caution (acceptance criterion covers TXT-exfil block)
- The nginx firewall config lives in a **root-owned** dir (`/run/artemis-ngx-<run_id>`, never chowned); only the tmpfs `$WORK` (capability code) is chowned to the untrusted UID, so the capability cannot replace its own egress config → impact: Stop
- IPv6 is disabled inside the netns (`sysctl net.ipv6.conf.*.disable_ipv6=1`), since the iptables rules are v4-only → impact: Caution (acceptance criterion covers blocked v6 egress)
- Egress domains are validated by the sibling `enabler-sandbox-policy-wiring` (policy writer) AND defensively re-validated guest-side before templating into nginx.conf: split under `set -f` (noglob) so wildcard tokens can't glob to filenames, whole-string bash `=~` match (not per-line `grep`), and explicit newline/CR rejection — so a value like `ok.com\n<nginx-directive>` cannot inject into the egress-control config. nginx.conf is emitted as literal per-domain `map` entries → impact: Stop (config injection defeats the whole egress boundary)
- Egress is enforced by **nginx** (`stream` `ssl_preread` maps the TLS SNI for HTTPS; `http` `$host` map for plain HTTP), fronted by `iptables -t nat OUTPUT REDIRECT` with `-m owner --uid-owner` matching; default-deny. NOT tinyproxy (it can't SNI-filter transparent HTTPS) and NOT TPROXY (`xt_TPROXY` often absent in the WSL2 kernel). → impact: Caution (acceptance criteria 3/4 are the gate; residual live-only unknowns: kernel `nf_nat`/`REDIRECT` in a hand-made netns, the netns DNS path for nginx `resolver`, WSL `MASQUERADE` regressions — ADR-036 Consequences)
- The untrusted capability runs **de-privileged** (dedicated non-root UID via `setpriv`, all caps dropped); root is used only for setup (netns/iptables/nginx/cgroup). This is load-bearing: if the capability ran as root it could `iptables -F` and void the egress firewall. → impact: Stop (a root-run capability breaks the whole boundary — the reviewer must confirm de-privileging)
- Provisioned distro has a dedicated untrusted UID (4000) and the `www-data` UID (33) for nginx; `nginx -V` includes `ssl_preread` (Ubuntu `libnginx-mod-stream`) → impact: Caution (verified in provisioning; live tests skip when absent)
- Caps are delivered to the guest via `WSLENV`-exported env vars (`MEM_MAX`/`CPU_MAX`/`PIDS_MAX`/`ULIMIT_T`), keeping the embedded script a brace-heavy constant untouched by `.format()` → impact: Low

Simplicity check: considered simpler approach? yes — keep the spike's unprivileged DNS-sinkhole + ulimit. Rejected: ADR-036 requires an enforced boundary (DNS sinkhole is IP-bypassable, unprivileged cgroup caps are silently ignored — spike checks 4/5). Root-backed transparent-proxy + cgroups-v2 is the minimum that makes external-authored code trustable.

## Prerequisites
- Specs that must be complete first: none (this is the foundation for enabler-sandbox-policy-wiring and enabler-fetch-sandbox)
- Environment setup: one-time WSL2 provisioning (see Commands) — not required to build/verify the pure-logic path; live WSL tests skip cleanly without it

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| src/artemis/capabilities/sandbox_wsl2.py | create | `Wsl2SandboxRunner` + embedded C2 hardened isolate script + `run_isolated` (C3) + `SandboxCaps` model + `default_sandbox()` probe factory; module docstring carries provisioning steps |
| src/artemis/api/app.py | modify | one line: `resolved_sandbox: SandboxRunner = sandbox if sandbox is not None else default_sandbox()` (keep injection override); update import |
| tests/capabilities/test_sandbox_wsl2.py | create | pure-logic unit tests (no WSL) + live WSL tests gated by a probe fixture that skips cleanly. Also create `tests/capabilities/__init__.py` |

## Tasks
- [ ] Task 1: Create `sandbox_wsl2.py` — `SandboxCaps` (pydantic: `memory_mb=512`, `cpu_pct=100`, `pids_max=128`, `timeout_s=60.0`, matching C1 defaults); embedded `_ISOLATE_SCRIPT` (C2, below); `run_isolated(...)` (C3 signature, below); `Wsl2SandboxRunner(SandboxRunner)` reading `sandbox_policy.json` (C1) — absent → no-network + default caps; `default_sandbox() -> SandboxRunner` (sync probe). Module docstring lists provisioning. — files: src/artemis/capabilities/sandbox_wsl2.py — done when: `uv run mypy src/artemis/capabilities/sandbox_wsl2.py` is clean and `python -c "from artemis.capabilities.sandbox_wsl2 import Wsl2SandboxRunner, run_isolated, SandboxCaps, default_sandbox"` succeeds
- [ ] Task 2: Change the `create_app` default from `SubprocessSandbox()` to `default_sandbox()` (one line), update the import to add `default_sandbox`; keep the `sandbox` injection override untouched. — files: src/artemis/api/app.py — done when: `create_app()` with no `sandbox` arg resolves via `default_sandbox()`; existing `tests/test_app.py` + `tests/test_api_capabilities.py` still pass
- [ ] Task 3: Create `tests/capabilities/__init__.py` + `tests/capabilities/test_sandbox_wsl2.py`. Unit (no WSL): policy parse (present/absent → egress + caps), `SandboxCaps` defaults, wslpath conversion (monkeypatch the subprocess), `default_sandbox()` fallback to `SubprocessSandbox` when probe fails. Live WSL (probe fixture, `pytest.skip` when `wsl.exe`/provisioning absent): no-network default blocks egress, transparent-proxy allows-one/blocks-another, cgroup memory cap kills an over-allocation, tmpfs cleanup leaves no `/tmp/artemis-*`. — files: tests/capabilities/__init__.py, tests/capabilities/test_sandbox_wsl2.py — done when: `uv run pytest -q tests/capabilities/test_sandbox_wsl2.py` is green with live tests SKIPPED on a host without WSL provisioning

### C2 — embedded hardened isolate script (`_ISOLATE_SCRIPT`, invoked `wsl.exe -u root -- bash -s -- <skill_wsl_path> <egress_csv> <run_id> <command...>`, stdin = script)
Harden the spike's `poc/wsl2_sandbox/isolate.sh` to:
```bash
set -euo pipefail    # BLOCK 2: -e so any setup failure ABORTS before the untrusted command runs (fail CLOSED)
SKILL_WSL="$1"; EGRESS_CSV="$2"; RUN_ID="$3"; shift 3   # remaining "$@" = command tokens
NS="artemis-$RUN_ID"; WORK="/tmp/artemis-$RUN_ID"; CG="/sys/fs/cgroup/artemis-$RUN_ID"
NGXDIR="/run/artemis-ngx-$RUN_ID"                       # BLOCK 4: ROOT-OWNED firewall-config dir, NEVER chowned
NGX_HTTPS=8443; NGX_HTTP=8080; UNTRUSTED_UID=4000; NGINX_UID=33   # nginx=www-data; capability de-privileged
DNS_STUB=127.0.0.1                                      # BLOCK 3: the only resolver the capability may reach
abort() { echo "isolate-setup-failed: $1" >&2; exit 1; }   # BLOCK 2: explicit guard on each security-critical step
cleanup() {
  ip netns pids "$NS" 2>/dev/null | xargs -r kill -9 2>/dev/null || true
  ip netns del "$NS" 2>/dev/null || true
  rmdir "$CG" 2>/dev/null || true
  rm -rf "$WORK" "$NGXDIR" 2>/dev/null || true
}
trap cleanup EXIT
# 1. tmpfs copy in (D2 — no /mnt/c access from the guest process)
mkdir -p "$WORK" || abort workdir; cp -r "$SKILL_WSL/." "$WORK/" || abort copy
# 2. cgroups v2 caps as root (the enforced boundary the spike lacked). Values via WSLENV env.
mkdir -p "$CG" || abort cgroup
echo "$MEM_MAX"  > "$CG/memory.max" || abort memory.max   # bytes = memory_mb*1024*1024
echo "$CPU_MAX"  > "$CG/cpu.max"    || abort cpu.max       # "<quota> <period>", e.g. "100000 100000" = 100%
echo "$PIDS_MAX" > "$CG/pids.max"   || abort pids.max
# 3. de-privilege ONLY the tmpfs (capability code). The nginx-config dir stays root-owned (BLOCK 4) so the
#    capability can never unlink/replace its own firewall config.
chown -R "$UNTRUSTED_UID:$UNTRUSTED_UID" "$WORK" || abort chown
# 4. netns: empty allowlist => pure no-network (lo only); non-empty => nginx SNI/Host allowlist
#    (nginx stream ssl_preread for HTTPS-by-SNI + http $host map for HTTP; REDIRECT, not TPROXY —
#     xt_TPROXY is often absent in the WSL2 kernel and proxy_pass re-resolves by name so CDN IP
#     rotation is moot. tinyproxy CANNOT SNI-filter transparent HTTPS — see ADR-036.)
ip netns add "$NS" || abort netns
ip -n "$NS" link set lo up || abort lo
ip netns exec "$NS" sysctl -qw net.ipv6.conf.all.disable_ipv6=1 || abort ipv6      # FLAG 5: no unfiltered v6 egress
ip netns exec "$NS" sysctl -qw net.ipv6.conf.default.disable_ipv6=1 || true
if [ -n "$EGRESS_CSV" ]; then
  mkdir -p "$NGXDIR" || abort ngxdir
  chmod 700 "$NGXDIR" || abort ngxdir-perm   # note: explicit, not umask-dependent
  # BLOCK (reopened FLAG 7): re-validate each domain BEFORE templating into nginx.conf (the egress-control
  # artifact). Split on comma with noglob so a `*`/`?`/`[` token cannot glob-expand to filenames; match the
  # WHOLE string with bash `=~` (NOT per-line `grep`, which would pass "ok.com\n<injected-directive>"); and
  # explicitly reject any embedded newline/CR as defense-in-depth. policy-wiring also pre-validates.
  RE='^[a-zA-Z0-9]([a-zA-Z0-9-]{0,62}\.)+[a-zA-Z]{2,63}$'
  set -f                                        # noglob for the split
  IFS=',' read -ra _domains <<< "$EGRESS_CSV"
  set +f
  ALLOWED=()
  for d in "${_domains[@]}"; do
    [ -z "$d" ] && continue
    case "$d" in *$'\n'*|*$'\r'*) abort "newline-in-domain" ;; esac   # reject multi-line values
    [[ "$d" =~ $RE ]] || abort "bad-domain:$d"                        # whole-string match
    ALLOWED+=("$d")
  done
  [ "${#ALLOWED[@]}" -gt 0 ] || abort no-valid-domains
  # BLOCK 3: local resolver in-ns so the capability's DNS has ONE legal destination. It resolves every name
  # to a dummy IP — content is irrelevant because REDIRECT catches the TCP connect by SNI/Host, not by the
  # resolved IP; nginx re-resolves the real name upstream. resolv.conf (nameserver $DNS_STUB) is bind-mounted
  # into the capability's private mount ns in step 5. --conf-file=/dev/null ignores any ambient dnsmasq.conf;
  # the startup is VERIFIED (backgrounding always returns success, so `& disown || abort` was dead code).
  ip netns exec "$NS" dnsmasq --keep-in-foreground --conf-file=/dev/null --no-resolv --no-hosts \
    --listen-address="$DNS_STUB" --bind-interfaces --port=53 --address="/#/$DNS_STUB" &
  DNSPID=$!; disown; sleep 0.2; kill -0 "$DNSPID" 2>/dev/null || abort dnsmasq   # verify it actually came up
  printf 'nameserver %s\n' "$DNS_STUB" > "$NGXDIR/resolv.conf" || abort resolvconf
  # Generate "$NGXDIR/nginx.conf" (root-owned) as LITERAL CODE — one map entry per validated domain. The
  # stream{} block SNI-allowlists HTTPS; the http{} block Host-allowlists plain HTTP; both default-deny.
  {
    printf 'user www-data;\nworker_processes 1;\npid %s/nginx.pid;\n' "$NGXDIR"
    printf 'events { worker_connections 128; }\n'
    printf 'stream {\n  resolver %s;\n  map $ssl_preread_server_name $ups {\n    default "";\n' "$DNS_STUB"
    for d in "${ALLOWED[@]}"; do printf '    "%s" "%s:443";\n' "$d" "$d"; done   # $d already regex-validated
    printf '  }\n  server {\n    listen %s;\n    ssl_preread on;\n    proxy_pass $ups;\n' "$NGX_HTTPS"
    printf '    proxy_connect_timeout 5s;\n  }\n}\n'
    printf 'http {\n  resolver %s;\n  map $host $ok {\n    default 0;\n' "$DNS_STUB"
    for d in "${ALLOWED[@]}"; do printf '    "%s" 1;\n' "$d"; done
    printf '  }\n  server {\n    listen %s;\n    location / {\n' "$NGX_HTTP"
    printf '      if ($ok = 0) { return 444; }\n      proxy_pass http://$host;\n    }\n  }\n}\n'
  } > "$NGXDIR/nginx.conf" || abort nginx-conf
  ip netns exec "$NS" nginx -c "$NGXDIR/nginx.conf" || abort nginx
  NSX="ip netns exec $NS iptables"
  $NSX -t nat -A OUTPUT -m owner --uid-owner "$NGINX_UID" -j RETURN || abort nat-nginx
  $NSX -t nat -A OUTPUT -p tcp --dport 443 -m owner --uid-owner "$UNTRUSTED_UID" -j REDIRECT --to-ports "$NGX_HTTPS" || abort nat-443
  $NSX -t nat -A OUTPUT -p tcp --dport 80  -m owner --uid-owner "$UNTRUSTED_UID" -j REDIRECT --to-ports "$NGX_HTTP" || abort nat-80
  $NSX -A OUTPUT -m owner --uid-owner "$NGINX_UID" -j ACCEPT || abort acc-nginx      # nginx reaches the internet
  $NSX -A OUTPUT -o lo -j ACCEPT || abort acc-lo
  # BLOCK 3: DNS allowed ONLY to the pinned local stub; all other DNS (any other nameserver, TXT-exfil) DROPPED.
  $NSX -A OUTPUT -p udp --dport 53 -d "$DNS_STUB" -m owner --uid-owner "$UNTRUSTED_UID" -j ACCEPT || abort dns-udp-ok
  $NSX -A OUTPUT -p tcp --dport 53 -d "$DNS_STUB" -m owner --uid-owner "$UNTRUSTED_UID" -j ACCEPT || abort dns-tcp-ok
  $NSX -A OUTPUT -p udp --dport 53 -m owner --uid-owner "$UNTRUSTED_UID" -j DROP || abort dns-udp-drop
  $NSX -A OUTPUT -p tcp --dport 53 -m owner --uid-owner "$UNTRUSTED_UID" -j DROP || abort dns-tcp-drop
  $NSX -A OUTPUT -p tcp -m multiport --dports "$NGX_HTTPS,$NGX_HTTP" -m owner --uid-owner "$UNTRUSTED_UID" -j ACCEPT || abort acc-proxy
  $NSX -A OUTPUT -m owner --uid-owner "$UNTRUSTED_UID" -j DROP || abort default-deny   # default-deny (any proto/port)
fi
# 5. run command in netns + a PRIVATE mount+pid ns (BLOCK 1), DE-PRIVILEGED (non-root UID, all caps dropped),
#    cgroup + ulimit backstop, cwd=tmpfs. As root inside the mount ns: make mounts private, MASK the Windows
#    drives (tmpfs over /mnt — no /mnt/c host-filesystem access), bind the pinned resolv.conf, join the cgroup,
#    set ulimit; THEN setpriv drops to the untrusted UID for exec (so the capability never holds CAP_NET_ADMIN
#    /root and cannot `iptables -F` its way out or reach /mnt/c).
# The untrusted command is ALLOWED to exit non-zero (a blocked fetch / failing test is a normal,
# expected outcome we capture deliberately). Disable -e for JUST this capture so a non-zero child
# does not abort the outer script before we emit the length-prefixed output run_isolated parses.
# NOTE the inner `set -euo pipefail` (mount/proc/cgroup setup) still fails closed INSIDE the ns —
# any setup failure there makes the inner bash exit non-zero, which surfaces as STATUS!=0 here.
set +e
OUT=$(ip netns exec "$NS" unshare --mount --pid --fork bash -c '
  set -euo pipefail
  mount --make-rprivate /                                     # fail-closed: if this fails, abort (set -e) —
                                                              # never let the /mnt tmpfs propagate host-wide
  mount -t tmpfs none /mnt                                    # BLOCK 1: Windows drives gone inside the ns
  mount -t proc proc /proc                                    # FLAG: fresh /proc for the new pid ns (no host PIDs)
  [ -f "'"$NGXDIR"'/resolv.conf" ] && mount --bind "'"$NGXDIR"'/resolv.conf" /etc/resolv.conf || true
  echo $$ > "'"$CG"'/cgroup.procs"
  ulimit -t "'"$ULIMIT_T"'"
  cd "'"$WORK"'"
  exec setpriv --reuid="'"$UNTRUSTED_UID"'" --regid="'"$UNTRUSTED_UID"'" --clear-groups \
       --inh-caps=-all --bounding-set=-all -- "$@"' _ "$@" 2>&1)
STATUS=$?
set -e
printf '%s\n%s' "${#OUT}" "${OUT:0:4000}"   # first line = original length; run_isolated derives `truncated`
exit "$STATUS"
```

### C3 — shared helper (exported; enabler-fetch-sandbox imports, does NOT modify)
```python
class SandboxCaps(BaseModel):
    memory_mb: int = 512
    cpu_pct: int = 100
    pids_max: int = 128
    timeout_s: float = 60.0

async def run_isolated(skill_dir: Path, *, egress_domains: list[str], caps: SandboxCaps,
                       command: list[str], timeout_s: float) -> tuple[int, str, bool]:
    """wslpath-convert skill_dir -> wsl.exe -u root -- bash -s -- <path> <egress_csv> <run_id> <command...>.
    FLAG 6: `run_id` is generated HERE via `uuid.uuid4().hex` — it is NEVER derived from skill name, caller
    input, or policy content (it is interpolated into $WORK/$CG/$NS/$NGXDIR paths, so caller-controlled input
    would be a path-injection vector). egress_csv is `",".join(egress_domains)`; domains are re-validated
    guest-side (FLAG 7).
    Exports caps to the guest via WSLENV (MEM_MAX/CPU_MAX/PIDS_MAX/ULIMIT_T). Feeds _ISOLATE_SCRIPT on
    stdin. asyncio.wait_for(timeout_s); on TimeoutError kill + return (124, 'sandbox timeout exceeded', False).
    Returns (exit_code, output, truncated). The guest emits `<original_len>\\n<output[:4000]>`; run_isolated
    splits the first line to set `truncated = original_len > 4000` — a RELIABLE flag, not a
    `len(output) >= 4000` heuristic (which false-positives on an exactly-4000-char clean result).
    Honors the passed `egress_domains` arg directly (never re-reads a staging policy file), so the
    runtime FetchSandbox path can pass egress explicitly."""
```
`Wsl2SandboxRunner.run_tests(skill_dir)` reads `sandbox_policy.json` (C1) → `run_isolated(..., command=["python3","-m","pytest","tests","-q"])` → `VerifyResult(passed=code==0, output=out)` (drops the `truncated` bool — `VerifyResult` has no such field). Absent policy → `egress_domains=[]` + default `SandboxCaps()`. **`Wsl2SandboxRunner` sets `hardened = True` (class attribute)** so the forge guard-relax (enabler-sandbox-policy-wiring) detects the hardened boundary via `getattr(sandbox, "hardened", False)`; `SubprocessSandbox` must NOT define `hardened`.

`default_sandbox() -> SandboxRunner`: **synchronous** probe (create_app is sync) via `subprocess.run(["wsl.exe","-u","root","--","bash","-c","command -v ip iptables nginx dnsmasq setpriv unshare >/dev/null && nginx -V 2>&1 | grep -q ssl_preread && id -u artemis-cap >/dev/null && test -w /sys/fs/cgroup/cgroup.procs"], timeout=5)`; exit 0 → `Wsl2SandboxRunner()`, any error/non-zero/`FileNotFoundError` → `SubprocessSandbox()`.

## Wave plan
Wave 1: [Task 1] | Wave 2: [Task 2, Task 3]

## Permissions

The following actions will run autonomously during build.
Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Create | src/artemis/capabilities/sandbox_wsl2.py, tests/capabilities/__init__.py, tests/capabilities/test_sandbox_wsl2.py |
| Modify | src/artemis/api/app.py |
| Delete | (none) |

### Commands
| Command | Purpose |
|---------|---------|
| `wsl.exe -d Ubuntu -- sudo apt-get update` | one-time provisioning |
| `wsl.exe -d Ubuntu -- sudo apt-get install -y iptables nginx libnginx-mod-stream dnsmasq util-linux` | one-time provisioning (nginx + stream/ssl_preread, dnsmasq stub resolver, setpriv/unshare) over the spike's iptables |
| `wsl.exe -d Ubuntu -- bash -lc 'nginx -V 2>&1 \| grep -o with-stream_ssl_preread_module'` | verify the SNI module is present (else the HTTPS allowlist can't work) |
| `wsl.exe -d Ubuntu -- sudo useradd -r -u 4000 artemis-cap` | one-time: the dedicated de-privileged UID the capability runs as |
| `wsl.exe -d Ubuntu -- bash -lc 'grep -q systemd=true /etc/wsl.conf'` | verify `/etc/wsl.conf` `systemd=true` (set + `wsl --shutdown` if absent) |
| `uv run mypy` | full-project strict type check |
| `uv run pytest -q` | full-project test run |
| `uv run ruff check` | lint |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | src/artemis/capabilities/sandbox_wsl2.py src/artemis/api/app.py tests/capabilities/__init__.py tests/capabilities/test_sandbox_wsl2.py |
| `git commit` | "feat: hardened root-backed WSL2 SandboxRunner (transparent-proxy egress + cgroups-v2 caps)" |

### Environment Access
| Variable | Purpose |
|----------|---------|
| `WSLENV` | export cap env vars (MEM_MAX/CPU_MAX/PIDS_MAX/ULIMIT_T) into the WSL guest |

### Network
| Action | Purpose |
|--------|---------|
| `apt-get install iptables nginx libnginx-mod-stream dnsmasq util-linux` | one-time WSL provisioning |

## Specialist Context
### Security
Dispatched apex-spec-reviewer (security) pass required (untrusted-code execution boundary). Boundary invariants (ADR-036): **untrusted capability runs de-privileged** (dedicated non-root UID, all caps dropped — cannot `iptables -F`) in a **private mount+pid namespace** with `/mnt` (Windows drives) masked by tmpfs (BLOCK 1); **setup fails closed** — `set -euo pipefail` + per-step `abort` guards, so isolation failure never falls through to running the command (BLOCK 2); egress default-deny via nginx SNI/Host allowlist with `-m owner --uid-owner` matching (nginx on its own UID); **DNS pinned to a single in-ns stub resolver**, all other DNS dropped (no DNS-exfil channel — BLOCK 3); nginx firewall config in a **root-owned** dir never chowned to the capability (BLOCK 4); **IPv6 disabled in the netns** (v4-only rules — FLAG 5); `run_id` is uuid-generated, never caller-derived (FLAG 6); egress domains hostname-regex re-validated before templating (FLAG 7); non-allowlisted/any-non-TCP egress dropped; root used only for setup and confined to the WSL2 guest VM (not the Windows host); tmpfs-only data path; enforced cgroups-v2 caps.

### Performance
(none)

### Accessibility
(none — no frontend change)

## Documentation
| Doc type | File | Action |
|----------|------|--------|
| Inline | src/artemis/capabilities/sandbox_wsl2.py | Docstrings on all exports; module docstring carries the full provisioning runbook |
| ADR | docs/technical/adr/ADR-036-hardened-wsl2-sandbox.md | Already written — link only, do not duplicate |

## Acceptance Criteria
- [ ] Provision: `wsl.exe -u root -- bash -c 'command -v ip iptables nginx && nginx -V 2>&1 | grep -q ssl_preread && id artemis-cap'` → verify: exits 0 (tools present, SNI module compiled in, untrusted UID exists)
- [ ] No-network default: `run_isolated(dir, egress_domains=[], ...)` on a capability that fetches a URL → verify: fetch fails (netns has lo only), exit code non-zero, output shows the network error
- [ ] nginx SNI allow-one: egress `["example.com"]`, capability GETs `https://example.com` → verify: succeeds (200)
- [ ] nginx SNI block-another: same run, capability GETs a non-allowlisted HTTPS domain → verify: connection closed/refused (nginx default-deny map)
- [ ] De-privilege / firewall-integrity: the capability runs as the non-root UID and cannot escape — a capability that runs `id` reports uid≠0, and one that attempts `iptables -F` (or a raw-socket egress to a non-allowlisted IP) → verify: the flush fails (no CAP_NET_ADMIN) AND a subsequent non-allowlisted fetch is still blocked
- [ ] Windows-drive mask (BLOCK 1): a capability that reads or writes `/mnt/c/...` (e.g. `open('/mnt/c/Users/...')`) → verify: fails (FileNotFoundError / empty tmpfs) — `/mnt` is masked inside the private mount ns
- [ ] Fail-closed setup (BLOCK 2): force a setup step to fail (e.g. inject an nginx-config error / a bad domain) → verify: the script exits non-zero via `abort` and the untrusted command NEVER runs (no capability stdout in the output)
- [ ] DNS-exfil blocked (BLOCK 3): a capability doing a DNS lookup against an external resolver (e.g. `8.8.8.8`) or a TXT-record query to a non-allowlisted nameserver → verify: blocked (only `127.0.0.1:53` reachable; all other UDP/TCP 53 dropped)
- [ ] IPv6 egress blocked (FLAG 5): a capability connecting to an IPv6 literal / AAAA target → verify: fails (IPv6 disabled in the netns)
- [ ] Domain-injection rejected (reopened FLAG 7): `run_isolated(..., egress_domains=["ok.com\n} server { proxy_pass evil:443;"])` (embedded newline) and a wildcard token `["*.com"]` → verify: the script `abort`s (`newline-in-domain` / `bad-domain`), nginx.conf is NOT written with the injected directive, and the command never runs
- [ ] /proc isolation (new pid ns): a capability listing `/proc` (e.g. `os.listdir('/proc')`) → verify: sees only its own pid ns (its own PID + a couple of helpers), NOT host PIDs / other sandbox run_ids
- [ ] dnsmasq-startup verified: force the stub resolver to fail to bind (e.g. port already held) → verify: the script `abort`s (`dnsmasq`) before running the command, rather than proceeding with no resolver
- [ ] cgroup memory cap kills over-allocation (the enforced cap the spike LACKED): caps `memory_mb=256`, capability allocates ~1 GB → verify: process is OOM-killed / non-zero exit (contrast spike check 5 where the 1 GB alloc succeeded)
- [ ] tmpfs cleanup: after any run → verify: `wsl.exe -- bash -lc 'ls /tmp/artemis-* 2>/dev/null | wc -l'` prints `0` and the cgroup dir is gone
- [ ] `hardened` flag: `Wsl2SandboxRunner().hardened is True` and `getattr(SubprocessSandbox(), "hardened", False) is False` → verify: a unit test asserts both (the contract enabler-sandbox-policy-wiring's guard-relax depends on)
- [ ] Reliable truncation flag: `run_isolated` on a capability printing >4000 chars → verify: returns `truncated is True`; a ≤4000-char clean run returns `truncated is False`
- [ ] Dev-fallback probe: `default_sandbox()` on a host with no/unprovisioned WSL → verify: returns a `SubprocessSandbox` instance (no exception raised)
- [ ] Pure-logic units (no WSL): policy parse, wslpath convert (monkeypatched), caps defaults, probe fallback → verify: `uv run pytest -q tests/capabilities/test_sandbox_wsl2.py` green with live tests SKIPPED
- [ ] Host verify recipe → verify: `uv run mypy` (full, strict) + `uv run pytest -q` + `uv run ruff check` all pass

## Progress
_(Coding mode writes here — do not edit manually)_
