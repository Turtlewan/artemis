# ADR-036 — Hardened, root-backed WSL2 capability sandbox (cgroups + transparent proxy)

- **Status:** **Accepted** — owner + planning, 2026-07-01.
- **Date:** 2026-07-01
- **Deciders:** owner + planning
- **Refines:** ADR-035 decision 7 (isolation runner dev→prod) and decision 2 (fetch boundary = Option B).
- **Design basis:** `poc/wsl2_sandbox/README.md` (the enabler-#1 spike results, 2026-07-01) + `docs/findings/enabler-wsl2-isolation-2026-07-01.md`.

## Context

Enabler #1 (the WSL2 spike) proved isolation is feasible **unprivileged** (netns + pid-ns + mount-ns
+ tmpfs data path + `ulimit` CPU-time cap, no root). But it also proved two ways the unprivileged
model is **not a hard boundary**:

1. **Egress is name-only and IP-bypassable.** The DNS-sinkhole allowlist restricts DNS resolution
   only; untrusted code that dials a hard-coded IP or ships its own resolver/DoH walks straight out.
2. **Resource caps are unenforced unprivileged.** `systemd-run --scope -p MemoryMax` *succeeds* but is
   silently ignored — the memory controller isn't delegated to the unprivileged user (verified: a 1 GB
   allocation under `MemoryMax=256M` succeeded). Only `ulimit -t`/`-v` bit, and `ulimit` is escapable.

Enabler #2 is meant to be **the real gate that lets externally-authored capability code be trusted**
(status.md: "Security gate, not optional"). Shipping the spike's soft model as the production boundary
would defeat that purpose.

## Decision

The production capability sandbox runs **root-backed inside WSL2** (passwordless `wsl.exe -u root`,
confirmed available on the dev host), to obtain a genuine boundary:

| Concern | Hardened choice | Rejected alternative |
|---|---|---|
| **Egress** | **Transparent SNI/Host allowlist via nginx**: `stream{}` + `ssl_preread` maps `$ssl_preread_server_name` (HTTPS by SNI) + `http{}` `$host` map (plain HTTP), fronted by iptables **REDIRECT** in `nat OUTPUT`; default-deny (empty map → close), `proxy_pass` re-resolves by name so rotating CDN/cloud IPs don't matter | tinyproxy (**cannot** SNI-filter transparent HTTPS — only sees the original-dst IP); DNS-sinkhole (IP-bypassable — spike); raw iptables IP-allowlist (breaks on rotating IPs); TPROXY (`xt_TPROXY` often absent in the WSL2 kernel; REDIRECT + re-resolve makes it unnecessary) |
| **Resource caps** | **cgroups v2 as root** (`memory.max` / `cpu.max` / `pids.max`) + `ulimit -t` wall backstop | unprivileged `systemd-run --scope` (caps silently unenforced — spike) |
| **Setup invocation** | passwordless `wsl.exe -u root` sets up netns + iptables + nginx + cgroup | unprivileged `unshare` (can't do REDIRECT firewall or enforced cgroups) |
| **Untrusted process privilege** | **runs de-privileged** — the capability itself executes under a dedicated non-root UID (e.g. 4000) with `CAP_NET_ADMIN`/`CAP_NET_RAW` dropped; nginx runs under its own distinct UID (33) | running the capability as root (it could `iptables -F` and bypass the egress firewall — the whole boundary is void) |
| **Data path** | tmpfs copy in, text/bytes out (unchanged from spike D2) | `/mnt/c` direct (host-writable — isolation hole) |

**"Root-backed" = root-privileged *setup*, not root-executed *capability*.** Root (via
`wsl.exe -u root`) builds the netns/firewall/cgroup and starts nginx; the untrusted capability then
runs under a dedicated non-root UID inside that cage. This is load-bearing: the iptables egress
allowlist uses `-m owner --uid-owner` matching (untrusted UID redirected/dropped, nginx UID exempt),
which only holds if the untrusted code cannot itself edit iptables — i.e. must not be root and must
not hold `CAP_NET_ADMIN`.

**Blast-surface acknowledgement:** the *setup* subprocess runs as root inside the WSL2 VM — a larger
surface than the unprivileged model. Accepted because (a) it is confined to the WSL2 guest VM (not the
Windows host), (b) it is the only way to get an enforced egress + memory boundary, (c) the untrusted
code never runs with that privilege (de-privileged UID above), and (d) the whole point is to contain
code we do **not** trust — a soft boundary is worse than an honestly-scoped one.

**Residual unknowns settled only by the runner spec's live WSL acceptance checks** (not blockers —
the same live-verify discipline that drove the spike): whether the installed WSL2 kernel loads
`nf_nat`/`REDIRECT` inside a hand-made netns; the netns DNS path for nginx's `resolver`; and
WSL `MASQUERADE` regressions on some kernel builds. `nginx -V | grep ssl_preread` must confirm the
stream SNI module is present in the Ubuntu package.

**Seam unchanged.** The runner plugs in behind the existing one-method `SandboxRunner` protocol
(`run_tests(skill_dir) -> VerifyResult`); the per-capability egress allowlist + caps are delivered via
a `sandbox_policy.json` file the forge writes into the staging dir (finding Path 1 — no protocol
change). `SubprocessSandbox` remains the unprivileged dev fallback when WSL2 is absent.

## Consequences

- Provisioning gains `nginx` + `libnginx-mod-stream` (+ `iptables`, already installed for the spike);
  `.wslconfig` `networkingMode=nat` and `/etc/wsl.conf` `systemd=true` are the assumed WSL2 config. A
  dedicated non-root UID for untrusted runs and a distinct nginx UID are set up at provisioning.
- The AST import-guard (`scan_for_unsafe_imports`) can be **relaxed**: a capability that declares an
  `egress_domains` allowlist may import network modules and run in the hardened sandbox (the sandbox,
  not the guard, is now the boundary). Capabilities with network imports but **no** declared egress,
  or when the hardened sandbox is unavailable, stay blocked.
- **macOS parity** (Lima, ADR-035 decision 7) reuses the same isolate script; HW-gated to the Mac
  Mini and out of scope until then.
- Implemented as three sequenced specs (split rule): `enabler-wsl2-runner` → `enabler-sandbox-policy-wiring` → `enabler-fetch-sandbox`.

## Alternatives considered

- **Ship the spike's unprivileged model as production** — *rejected*: not a hard boundary (see Context).
- **iptables IP-allowlist instead of a proxy** — *rejected*: fragile on rotating CDN/cloud IPs (finding B1).
- **tinyproxy for the transparent proxy** — *rejected*: cannot SNI-filter transparent HTTPS (sees only the original-dst IP); nginx `ssl_preread` is the SNI-aware replacement (research 2026-07-01).
- **TPROXY instead of REDIRECT** — *rejected*: `xt_TPROXY` is often absent in the WSL2 kernel, and REDIRECT + re-resolve-by-name removes the need to preserve the original dst IP.
- **Run the untrusted capability as root** — *rejected*: it could `iptables -F` and void the egress firewall; the capability runs de-privileged.
- **Stay unprivileged, accept soft caps** — *rejected*: the feature's purpose is to trust untrusted code.
