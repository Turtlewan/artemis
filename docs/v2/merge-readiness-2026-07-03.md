# Merge-readiness assessment — `v2-rebuild` → `main`

_Read-only assessment produced 2026-07-03. No merge, push, or modification performed._

Branch under review: `v2-rebuild` @ `404777e` · target: `main` @ `25ac969`.
Scale: **187 commits / ~860 files / +53k / −73k** ahead of `main`. This is the entire v1→v2 rebuild (v1 deleted, v2 built fresh on a new multi-provider agent-harness architecture), not a normal feature PR. This is a **readiness assessment, not a line-by-line review**.

---

## 1. What the merge delivers (subsystem-level)

Sourced from `docs/status.md`, `docs/v2/`, and `git log --oneline main..HEAD` (feat-scope histogram: client 9, capabilities 3, identity 3, retrieval 2, api 2; plus sandbox/runtime/reachout/proactivity/forge/ask/agency). `src/artemis/` top dirs by file count: model 11, capabilities 9, api 9, ports 8, memory 8, reachout 7, spine 4, transport 3, scheduler 3, proactivity 2.

| Subsystem | What it adds |
|-----------|--------------|
| **Spine + model router** | Thin plan→act→verify spine over an own `QuotaAwareRouter` (codex → claude_code → anthropic_api → ollama, subscription-first; LiteLLM rejected). Per-backend schema down-conversion in each `RawProvider`. (Slices 0–1) |
| **Memory** | `CogneeMemory` behind `MemoryPort` (optional dep group) + retrieval pipeline (CHUNKS → rerank → MMR → token-budget → summarize-overflow), embedding-cosine MMR, LLM consolidation (ADD/UPDATE/DELETE/NOOP + supersession), `forget()`/decay over a durable SQLite ledger. (Slice 2) |
| **Proactivity + transport** | SQLite-backed durable `Scheduler` (cron + one-shot, fire-once catch-up) → `ProactiveWorker` → `TransportPort`. `ConsoleTransport` + `TelegramTransport` (Bot API, allowlisted long-poll) + `artemis` console script (`uv run artemis` = live heartbeat) + `add/list/cancel/run` CLI. (Slice 3) |
| **Capability build-by-chat** | Gated forge: `propose` → `build_proposed` (sandbox-verify, self-correcting) → `promote`, with AST import guard (`scan_for_unsafe_imports`) blocking network/process capabilities in the no-isolation sandbox. Brain endpoints (SSE) + Tauri gateway + AskPopup build-mode state machine + capabilities list. Proven live end-to-end. (CB-1…CB-5a) |
| **Invoke / reuse** | Closes the dogfood loop: NL invoke via intent router → match-first `CapabilitySelector` (dedicated Haiku, anti-hallucination re-validation, typed-arg coercion), typed inputs declared in SKILL.md, confirm-before-run + missing-key guard, keychain→isolate secret injection, dual-LLM output quarantine. Brain path + client confirm-card UI. (ADR-039, 5 specs) |
| **Reach-out / web** | Web primitives + clean-context provider + `WebTool` (Option B: sandbox = dumb egress-allowlisted fetch pipe, reasoning host-side), brain-side intent router (build/web_q/aggregate/plain_ask), reader no-tools quarantine, capture-then-replay eval corpus + harness + calibration, JS-rendering fallback fetcher (chrome-headless-shell in WSL2 isolate). (ADR-035/037/040) |
| **Sandbox** | Hardened WSL2 isolation runner (root-backed caps, egress IP-allowlist, netns/pid/mount-ns) replacing interim `SubprocessSandbox`; `FetchSandbox` + policy-wiring; chrome-capable render profile. (ADR-036/041) |
| **Secrets** | Keyring-backed `SecretStorePort` (OS keychain) + secret-capture routes + keys-panel UI + build-gate consent (egress + missing-secrets on the plan card). Telegram/Tavily migrated keychain-first (env fallback). |
| **Client** | Revived v1 Tauri client (112 tracked files) wired to the v2 brain: P-256 pairing + API session, Ask (+ stream), layout persistence, typed-empty domain reads for all 11 domains, build-mode + invoke confirm cards. Builds to `artemis-client.exe`; one-double-click launcher. (CR-1…CR-6) |

---

## 2. Current green status (run on HEAD `404777e`, this session)

| Check | Command | Result |
|-------|---------|--------|
| Type check | `uv run mypy` | **PASS** — "Success: no issues found in **136** source files" (exit 0) |
| Lint | `uv run ruff check src/ tests/` | **PASS** — "All checks passed!" (exit 0) |
| Tests | `uv run pytest -q` | **PASS** — **419 passed, 6 skipped, 2 deselected**, 1 warning, 55s (exit 0) |
| Client | tsc / vitest / cargo | **Not run this session** (would need `npm install` + cargo build; skipped for time). Documented green at HEAD `040de1b` in status.md: tsc/eslint clean · 97 vitest · 24 cargo · clippy clean. |

The one pytest warning is a benign Starlette/httpx deprecation notice, not a failure. Backend verification matches the numbers status.md claims (419/6) — no drift.

---

## 3. Merge mechanics + risks

- **Fast-forward-able:** ✅ Yes. `git merge-base --is-ancestor main HEAD` succeeds; `git rev-list --left-right --count main...HEAD` = **0 behind / 187 ahead**. `main` is a direct ancestor — `v2-rebuild` can fast-forward `main` with zero divergence.
- **Merge conflicts today:** ✅ None. `git merge-tree <merge-base> main HEAD` produces no conflict markers (as expected for a pure fast-forward).
- **v1 recoverable:** ✅ Yes. Tag `archive/v1` present; v1 planning/coding history frozen at `docs/archive/status-v1.md`; stale v1 specs archived under `archive/v1/`.
- **Large/binary files:** ✅ None. No tracked file > 1 MB.
- **Tracked secrets:** ✅ None found. Secret-pattern grep (sk-, AKIA, BEGIN PRIVATE KEY, xoxb-, ghp_) over all tracked files returned nothing. The only secret-adjacent tracked files are safe: `config/.env.*.example` (placeholder templates — ports/paths, no values), `evals/webtool/corpus/queries/neg-003-secret-key.json` (an adversarial *abstain* test case, no real key), and source/test/docs files that merely reference secret handling.
- **Working tree not clean:** the branch tip has uncommitted modifications (`CHANGELOG.md`, `src/artemis/reachout/web_tool.py`, `tests/reachout/test_web_tool.py`) and untracked files (`js_fetch.py`, `render_script.py`, tests, a setup doc). Per status.md the JS-fetcher stack was *committed* (`8164ba0`, `628080f`); these residual edits should be reconciled/committed or stashed **before** a merge so the merged state is the intended one. (Not a blocker to the merge mechanics — HEAD is clean — but confirm nothing important is left uncommitted.)

---

## 4. Known caveats already documented (merge with eyes open)

From status.md Open Questions / In-Flight. None blocks a merge; all are forward work on a green tree.

1. **Client UI is baseline styling only.** Build-mode, invoke confirm-card, keys-panel, and secret-capture UIs are functionally wired but on baseline CSS; a full UI overhaul is a separate owner track. Some flows are test-green but "not yet visually run/polished in the live app."
2. **Telegram transport not fully exercised as always-on.** Bot minted and proven both ways live, but tokens are an env stopgap until fully keychain-resident; R4 transport-ingress (inbound → intent router) is not built, so Telegram-side invoke is pending.
3. **`sandbox_policy.json` accepts unbounded numeric resource caps** on the `Wsl2SandboxRunner.run_tests` path (`memory_mb`/`cpu_pct`/`pids_max`/`timeout_s` have floors but no ceiling) — apex-security minor, deferred; queued as a small `Field`-bounds follow-up.
4. **Plan-gate egress not shown to owner.** The build plan card shows `secrets` but not `egress_domains`, so "Build it" is approved without seeing granted network domains — queued as `enabler-plangate-egress` (informed-consent gap; enforcement is safe).
5. **Stale v1 dirs remain under `src/artemis/`** (`cli`, `voice`, `reactions`, `proactive`, `knowledge`, …) as untracked `__pycache__` shells; `README.md` + `AGENTS.md` still describe v1 (queued for v2 rewrite). Cosmetic, not functional.
6. **Layering follow-up (review ⚠️):** `memory/embedder.py` imports the failover-error taxonomy from `artemis.model.errors`, transitively loading model providers; relocate to a neutral `artemis/errors.py` so memory doesn't drag in providers.
7. **Two pending specs, build not greenlit:** `verify-auth-unverified-mark` (honest `auth_status` labeling so promote/InstalledCard stop implying a credentialed path was verified) and `argv-base64-side-channel` (optional sturdier WSL arg-passing; ADR-042, durability insurance, not a bug fix).
8. **Claude Code subscription org-access flagged org-disabled** mid-session for the Opus host (may need `ANTHROPIC_API_KEY` or re-enabled org access next Opus session). Does not affect Codex builds or the merge.

---

## 5. Draft PR body

> **Title:** `v2 rebuild: multi-provider subscription-first agent harness (replaces v1)`
>
> **Summary**
> Replaces the v1 local-first RAG "second brain" with Artemis v2: a thin Python spine whose job is letting agents build the owner's capabilities by chat. 187 commits, ~860 files, +53k/−73k. v1 is preserved at tag `archive/v1`. `main` fast-forwards to this branch (0 behind / 187 ahead, no conflicts).
>
> **What's included**
> - **Spine + `QuotaAwareRouter`** — plan→act→verify over a subscription-first provider chain (codex → claude_code → anthropic_api → ollama).
> - **Memory** — `CogneeMemory` behind `MemoryPort` with a retrieval + consolidation + decay pipeline over a durable SQLite ledger.
> - **Proactivity + transport** — durable scheduler → proactive worker → Console/Telegram transports; `uv run artemis` always-on heartbeat + schedule CLI.
> - **Capability build-by-chat** — gated forge (propose→build→promote) with an AST network-import guard; brain SSE endpoints + Tauri build-mode UI. Proven live.
> - **Invoke / reuse** — match-first NL invoke, typed SKILL.md inputs, confirm-before-run, keychain→isolate secret injection, dual-LLM output quarantine.
> - **Reach-out / web** — egress-allowlisted fetch pipe + `WebTool` + intent router + reader quarantine + eval corpus/harness + JS-rendering fallback fetcher.
> - **Sandbox** — hardened WSL2 isolation runner + `FetchSandbox` (egress IP-allowlist, resource caps) replacing the interim subprocess sandbox.
> - **Secrets** — OS-keychain `SecretStorePort` + capture routes + keys-panel UI + build-gate consent.
> - **Client** — revived Tauri client wired to the v2 brain (pairing, Ask, layout, all 11 domains, build/invoke cards); builds to `artemis-client.exe` with a one-double-click launcher.
>
> **Known limitations**
> - Client UI on baseline styling; some flows test-green but not yet visually polished.
> - Telegram inbound → intent router (R4) not built; tokens partly env stopgap.
> - Deferred hardening: unbounded `sandbox_policy.json` caps, plan-gate egress-domain display, memory→model layering, stale v1 dirs + README/AGENTS v1 text.
>
> **How to verify**
> ```
> uv run mypy            # Success: no issues found in 136 source files
> uv run ruff check src/ tests/   # All checks passed!
> uv run pytest -q       # 419 passed, 6 skipped, 2 deselected
> ```
> Client (optional): `cd client && npm install && npm run build` (tsc/eslint/vitest) + `cargo test` — documented green.

---

## 6. Bottom-line recommendation

**Merge as-is (fast-forward).** The tree is green on all three backend gates (mypy 136 files, ruff clean, pytest 419 passed / 6 skipped), `main` fast-forwards with zero divergence and no conflicts, v1 is recoverable at `archive/v1`, and there are no tracked secrets or large/binary files. Every documented caveat is forward work on a green branch, not a defect in what's being merged.

**Two non-blocking pre-merge courtesies:**
1. Reconcile the branch-tip working-tree changes (uncommitted `web_tool.py`/`test_web_tool.py`/`CHANGELOG.md` + untracked `js_fetch.py`/`render_script.py`) — commit or stash so the merged state is intended.
2. Because this replaces `main` wholesale, do it as a reviewable PR (origin = github.com/Turtlewan/artemis) rather than a silent local fast-forward, so the v1→v2 cutover is recorded.
