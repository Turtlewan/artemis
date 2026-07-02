# WSL2 Chromium userns-sandbox Spike

Follow-up to `poc/wsl2_browser/` (the headless-Chromium-in-isolate feasibility spike). That spike
ran Chrome with `--no-sandbox` and noted (check #1) that the flag was "empirically not required …
tested both ways" yet kept it "for robustness." An apex-security review of the `js-rendering-fetcher`
spec (2026-07-03, BLOCK 2) flagged that `--no-sandbox` **disables Chrome's per-renderer seccomp-bpf
sandbox** — the primary defense against a renderer RCE from adversarial JS/WASM. Owner directed this
spike to settle it before building.

**Question:** can `chrome-headless-shell` render WITH its own (unprivileged user-namespace) sandbox
engaged, nested inside the ADR-036 isolate's `unshare --mount --pid` + `setpriv --bounding-set=-all
--inh-caps=-all` (uid 4000) chain — so we avoid `--no-sandbox` entirely?

**Verdict: PASS — and strictly better than the status quo.** Dropping `--no-sandbox` engages Chrome's
seccomp-bpf renderer sandbox with **zero** change to the isolate (no added capability, no sysctl). The
JS fetcher should run WITHOUT `--no-sandbox`/`--disable-setuid-sandbox`, gaining defense-in-depth
(Chrome sandbox **+** WSL2 isolate) at no measurable cost.

## Host
Verified 2026-07-03 on this host: Ubuntu 24.04 WSL2, kernel 6.6.87.2-microsoft-standard-WSL2,
chrome-headless-shell build 1228 (Chrome-for-Testing 149.0.7827.55), provisioned at
`/opt/chromium_headless_shell/`. `max_user_namespaces=61665`; `kernel.apparmor_restrict_unprivileged_userns`
absent (WSL2 does not enforce the Ubuntu 24.04 AppArmor userns clamp); `unprivileged_userns_clone`
sysctl absent (default-on).

## Layout
- `capability/render.py` — copy of the base spike's renderer, modified: `--no-sandbox` +
  `--disable-setuid-sandbox` are now OMITTED by default (userns-sandbox path); set env
  `CHROME_NO_SANDBOX=1` to restore the old flags for A/B.
- `isolate.sh`, `run.py` — unchanged copies of the base spike's isolate + host runner.

## Results

| # | Check | Result | Evidence |
|---|-------|--------|----------|
| 1 | Renders WITHOUT `--no-sandbox` in the isolate | PASS | `run.py … en.wikipedia.org/wiki/Python_(programming_language)` -> exit 0, **1.27s**, peak mem **163 MB**, **102 KB** clean article text. Identical envelope to the `--no-sandbox` base spike. |
| 2 | Sandbox is actually ENGAGED (not silently skipped) | PASS | `/proc/<pid>/status` `Seccomp:` of live chrome procs under the exact `setpriv --reuid=4000 --bounding-set=-all --inh-caps=-all` chain: **WITHOUT `--no-sandbox` -> renderer procs show `Seccomp: 2`** (SECCOMP_MODE_FILTER); **WITH `--no-sandbox` -> all procs `Seccomp: 0`**. So the userns namespace sandbox + seccomp-bpf filter engage on the renderers. |
| 3 | Isolate delta required | NONE | The sandbox engaged under the isolate's existing de-privilege chain — no capability retained, no sysctl added, bounding set still fully stripped. ADR-036's boundary is untouched. |
| 4 | Egress containment still holds | PASS (inherited) | Enabling Chrome's internal sandbox is orthogonal to and more restrictive than the netns/nginx-SNI boundary; the allowlist=`en.wikipedia.org`-only fetch in check 1 confirms egress containment is unchanged from the base spike. |

## Load-bearing findings

**1. Drop `--no-sandbox` AND `--disable-setuid-sandbox` in the real fetcher.** They are not needed
under the de-privileged isolate, and keeping them DISABLES the seccomp-bpf renderer sandbox
(`Seccomp: 0` everywhere). Omitting them yields `Seccomp: 2` on the renderers — real per-renderer
syscall filtering layered on top of the isolate. The base spike's "kept for robustness" note was
backwards; robustness comes from *removing* them here.

**2. No isolate change.** Chrome's zygote creates its user namespace unprivileged; creating a new
userns does not require any capability, so the fully-stripped `--bounding-set=-all` de-priv is
compatible with it. `js-rendering-fetcher` needs no `sandbox_wsl2.py` change for this — only the flag
removal in `render_script.py`.

**3. `chrome-headless-shell` (old headless) does NOT refuse to run unsandboxed.** Unlike full chrome's
"running as root" refusal, chrome-headless-shell ran (exit 0) even with `--no-sandbox` and even as
root, so "it rendered" alone does NOT prove sandboxing — the `/proc` `Seccomp:` check (finding above)
is the authoritative signal and is what the real fetcher's build-time sandbox check should be reasoned
against.
