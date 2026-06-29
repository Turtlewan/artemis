# Tier-2 / P1 Review Audit — 2026-06-29

_Second pass of the review-ensemble audit (the Tier-2/P1 backlog in
`~/.claude/skills/apex-code/REVIEW-ENSEMBLE-DESIGN.md`). Method: 2 Codex `gpt-5.5` read-only lenses
(security/privacy + concurrency/integrity, off-Max) + Opus adjudication against the verified
single-worker deployment model. Raw outputs: scratchpad `review-p1-security.json` /
`review-p1-concurrency.json`. Companion to the P0 audit `tier1-concurrency-audit-2026-06-29.md`._

## Verdict (headline)

**No active bug.** Like the P0 set, every P1 item is CLEAN or latent/defensive-only under the verified
single-uvicorn-worker model. One **high-confidence FLAG** (raised independently by *both* model
families) survives adjudication: the **registry execute-twin identity-integrity gap** — a manifest-time
wiring hardening gap, first-party-only, low urgency. Two minor defensive notes round it out.

## Per-item adjudication

| P1 item | sec lens | conc lens | Adjudicated | Why |
|---|---|---|---|---|
| Nonce / session **replay-after-restart** (`app_auth.py` ChallengeStore/SessionStore) | CLEAN | — | **CLEAN (by design)** | In-memory nonces/tokens are lost on restart → fail-safe: an old nonce can't `consume()`, an old bearer fails closed, clients re-handshake. The replay defense that *must* be durable — counter monotonicity — lives in `devices.json` and is read+checked+bumped before session mint. Only gap is test coverage of the restart path. |
| **Pairing-code / secret logging** (`api_app.py`) | CLEAN | — | **CLEAN** | No request-logging middleware; uvicorn default access log is method/path/status, not bodies/headers. The raw code is returned only by the loopback-gated `/admin/pair-code`; the session token only on successful completion. Nothing logs code/nonce/signature/token. (Defensive nit below.) |
| **ntfy DedupStore** mutate-before-persist (`ntfy_delivery.py`) | — | FLAG | **Latent / defensive-only** | `seen`/`mark` are sync, no await; the joined drain thread freezes the main loop; `os.replace` write is atomic. Residual: if persist fails *after* the in-memory mutation, memory and disk diverge until restart (a durability nit, not a race). |
| **tier1 deliver-swap** (`_handle_with_delivery_count`) | — | FLAG | **Latent / defensive-only** | The `hit_handler.deliver` swap spans the `await` and runs in the drain thread, but the main loop is blocked in `thread.join()` for the whole drain — nothing can observe the swapped callable. Inert under the current model. |
| **Staging per-query SQLCipher connections** (`staging/store.py`) | — | CLEAN | **CLEAN** | Each method is sync and commits before returning; `set_status_conditional` is a single-statement CAS (atomic across fresh connections); single writer on the loop. Missing WAL/busy-timeout is not a P1 issue at single-owner loopback scale. |
| **Registry execute-twin validation** (`registry/registry.py:62`) | FLAG | FLAG | **FLAG — high-confidence (both families)** | See below. |

## The one surviving finding — registry execute-twin identity integrity

`ToolRegistry.register` records `tool.execute_callable_ref or tool.callable_ref` as the `{tool}_execute`
twin for WRITE / HIGH_STAKES tools, and `get_tool` later wraps that callable with the **base tool's**
`args_schema`/`return_schema`. So staged args *are* revalidated against the gated base schema — the
front-line GATE contract holds. The gap: there is **no manifest-time invariant binding the supplied
execute callable to the base tool's identity**. A miswired (or malicious) in-process manifest could make
owner approval for tool *X* dispatch a different raw callable, and the `or tool.callable_ref` fallback
silently substitutes the front-door callable (e.g. the *classify* path, not the *raw* twin) when a WRITE
tool declares no explicit `execute_callable_ref`.

**Calibration:** manifests are first-party code wired at build time; no untrusted manifest is loaded at
runtime. So this is a **developer-error / defence-in-depth guard**, not an attacker-reachable bypass —
which is why both lenses landed on FLAG, not BLOCK. Realistic fix is modest (Python callables are
opaque, so semantic correspondence can't be fully proven):
- Drop the silent `or tool.callable_ref` fallback — require WRITE/HIGH_STAKES tools to declare an
  explicit `execute_callable_ref` (fail registration otherwise), so a missing twin is a loud error, not
  a silent front-door substitution.
- Optionally record twin provenance and assert the base tool exists at register time.

## Minor defensive notes (record, don't spec)
- **Redaction-set gap** (`obs/logging.py` `_SECRET_KEY_NAMES`): covers `token`/`bearer`/`secret`/`dek`
  but not `code`/`pairing_code`/`nonce`/`signature`. No current call logs those fields (logging audit
  CLEAN), so this is pure defence-in-depth — add the names if/when structured request logging expands.
- **DedupStore persist-failure divergence**: in-memory `_entries` can lead disk if the atomic write
  raises; self-heals on restart (reload from disk). Cosmetic at single-owner scale.

## Net result across both audits

The deep-review backlog's premise — *"dominant debt = concurrency/race correctness in the always-on
background + auth"* — is **substantially de-risked by the single-worker deployment model**. Across P0+P1,
zero active races; the strongest survivors are (a) the P0 staging at-most-once-on-external-effect gap
(real, single-request, gated to Google-spoke go-live — spec'd) and (b) this P1 registry-twin integrity
FLAG (first-party hardening, low urgency). **Recommendation:** the highest-value remaining concurrency
work is the P0 `harden-background-invariants` spec (makes the latent set safe-by-construction); the
registry-twin guard is a worthwhile small follow-up, not urgent. Future review spend should shift off
"hunt for races" toward correctness/contract lenses, since the race surface is now characterised.
