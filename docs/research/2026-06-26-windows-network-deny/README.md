# Windows per-process outbound network-deny for the agent sandbox (Rung-2)

**Date:** 2026-06-26
**Context:** ADR-031 Rung-2 (`AGENT-rung2`). The agent sandbox confines a spawned child process with a
Windows restricted token + Job Object (FS/process/resource), but runs **network-ON**. To make the
`AuthorityGate` "no-network + workspace-confined ⇒ `IN_SANDBOX` ⇒ auto-run" classification *real*, we
need a kernel-enforced **outbound network deny** on the child. `AGENT-rung2.md` currently names
"WFP/SID outbound block keyed to the restricted-token's SID" as the mechanism, with a fail-closed
fallback to gate-everything if it can't be confirmed. This resolves the mechanism.
**Dev box:** Windows 11, 8 GB RAM, runs as a **normal (non-admin) user**, Ollama resident (~5-6 GB).
Final host = Mac later.

> **Headline:** the restricted-token model keeps the dev user's own SID, so a per-SID firewall/WFP
> rule can't tell the sandbox apart from the user — and every firewall/WFP route needs **admin**
> anyway. The mechanism that gives a **distinct SID + automatic kernel outbound block with NO admin**
> is **AppContainer launched without network capabilities**. Recommend AppContainer; it *replaces*
> the restricted-token layer (it is a stricter low-box token) and the Job Object still layers on top.

---

## 1. Mechanism options

### (a) AppContainer launched WITHOUT `internetClient` / `internetClientServer` / `privateNetworkClientServer`

**How it works.** An AppContainer process runs under a *low-box token* tagged with a unique
**package SID** plus a set of *capability SIDs*. Network access is capability-gated:
- `internetClient` = `S-1-15-3-1` — outbound client to internet addresses.
- `internetClientServer` = `S-1-15-3-2` — outbound + inbound internet.
- `privateNetworkClientServer` = `S-1-15-3-3` — RFC1918 / local-private ranges (Private interfaces).

If **none** of these capabilities are present, the Windows Defender Firewall service installs a
**"Block Outbound Default" filter at the `MICROSOFT_DEFENDER_SUBLAYER_WSH` sublayer** that blocks all
AppContainer outbound connections — this is a kernel TCP/IP-driver filter, evaluated per socket, that
terminates evaluation once matched. So omitting the capabilities **does** block sockets, and it is the
firewall/WFP doing the enforcement automatically (you add no rule yourself).

**What it blocks.** All outbound TCP/UDP to non-loopback addresses. **Loopback (127.0.0.1 /
localhost) is ALSO blocked by default** for AppContainers via an inbound/receive-layer `IsLoopback`
filter — same-package loopback and an explicit `Add-AppModelLoopbackException` (debug) are the only
exemptions. For a *deny-all* default this is exactly what we want (localhost is denied too). Note:
loopback blocks present as a **timeout**, not an immediate refusal.

**Launching an arbitrary console exe (not UWP) from Python.** Yes — this is the established
"AppContainer-as-sandbox" pattern (Chromium/Firefox/Edge use it for renderers; MalwareTech's
`AppContainerSandbox`, Privexec, blahcat all launch ordinary exes). Sequence:
1. `CreateAppContainerProfile(name, …)` → unique package SID (or `DeriveAppContainerSidFromAppContainerName` if it already exists). `userenv.dll`.
2. Build `SECURITY_CAPABILITIES { AppContainerSid, Capabilities=<empty for deny-all>, … }`.
3. `InitializeProcThreadAttributeList` + `UpdateProcThreadAttribute(PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES, &caps)` into a `STARTUPINFOEX`.
4. `CreateProcess(…, EXTENDED_STARTUPINFO_PRESENT, …, &startupinfoex, …)`.

**Reliability.** High and kernel-enforced — **but with one hard dependency: the Windows Defender
Firewall service (MPSSVC) must be running.** The AppContainer outbound block IS a firewall/WFP filter;
if a user disables the firewall, AppContainer network isolation disappears. (Default state on Win 11 =
running.) Treat "MPSSVC running" as a runtime precondition + back it with the network-deny self-test
(§5). Known weakness: an AppContainer can `CreateProcess` a *different* exe that already has an explicit
allow filter and ride it out (Project Zero bug #2207, child inherits higher-priority permit filters) —
mitigate by capping/limiting the process tree via the Job Object and not whitelisting random exes.

Python feasibility: `CreateAppContainerProfile` / `DeriveAppContainerSidFromAppContainerName` are **not
exposed by pywin32** (userenv.dll), and pywin32's `CreateProcess` doesn't cleanly drive the
`STARTUPINFOEX` attribute list — so this is a **ctypes** job (declare the structs + the four calls).
Non-trivial glue but well-trodden; C++/Python reference implementations exist.

### (b) Windows Filtering Platform (WFP) — per-AppID / per-SID outbound block filter

**How it works.** Add a filter at `FWPM_LAYER_ALE_AUTH_CONNECT_V4/V6` with action BLOCK, conditioned
on `FWPM_CONDITION_ALE_APP_ID` (the exe path) or `FWPM_CONDITION_ALE_USER_ID` (token user SID) or
`FWPM_CONDITION_ALE_PACKAGE_ID` (AppContainer package SID). The condition is evaluated against the
**token captured when the socket is created**, so a USER_ID/PACKAGE_ID block does match the spawning
process by its token. Filters can be transient (BFE session lifetime) or **persistent**
(`FWPM_FILTER_FLAG_PERSISTENT`).

**Admin.** **Required.** The Base Filtering Engine restricts WFP objects to administrators by default —
"nothing can be accessed by non-administrators"; `FwpmFilterAdd` must run elevated.

**Python feasibility.** Possible via ctypes against `fwpuclnt.dll` (no pywin32 coverage), but it's a
large, error-prone API surface (engine open, sublayer, filter conditions, blobs). Heavier than (a) or
(c) for the same outcome.

**Verdict:** this is the *engine underneath* (a) and (c). Driving it directly buys nothing over the
firewall cmdlets except complexity — and it still needs admin **and** a distinct SID to scope to.

### (c) Windows Firewall rule scoped to the restricted-token's user/SID (`New-NetFirewallRule -LocalUser` / `netsh`)

**Does an outbound block bound to a user SID stop that process's sockets?** **Yes — for a LOCAL user
SID, with no IPsec.** `-LocalUser` maps to `FWPM_CONDITION_ALE_USER_ID`: "only network packets …
coming from or going to a principal (SID) match this rule"; principals may be "services, users,
application containers, or any SID." The local token is captured at socket creation and access-checked
against the rule's SDDL — **no IPsec needed**. (This is the key distinction: `-RemoteUser` /
`-RemoteMachine` *do* require an IPsec rule to authenticate the *remote* identity; `-LocalUser` does
not.) `-LocalUser` wants an SDDL string, e.g. `O:LSD:(A;;CC;;;<SID>)`.

**Admin.** **Required** to add/modify a firewall rule (`New-NetFirewallRule`, `netsh advfirewall`).

**The fatal scoping problem for our model.** Our existing sandbox uses **`CreateRestrictedToken`,
which keeps the *same* user SID** (it only disables/restricts SIDs + strips privileges). A `-LocalUser`
rule keyed to that SID would therefore block **the dev user's own traffic**, not just the sandbox. To
scope a firewall rule to *only* the sandbox you need the child to run under a **distinct** SID, which
means either (i) a **dedicated local user account** (creating it needs admin; launching under it needs
`CreateProcessAsUser`, which needs the `SE_ASSIGNPRIMARYTOKEN`/`SE_INCREASE_QUOTA` privileges ≈ admin),
or (ii) an **AppContainer package SID** — at which point you're back to (a) and the rule is redundant
(AppContainers are blocked by default with no rule). **Cleanup/teardown:** a persistent rule must be
removed on teardown (`Remove-NetFirewallRule`) — an orphaned per-run rule is leakage; transient is
safer but still needs admin per run.

**Verdict:** technically works, but needs admin **and** a distinct SID it can't get cheaply under the
restricted-token model → non-starter on the non-admin dev box.

### (d) Other primitives

- **Per-process "deny-all" proxy** (set `HTTP(S)_PROXY` to a black-hole): trivial, no admin, but
  **advisory only** — a process can ignore env proxy and open raw sockets. Not an enforcement boundary;
  rejected as the security control (fine as defence-in-depth, not as the gate's basis).
- **Network namespaces / netns:** Windows has **no** Linux-style netns without a container/Hyper-V
  compartment. Network compartments exist only via the HNS/container stack (Windows containers /
  Hyper-V isolation) — ruled out on 8 GB (§3).
- **Disable the adapter / null-route:** host-global, not per-process — wrong granularity.

---

## 2. Admin / elevation

| Mechanism | Per-run admin? | One-time admin setup? |
|---|---|---|
| **(a) AppContainer, no net caps** | **No** | **No** — `CreateAppContainerProfile` is per-user and works non-elevated (Chromium/Edge launch AppContainer sandboxes from non-elevated processes); the outbound default-block is built into Windows. |
| (b) WFP direct | **Yes** (BFE is admin-only) | — |
| (c) Firewall `-LocalUser` rule | Yes (rule add) **and** admin to mint a distinct SID (separate user) | A *static* rule could be pre-seeded once by admin, but it still needs a per-run distinct SID it can't get without admin |
| (d) proxy env | No (but not an enforcement boundary) | No |

**Only (a) needs no admin at all** — neither one-time nor per-run. That is decisive for a box that
runs as a normal user and treats per-command elevation as a non-starter.

---

## 3. Footprint / feasibility on 8 GB alongside Ollama

- **(a) AppContainer:** native NT kernel feature, **zero resident footprint** — just the child process.
  No VM, no daemon. ✔ coexists with Ollama.
- **(c) firewall rule:** also near-zero footprint (MPSSVC already runs), but blocked on admin/SID.
- **Ruled out (too heavy):** Docker Desktop / WSL2 / Windows containers / Hyper-V network compartments
  — these are the only way to get true netns on Windows, and each wants 1.5-3 GB+ resident, mutually
  exclusive with a resident Ollama on 8 GB (consistent with the OpenHands-Windows research verdict).

---

## 4. Combining with restricted-token + Job Object

**AppContainer does NOT layer on top of the restricted token — it replaces that layer.** Both are
token-level confinement; the AppContainer low-box token *is* a more-restrictive token (unique package
SID, capability-gated, integrity-capped). You launch the child **as an AppContainer process instead of
as a restricted-token process** for the token layer. The **Job Object still layers on top unchanged**
(resource caps / process-tree kill / `KILL_ON_JOB_CLOSE`) — Job Objects compose fine with AppContainer
processes, and the tree-cap also mitigates the bug-#2207 spawn-a-permitted-exe bypass.

**Cost of the swap vs the restricted token:** AppContainer adds a real **kernel FS boundary** — the
child can't touch files unless the **package SID is granted ACL access**. So `workspace_root` (and any
needed temp dir) must get an explicit ACE for the package SID (`SetEntriesInAcl` / `icacls
…/grant *<package-sid>:(OI)(CI)M`). This is *stronger* than the Python-level `resolve_within`
confinement the rungs already do, but it's extra setup the restricted-token path didn't need. Net: the
`Sandbox` seam stays identical; `WindowsRestrictedSandbox` becomes (or is joined by)
`WindowsAppContainerSandbox` = AppContainer token + ACL-grant workspace + Job Object.

---

## 5. Verifiability — automated "cannot open an outbound socket" test

Make the acceptance criterion a real runtime check, run as part of the sandbox self-test:

1. **Precondition gate:** assert the Windows Defender Firewall service (MPSSVC) is running
   (`sc query mpssvc` / `Get-Service mpssvc` STATE = RUNNING). If not running ⇒ the AppContainer block
   is void ⇒ **fail closed** (disable `IN_SANDBOX` auto-run, gate everything) — exactly the
   owner-flagged fallback in `AGENT-rung2.md`.
2. **Outbound deny:** launch a child *in the sandbox* that attempts an outbound connect and assert it
   FAILS (non-zero / exception / timeout). Self-contained payload (no test server needed):
   ```python
   # run INSIDE the sandbox; must NOT succeed
   import socket, sys
   try:
       socket.create_connection(("1.1.1.1", 80), timeout=5)   # routable public IP, no DNS dependency
       sys.exit(0)   # connected -> deny FAILED
   except OSError:
       sys.exit(42)  # blocked -> deny works
   ```
   Assert the child's exit code is the "blocked" sentinel (42), not 0.
3. **Loopback deny (optional, documents the default):** same payload against `("127.0.0.1", <port>)`
   with a listener in the parent — expect timeout/failure (AppContainer loopback is blocked by default).
4. **Positive control:** the SAME payload run OUTSIDE the sandbox connects (exit 0), proving the test
   discriminates rather than always-fails.

Use a routable literal IP (e.g. `1.1.1.1:80` or `8.8.8.8:53`) so the test doesn't depend on DNS or a
live external service beyond basic reachability; or stand up a localhost listener and rely on the
loopback-block for a fully offline-deterministic assertion.

---

## 6. Mac parity (one line)

On the Mac the same `Sandbox` seam swaps to a Docker/remote workspace launched **`--network none`** (or
a container with no network capability); `allow_network=None` ⇒ no-network container, a scoped
`allow_network` set ⇒ a constrained egress policy — so deny-all-by-default maps cleanly across both
hosts behind the one seam.

---

## Bottom-line recommendation

**Use an AppContainer launched with NO network capabilities** as the Rung-2 network-deny mechanism on
the Windows dev box.

- **Why:** it is the **only** option that gives a *distinct SID + automatic, kernel-enforced outbound
  block (loopback included) with NO admin* — neither one-time nor per-run. Every WFP/firewall route
  needs admin *and* a distinct SID that the current `CreateRestrictedToken` model (same user SID) can't
  provide without admin. AppContainer solves both at once and stays within the native, zero-footprint
  constraint on 8 GB alongside Ollama.
- **Key trade-off:** AppContainer **replaces the restricted-token layer** (it's a stricter low-box
  token; the Job Object still layers on top) and it imposes a **kernel FS boundary** — `workspace_root`
  must be ACL-granted to the package SID. That's more setup than the restricted token, but it buys a
  stronger FS boundary as a bonus. The `Sandbox` seam interface is unchanged.
- **One-time admin setup needed?** **No.** The only runtime dependency is that the **Windows Defender
  Firewall service (MPSSVC) is running** (default-on). Enforce it as a precondition + the §5 network-deny
  self-test; if MPSSVC is down, **fail closed** to gate-everything (the spec's existing fallback).
- **Spec deltas (most load-bearing):** (1) the `AGENT-rung2.md` "WFP/SID rule keyed to the
  restricted-token's SID" mechanism should change to "**AppContainer with no network capabilities**"
  — the restricted-token-SID firewall idea doesn't scope (same SID) and needs admin; (2) the token
  layer for the network-deny variant is AppContainer (ctypes against `userenv.dll`/`kernel32`, *not*
  pywin32), Job Object unchanged; (3) `workspace_root` needs an ACL grant to the package SID; (4) the
  acceptance test must include the MPSSVC-running precondition + the in-sandbox outbound-connect-FAILS
  assertion, fail-closed if either is unmet.

---

### Sources
- AppContainer network access (capabilities, default-block sublayer, loopback, MPSSVC/WFP/BFE pipeline, bug #2207) — Google Project Zero: https://projectzero.google/2021/08/understanding-network-access-windows-app.html
- Launch an AppContainer (SECURITY_CAPABILITIES, STARTUPINFOEX, CreateProcess) — Microsoft Learn: https://learn.microsoft.com/en-us/windows/win32/secauthz/implementing-an-appcontainer
- AppContainer for legacy (non-UWP) applications — Microsoft Learn: https://learn.microsoft.com/en-us/windows/win32/secauthz/appcontainer-for-legacy-applications-
- CreateAppContainerProfile (per-user profile) — Microsoft Learn: https://learn.microsoft.com/en-us/windows/win32/api/userenv/nf-userenv-createappcontainerprofile
- Cheap sandboxing with AppContainers (practical non-UWP exe launch) — blahcat: https://blahcat.github.io/2020-12-29-cheap-sandboxing-with-appcontainers/
- Fun with AppContainers / Intro to WFP — Pavel Yosifovich: https://scorpiosoftware.net/2019/01/15/fun-with-appcontainers/ · https://scorpiosoftware.net/2022/12/25/introduction-to-the-windows-filtering-platform/
- AppContainerSandbox reference (CreateProcess into AppContainer) — MalwareTech: https://github.com/MalwareTech/AppContainerSandbox/blob/master/ContainerCreate.cpp
- WFP basic operation / persistent filters (FWPM_FILTER_FLAG_PERSISTENT, ALE layers, BFE admin-only) — Microsoft Learn: https://learn.microsoft.com/en-us/windows/win32/fwp/basic-operation · Quarkslab: https://blog.quarkslab.com/windows-filtering-platform-persistent-state-under-the-hood.html
- New-NetFirewallRule (-LocalUser = FWPM_CONDITION_ALE_USER_ID; LocalUser vs Remote* IPsec semantics; SDDL) — Microsoft Learn: https://learn.microsoft.com/en-us/powershell/module/netsecurity/new-netfirewallrule
- CreateRestrictedToken / CreateProcessAsUser (pywin32) — Tim Golden pywin32 docs: https://timgolden.me.uk/pywin32-docs/win32security.html · https://timgolden.me.uk/pywin32-docs/win32process__CreateProcessAsUser_meth.html
</content>
</invoke>
