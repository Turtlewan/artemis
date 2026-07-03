# Handoff — 2026-07-03 (session 10, coding): ADR-046 local data spine

Built the **full ADR-046 local-first data spine** end-to-end (owner greenlit the full stack), incrementally as 9 waves, Codex-built + host-verified + committed each. 13 commits `98e9a7b..48899ba` on `v2-rebuild`. What changed → `git log`; build/test status → all green (mypy 82 · 553 tests · ruff+format clean). This handoff = what the build learned.

## Decisions Made
- **Fetcher home = Option B (owner chose): `capabilities/builtin/` is now git-tracked** (new `.gitignore` exception). Discovered mid-build that `capabilities/` is gitignored runtime storage — a spec-built fetcher placed in `library/` would evaporate on a fresh checkout / Mac Mini transfer and break its (tracked) host test. `FileCapabilityStore.get()` falls back to a `builtin_root` resolved relative to the source tree (repo-portable); `list()`/`retrieve()` stay library-only so builtin = infrastructure, not owner-facing selectable capabilities.
- **`calendar-sync` is a NEW builtin capability reusing `today-calendar`'s Google logic** (owner: "adapt, spec-built"). `today-calendar` kept intact as the on-demand invoke fallback. Window widened to 7 days, rows keyed by Google event id, date+time in each row's `text` (fixes live-smoke Finding D).
- **Read-path domain routing is deterministic (keyword registry), NOT a 2nd model call** — ADR-046 #4 budgets exactly one (phrasing) call. **Review needed ⚠️:** a keyword registry won't scale as synced domains grow; revisit a classifier (could extend the intent router) when there are several domains.
- **Defaults (tunable):** calendar sync `*/15`, 7-day window, 900s freshness threshold; scheduler tick 30s.
- **Reviewer cleanup:** `ScheduleLedger` gained a `check_same_thread` param — replaced a Codex-authored `_ApiScheduleLedger` subclass that duplicated the jobs-table schema (would drift on a base-schema change).

## Specialist Flags (data-spine security review — no BLOCK)
Boundaries verified to HOLD: payload isolation (raw `payload` never reaches an LLM — only `sanitized_text`); OAuth token injected to sandbox env only (never logged/argv/returned); the "no-tools" reader is real (`--tools ""` at the CLI, not just prompt); fail-closed ingest / fail-soft fetcher; all SQL parameterized (incl. dynamic `IN` + LIKE-escape); no token log leakage; scheduler dispatch has no external ingress.
- **FLAG (hardened, `48899ba`):** quarantine-once is a *single soft gate* (ADR-046 #3 latency trade) — read path trusts `sanitized_text` verbatim. Hardened by spotlight-wrapping records as data-only in the read prompt (zero extra latency). **Residual (bounded):** a jailbroken ingest sanitizer could smuggle attacker *text* into an answer — but the phraser is no-tools, so no exec/exfil. **→ Add a line to ADR-046's Security section explicitly accepting this residual.**
- **FLAG (follow-up, pre-existing):** `FetcherRunner.capability` (and `InvokeState.capability` upstream) is an unconstrained string — `store.get()` resolves `library/<name>/SKILL.md` with no path-traversal guard. NOT exploitable today (name is server-fixed `calendar-sync`, no external ingress). **Add a `[A-Za-z0-9_-]+` allowlist IF scheduler/invoke registration ever accepts an external capability name.**
- **NOTE:** `ScheduleLedger(check_same_thread=False)` for the sync ledger — latent data-race if a 2nd writer thread is ever added; not exploitable today.

## Blocked Actions
- **Wave 3 blocked on two owner forks** (surfaced, awaiting decision): (1) which curated domains to seed first (notes / projects / tasks / none-yet); (2) build the cross-domain briefing now (calendar-only) or defer until >1 synced domain exists.

## What's Next (discoveries)
- **The whole spine has NEVER run live** — unit-tested + host-verified only. Per the live-smoke rule it needs a real run: **owner enables the Calendar API** (console toggle, still pending from session 9) → `artemis serve` (sync auto-on) → the `*/15` loop syncs → ask "what's on my calendar" → real events via the ~2–4s local read. Until enabled, fetches **fail-soft (403)**, the store stays empty, and the read path falls through to the old invoke path (graceful).
- **A manual `artemis sync-now` trigger** would make that live smoke fast (no 15-min cron wait) — offered to the owner, not built.
- The spine is dead-code-free but **dead-until-live**: every wave was "dead-until-consumed" and the whole thing only produces observable value once the Calendar API is on and `artemis serve` runs with sync.
