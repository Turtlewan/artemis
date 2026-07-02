---
spec: js-fetcher-userns-spike
status: done
kind: spike
outcome: PASS — Chrome userns+seccomp sandbox engages nested in the isolate, zero isolate change. Findings: poc/wsl2_browser_userns/README.md
autonomy_level: L5
---

# Spike: can Chrome's own sandbox run nested inside the WSL2 isolate?

> **RESOLVED 2026-07-03 — PASS.** Ran on this host: WITHOUT `--no-sandbox`, chrome-headless-shell
> renders full pages (exit 0, 1.27 s, 163 MB) AND engages its seccomp-bpf renderer sandbox
> (`/proc` `Seccomp: 2` on renderers vs `Seccomp: 0` with `--no-sandbox`) under the existing
> `setpriv --bounding-set=-all` chain — no isolate change. `js-rendering-fetcher` drops
> `--no-sandbox`; ADR-040 records the sandbox as retained. Full findings:
> `poc/wsl2_browser_userns/README.md`. (Brief retained for the audit trail.)

**Identity:** De-risking spike gating `js-rendering-fetcher` — determine whether `chrome-headless-shell` can render WITH its own (unprivileged user-namespace) sandbox inside the ADR-036 isolate, so we avoid `--no-sandbox`. Owner decision 2026-07-03 (apex-security BLOCK 2).

## Question
The `poc/wsl2_browser/` spike ran Chrome with `--no-sandbox` because "there's no setuid sandbox helper under nested unshare." That disables Chrome's per-renderer seccomp-bpf syscall filter — the primary defense against a renderer RCE from adversarial JS/WASM. **Can Chrome instead use its unprivileged-user-namespace (userns) sandbox nested inside the isolate's `unshare --mount --pid` + `setpriv --bounding-set=-all` chain?** If yes at acceptable cost to the isolation model, the fetcher keeps Chrome's sandbox; if no, we fall back to `--no-sandbox` + documented owner acceptance.

## What to test (on the provisioned WSL2 Ubuntu host)
Work in a throwaway `poc/wsl2_browser_userns/` (copy `poc/wsl2_browser/isolate.sh` + `capability/render.py`); do NOT edit `src/`.

1. **Baseline userns availability:** `sysctl kernel.unprivileged_userns_clone` and `/proc/sys/user/max_user_namespaces`; note kernel (POC host was 6.6.87). Confirm unprivileged userns clone is permitted on this WSL2 kernel at all.
2. **Nested-userns probe (no chrome):** inside the isolate's exact chain (netns + `unshare --mount --pid --fork` + `setpriv --reuid=4000 --bounding-set=-all --inh-caps=-all`), run a tiny C/`unshare -U` probe that attempts `CLONE_NEWUSER`. Does a NEW user namespace clone succeed after all caps are stripped and one userns level is already entered? (This is the crux — Chrome's zygote needs exactly this.)
3. **Chrome-with-sandbox:** run `render.py` variant WITHOUT `--no-sandbox`/`--disable-setuid-sandbox` (keep the rest of the minimal flag set) against `https://en.wikipedia.org/wiki/Python_(programming_language)` with allowlist `en.wikipedia.org`. Capture: does it launch? render? extract ≥4000 chars? within the ~2s/60s budget? Try the permutations: (a) as-is; (b) with `--disable-setuid-sandbox` only (userns path); (c) note any capability/sysctl the isolate would have to grant and whether that weakens ADR-036.
4. **Cost accounting:** for any config that works, state exactly what the isolate had to change vs the current `setpriv --bounding-set=-all` de-priv (e.g. retain a capability, add a sysctl, loosen the bounding set) and whether that materially widens the blast radius.

## Success criteria (the spike answers, not code that ships)
- [ ] A clear PASS/FAIL: can `chrome-headless-shell` render a real page with its sandbox ENABLED inside the isolate?
- [ ] If PASS: the exact isolate delta required, with a security read on whether it's acceptable (does it keep caps dropped / no host FS / egress-contained?).
- [ ] If FAIL: the concrete blocker (e.g. nested userns clone denied under stripped caps), re-confirming `--no-sandbox` is required — which routes back to the owner for explicit `--no-sandbox` acceptance.
- [ ] Findings written to `poc/wsl2_browser_userns/README.md` (mirror the existing spike's results-table + load-bearing-findings format).

## Outcome → next
- PASS → update `js-rendering-fetcher` Task 1 to drop `--no-sandbox` + add the proven isolate delta; unblock the spec; author ADR-040 (sandbox retained).
- FAIL → return to owner with the re-confirmed constraint for `--no-sandbox` acceptance; then author ADR-040 (residual risk + compensating control) and unblock.

## Permissions
- Create only under `poc/wsl2_browser_userns/`; no `src/` edits.
- Commands: `wsl.exe -u root -- …` (isolate probes), `sysctl`, `sha256sum`; may need one-time chrome-headless-shell provisioning per `poc/wsl2_browser/README.md` if `/opt/chromium_headless_shell` is gone.
