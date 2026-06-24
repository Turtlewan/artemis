---
spec: m8-b2-urgency-widen
status: ready
token_profile: balanced
autonomy_level: L2
cross_model_review: true
---
<!-- AMENDMENT to M8-b2 (do NOT edit the frozen M8-b2-gmail-urgency-hook.md). Wave F1 cluster amendment.
     Implements Gmail decisions D1 (OR-in topic+VIP admit), D2 (bank-sender exclude), D3 (hybrid VIP force-admit).
     Reads keyword/VIP/exclude lists from X3 runtime-config. check_ref stays LLM-free + deterministic (Seam 5).
     Seam 7 invariant preserved: raw subject/snippet NEVER enter the payload — keyword matching produces only
     a boolean admit reason; the raw text is read locally to decide admit, then discarded. -->

# Spec: M8-b2-urgency-widen — widen Stage-1 admit (OR-in keyword + VIP force-admit) + bank-sender exclude

**Identity:** Amends `GmailUrgencyPreFilter.stage1_candidates` to OR-in two new admit paths beyond the Gmail-Important path — a deterministic keyword/topic match (D1) and a VIP-sender force-admit (D3) — then applies a bank-sender exclude filter (D2). The keyword/VIP/exclude lists are read from `RuntimeConfig.gmail.*` at composition time. `check_ref` stays synchronous and LLM-free; raw subject/snippet are read only to compute a boolean admit reason and are never placed in the payload (Seam 7).
→ why: see docs/findings/cluster-decisions/DECISIONS-LOG.md (Gmail D1/D2/D3 LOCKED) · docs/findings/cluster-spec-roadmap.md Wave F1 · docs/technical/modules/gmail.md §E.

## Assumptions

- **M8-b2** (frozen, `M8-b2-gmail-urgency-hook.md`) is complete: `src/artemis/modules/gmail/urgency.py` exports `GmailUrgencyPreFilter` (constructed `(cache: GmailReadCache, *, known_senders: frozenset[str] = frozenset(), max_candidates: int = 10)`), `URGENCY_CANDIDATES = frozenset({MailCategory.PRIMARY, MailCategory.UPDATES})`, `UrgencyCandidate` (frozen dataclass: `message_id`, `sender`, `known_to_memory`, `extract_summary`, `extract_failed` — **no `subject`/`snippet`**), `fetch_extracts`, `UrgencyTemplateRenderer`; `src/artemis/modules/gmail/hook.py` exports `build_known_senders` (async) and `build_gmail_urgency_hook(cache, api, reader, known_senders, *, max_candidates=10, interval_seconds=300) -> tuple[HookSpec, Callable[[], Awaitable[None]], Callable[[TemplateRegistry], None]]`; `src/artemis/modules/gmail/module.py` exports `build_gmail_manifest(api, cache, *, hook=None)`. `CachedMessage` (M8-b1) has fields `message_id`, `sender`, `unread`, `important`, `category`, `snippet`, `subject`, `internal_date_ms`. → impact: Stop (this spec MODIFIES those three source files in place; symbol names + signatures must match the frozen spec exactly. The constructor and `build_gmail_urgency_hook` signatures gain new keyword params — additive, defaulted, so the frozen tests still type-check).
- **X3 runtime-config** is complete: `from artemis.runtime_config import get_runtime_config` returns a `RuntimeConfig` whose `.gmail` exposes `vip_senders: tuple[str, ...]` (default `("ashley", "debby")`), `urgency_keywords: tuple[str, ...]` (default includes `"legal"`, `"fraud"`, `"payment warning"`, …), `urgency_sender_exclude: tuple[str, ...]` (default UOB/SCB/DBS domains). These are tuples; this spec converts each to a lowercased `frozenset[str]` at composition time. → impact: Stop (the lists are read ONCE at `build_gmail_urgency_hook` call time via `get_runtime_config()`, never per-tick — keeps `check_ref` free of I/O and config-parse cost).
- The **VIP set is hybrid (D3):** the effective force-admit set = the static `RuntimeConfig.gmail.vip_senders` ∪ the memory-derived `known_senders` already built by `build_known_senders` (frozen spec). VIP membership is a case-insensitive substring test against `candidate.sender.lower()` (a VIP token appearing anywhere in the sender display-name/address). A VIP match force-admits the message **even if it is not Gmail-Important**, which is the new D3 behaviour; the existing `known_to_memory` scoring boost is independent and unchanged. → impact: Stop (force-admit changes which messages enter Stage-1; the `known_to_memory` flag still rides the payload for scoring).
- The **keyword admit (D1) is deterministic + local:** a case-insensitive substring scan of `msg.subject` (and `msg.sender`) against the `urgency_keywords` frozenset. This reads the raw subject text **locally inside `stage1_candidates`** only to compute a boolean; the raw subject is then discarded and never enters the payload (Seam 7). The admit reason is recorded as a bounded `Literal` enum value (`"important" | "keyword" | "vip"`), not the matched text. → impact: Stop (Seam 7 — no attacker-controlled free text crosses into the M6-b prompt; only a 3-valued enum).
- The **bank-sender exclude (D2)** is applied AFTER admit as a filter: any candidate whose sender domain (the part after `@`, lowercased) ends with / equals any entry in `urgency_sender_exclude` is dropped — bank transaction alerts are Finance's domain, never urgency. The exclude wins over admit (even a VIP/keyword/important match is dropped if the sender is an excluded bank domain). → impact: Caution (exclude-after-admit ordering is load-bearing: a bank "payment warning" subject must NOT become an urgency candidate; the exclude is the final gate).
- `check_ref` remains **synchronous, LLM-free, zero `await`** (M6-a / contracts.md Seam 5). All new logic (keyword scan, VIP test, domain exclude) is pure O(n) string ops over the ≤`max_candidates` cache rows. No model, no embedder, no network. → impact: Stop.
- Off-hardware: same harness as the frozen M8-b2 tests — `FakeGmailApi`-backed `GmailReadCache`, a pre-built `frozenset[str]`, no live calls. The X3 config is read via `get_runtime_config()` against the default `policy.json`-absent state (all-defaults), or a monkeypatched `RuntimeConfig` for override tests. → impact: Low.

Simplicity check: considered a separate `stage1b_widen` method — rejected; the OR-in admit and exclude belong inside `stage1_candidates` so there is one admit decision point (no two callers can disagree on what is a candidate). Considered passing the config object into the filter — rejected; converting to three `frozenset`s at composition and storing them keeps `check_ref` allocation-free and the filter independent of the config module. The admit reason is a bounded enum, the minimum needed to surface *why* a message was admitted without leaking subject text.

## Prerequisites

- Specs complete: **M8-b2** (the frozen urgency hook this amends), **X3-runtime-config** (`get_runtime_config().gmail.*`), **M8-b1** (`CachedMessage`/`GmailReadCache`), **M6-a** (`HookSpec`/`HookResult`).
- Environment: no new PyPI deps (`email.utils` stdlib; X3 already present). `uv sync` suffices off-hardware.

## Files to Change

| File | Operation | Notes |
|------|-----------|-------|
| `/Users/artemis-build/artemis/src/artemis/modules/gmail/urgency.py` | modify | widen `stage1_candidates` (OR-in keyword + VIP force-admit) + new exclude filter; add `urgency_keywords`/`vip_senders`/`sender_exclude` constructor params; add `admit_reason` to `UrgencyCandidate` + `build_payload`; add `_sender_domain` helper |
| `/Users/artemis-build/artemis/src/artemis/modules/gmail/hook.py` | modify | `build_gmail_urgency_hook` reads X3 config (keywords/exclude) + unions static `vip_senders` into the VIP force-admit set; passes the three frozensets into `GmailUrgencyPreFilter` |
| `/Users/artemis-build/artemis/tests/test_gmail_urgency_hook.py` | modify | add D1/D2/D3 cases: keyword OR-in admit, VIP force-admit of a non-Important message, bank-sender exclude wins, admit_reason set correctly, no subject text in payload |

All paths under `/Users/artemis-build/artemis/`.

## Tasks

- [ ] **Task 1: Widen `GmailUrgencyPreFilter` — config params + admit logic + exclude** — files: `/Users/artemis-build/artemis/src/artemis/modules/gmail/urgency.py` (SURGICAL modify) —

  **1a. Constructor params (additive, defaulted — frozen tests unaffected):**
  ```python
  class GmailUrgencyPreFilter:
      def __init__(
          self,
          cache: GmailReadCache,
          *,
          known_senders: frozenset[str] = frozenset(),
          urgency_keywords: frozenset[str] = frozenset(),   # NEW (D1) — lowercased topic tokens
          vip_senders: frozenset[str] = frozenset(),        # NEW (D3) — lowercased VIP tokens (static ∪ memory done by caller)
          sender_exclude: frozenset[str] = frozenset(),     # NEW (D2) — lowercased bank domains
          max_candidates: int = 10,
      ) -> None: ...
  ```
  Store all four frozensets. The frozen `known_senders` stays the Stage-2 scoring boost source; `vip_senders` is the new force-admit source (the caller may pass `known_senders ∪ static_vips` OR pass them separately — see hook.py Task 2; the filter treats `vip_senders` as the force-admit set and `known_senders` as the boost set independently).

  **1b. Add an `admit_reason` field to `UrgencyCandidate`** (bounded enum — NOT free text, Seam 7):
  ```python
  admit_reason: Literal["important", "keyword", "vip"]   # why this message was admitted (no subject text)
  ```
  Place it after the existing fields. The dict produced by `build_payload` gains an `"admit_reason"` key. Still no `subject`/`snippet` key.

  **1c. New `_sender_domain` helper (module-level or static):**
  ```python
  def _sender_domain(sender: str) -> str:  # the lowercased domain after '@'; "" if none
      addr = email.utils.parseaddr(sender)[1]          # the address part, e.g. alerts@uob.com.sg
      return addr.split("@", 1)[1].lower() if "@" in addr else ""
  ```

  **1d. Rewrite `stage1_candidates` admit decision.** The current body keeps `unread AND important AND category in URGENCY_CANDIDATES`. Replace the per-message keep test with a helper that returns `(keep: bool, reason: Literal["important","keyword","vip"] | None)`:

  ```python
  def _classify_admit(self, msg: CachedMessage) -> tuple[bool, Literal["important", "keyword", "vip"] | None]:
      if not msg.unread:
          return (False, None)                          # never admit a read message
      sender_l = msg.sender.lower()
      # D3 — VIP force-admit (highest priority reason; admits even if not Important)
      if self.vip_senders and any(tok in sender_l for tok in self.vip_senders):
          return (True, "vip")
      # Gmail-Important path (the original admit)
      if msg.important and msg.category in URGENCY_CANDIDATES:
          return (True, "important")
      # D1 — keyword/topic OR-in (subject + sender scanned locally; raw text NOT retained)
      if self.urgency_keywords:
          hay = f"{msg.subject} {msg.sender}".lower()   # local-only; discarded after the boolean
          if any(kw in hay for kw in self.urgency_keywords):
              return (True, "keyword")
      return (False, None)
  ```

  Then in `stage1_candidates`:
  1. `rows = self.cache.list_unread(category=None)`.
  2. For each row compute `(keep, reason) = self._classify_admit(row)`; collect `(row, reason)` where `keep`.
  3. **D2 exclude filter (after admit):** drop any `(row, reason)` whose `_sender_domain(row.sender)` matches an entry in `self.sender_exclude` (match if the domain equals OR ends with `"." + entry` OR equals `entry` — so `alerts.uob.com.sg` matches `uob.com.sg`). The exclude wins over every admit reason.
  4. Sort by `internal_date_ms` descending; take top `self.max_candidates`.
  5. Return the surviving rows. **Carry the `reason` forward** — change the return type to `list[tuple[CachedMessage, Literal["important","keyword","vip"]]]` so `stage2_boost`/`build_payload` can stamp `admit_reason`. (Update the two callers in this file accordingly; the frozen `stage2_boost` signature becomes `stage2_boost(self, admitted: list[tuple[CachedMessage, str]]) -> list[tuple[CachedMessage, bool, str]]` carrying `(msg, known_to_memory, admit_reason)`.)

  **1e. Thread `admit_reason` through `stage2_boost` + `build_payload`:** `stage2_boost` keeps computing `known_to_memory` (substring vs `known_senders`) and now also passes through the `admit_reason`. `build_payload(self, boosted: list[tuple[CachedMessage, bool, str]], extracts) -> dict` stamps `"admit_reason": reason` on each candidate dict alongside the existing keys. Still NO `subject`/`snippet`/raw `From:` header in the dict.

  **Seam 7 inline comment (required):** `# SEAM 7: msg.subject is read locally ONLY to compute the keyword-admit boolean; it is NEVER stored in a candidate or payload. Only the bounded admit_reason enum crosses into M6-b's prompt.`

  — done when: `uv run mypy --strict src` passes; `GmailUrgencyPreFilter(cache)` (no new args) behaves exactly as the frozen filter (defaults are empty frozensets → no keyword/VIP/exclude effect → original Important-only admit); a non-Important PRIMARY message whose subject contains `"fraud"` is admitted with `admit_reason="keyword"` when `urgency_keywords={"fraud"}`; a non-Important message from a VIP sender is admitted with `admit_reason="vip"` when `vip_senders={"ashley"}`; a message from `alerts@uob.com.sg` is dropped when `sender_exclude={"uob.com.sg"}` even if Important; no candidate dict contains a `"subject"` or `"snippet"` key.

- [ ] **Task 2: `build_gmail_urgency_hook` reads X3 config + unions VIP set** — files: `/Users/artemis-build/artemis/src/artemis/modules/gmail/hook.py` (SURGICAL modify) —

  In `build_gmail_urgency_hook(cache, api, reader, known_senders, *, max_candidates=10, interval_seconds=300)` (signature unchanged), before constructing `GmailUrgencyPreFilter`, read the X3 config and build the three frozensets:
  ```python
  from artemis.runtime_config import get_runtime_config
  cfg = get_runtime_config().gmail
  urgency_keywords = frozenset(k.lower() for k in cfg.urgency_keywords)
  static_vips = frozenset(v.lower() for v in cfg.vip_senders)
  sender_exclude = frozenset(d.lower() for d in cfg.urgency_sender_exclude)
  vip_senders = static_vips | known_senders   # D3 hybrid: static ∪ memory-derived
  pre_filter = GmailUrgencyPreFilter(
      cache,
      known_senders=known_senders,            # scoring boost set (unchanged)
      urgency_keywords=urgency_keywords,
      vip_senders=vip_senders,                # force-admit set (static ∪ memory)
      sender_exclude=sender_exclude,
      max_candidates=max_candidates,
  )
  ```
  Everything else in `build_gmail_urgency_hook` (the `_extract_cell`, `_pre_flight`, `_check_ref`, the returned 3-tuple, `dedup_key="gmail_urgency"`, `tier=1`, `needs_llm=True`) is unchanged. `check_ref` remains LLM-free (config was read once here at composition, not in the tick).

  **Composition note (document inline):** the X3 config is read at hook-build time. A `reload_runtime_config()` after the owner edits `policy.json` requires the hook to be rebuilt to pick up new keywords/VIPs/excludes — acceptable for daemon-scope config (same posture as the M6-wake fallback-time read).

  — done when: `uv run mypy --strict src` passes; `build_gmail_urgency_hook(cache, api, reader, known_senders=frozenset())` builds a filter whose `vip_senders` equals the lowercased static `RuntimeConfig.gmail.vip_senders` (when `known_senders` empty); with `known_senders={"carol"}` the filter's `vip_senders` is `{"ashley","debby","carol"}` (static ∪ memory); the returned `HookSpec.check_ref()` is still synchronous and makes no model call.

- [ ] **Task 3: Tests — D1/D2/D3 widen cases** — files: `/Users/artemis-build/artemis/tests/test_gmail_urgency_hook.py` (modify, additive) —

  Reuse the frozen harness (`FakeGmailApi`-backed `GmailReadCache` over a temp SQLCipher / plain-sqlite fallback, `FakeKeyProvider(owner_unlocked=True)`). Add:

  - **D1 keyword OR-in admit:** seed a `unread=True, important=False, category=PRIMARY` message with `subject="URGENT: legal notice"`. `GmailUrgencyPreFilter(cache, urgency_keywords=frozenset({"legal"}))` → `stage1_candidates()` includes it with `admit_reason == "keyword"`. With `urgency_keywords=frozenset()` (default) the same message is NOT admitted (no Important, no VIP).
  - **D1 keyword does not leak text:** the resulting payload candidate dict has `admit_reason="keyword"` and NO `"subject"`/`"snippet"` key; assert the matched word `"legal"`/the full subject string does NOT appear anywhere in the candidate dict values except (never) — i.e. assert `"legal notice" not in json.dumps(candidate_dict)`.
  - **D3 VIP force-admit of a non-Important message:** seed `unread=True, important=False, category=PRIMARY, sender="Ashley Tan <ashley@x.com>"`. `GmailUrgencyPreFilter(cache, vip_senders=frozenset({"ashley"}))` → admitted with `admit_reason == "vip"`, even though not Important. Without `vip_senders` it is not admitted.
  - **D3 hybrid union (hook level):** `build_gmail_urgency_hook(cache, api, reader, known_senders=frozenset({"carol"}))` (X3 defaults give static VIPs ashley/debby) → a message from `carol@x.com` (memory-derived VIP, non-Important) is force-admitted; a message from `debby@x.com` (static VIP) is force-admitted. (Use a monkeypatched/cleared `get_runtime_config` cache or the default config.)
  - **D2 bank-sender exclude wins:** seed `unread=True, important=True, category=PRIMARY, sender="UOB <alerts@uob.com.sg>"` with `subject="payment warning"` (would match keyword AND is Important). `GmailUrgencyPreFilter(cache, urgency_keywords=frozenset({"payment warning"}), sender_exclude=frozenset({"uob.com.sg"}))` → NOT in `stage1_candidates()` (exclude wins over Important + keyword). With `sender_exclude=frozenset()` the same message IS admitted.
  - **D2 subdomain exclude:** sender `alerts@notify.dbs.com.sg` with `sender_exclude=frozenset({"dbs.com.sg"})` → excluded (domain ends-with match).
  - **Backward-compat:** the frozen Stage-1 test (only Important-PRIMARY/UPDATES admitted, FORUMS/PROMOTIONS excluded) still passes when the filter is constructed with the new params all defaulted to empty.
  - **admit_reason on Important path:** an Important PRIMARY message with no keyword/VIP config → `admit_reason == "important"`.

  — done when: `uv run pytest -q tests/test_gmail_urgency_hook.py` passes AND `uv run mypy --strict src tests/test_gmail_urgency_hook.py` passes AND `uv run ruff check . && uv run ruff format --check .` both exit 0.

- [ ] **Task 4 (GATED — on-hardware):** On the Mini, vault unlocked, real served model + Gmail backfill, with a `policy.json` setting a real VIP (`ashley`) and the bank excludes: confirm a real non-Important email from the VIP is force-admitted and reaches the urgency briefing; confirm a real UOB transaction-alert email is NOT an urgency candidate (D2); confirm no subject text appears in any info-level log. — done when: recorded in handoff.

## Permissions

The following actions will run autonomously during build.
Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Modify | `/Users/artemis-build/artemis/src/artemis/modules/gmail/urgency.py` |
| Modify | `/Users/artemis-build/artemis/src/artemis/modules/gmail/hook.py` |
| Modify | `/Users/artemis-build/artemis/tests/test_gmail_urgency_hook.py` |
| Delete | (none) |

### Commands
| Command | Purpose |
|---------|---------|
| `uv run mypy --strict src tests/test_gmail_urgency_hook.py` | Type gate |
| `uv run ruff check . && uv run ruff format --check .` | Lint + format gate |
| `uv run pytest -q tests/test_gmail_urgency_hook.py` | Test gate (fakes only) |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | `src/artemis/modules/gmail/urgency.py`, `src/artemis/modules/gmail/hook.py`, `tests/test_gmail_urgency_hook.py` |
| `git commit` | `"feat: M8-b2 urgency-widen — D1 keyword OR-in + D2 bank exclude + D3 VIP force-admit (X3 config)"` |

### Environment Access
| Variable | Purpose |
|----------|---------|
| `ARTEMIS_ENV_FILE` / `ARTEMIS_DATA_ROOT` / `ARTEMIS_SLOT` | Settings + cache-DB + slot_root (for X3 `policy.json`) resolution |

### Network
| Action | Purpose |
|--------|---------|
| (none off-hardware) | Tests use fakes; real Gmail/model GATED on-hardware (Task 4) |

## Specialist Context

### Security

**Load-bearing invariants (the urgency admit decides what proactively interrupts the owner — widening it is security-relevant):**

1. **Seam 7 — no attacker-controlled free text crosses the boundary.** `msg.subject` and `msg.sender` are read LOCALLY inside `_classify_admit` only to compute a boolean admit + a bounded `admit_reason` enum (`"important"|"keyword"|"vip"`). The raw subject is never stored on `UrgencyCandidate` and never enters the payload. The frozen spec already removed `subject`/`snippet` from the payload; this amendment keeps that — the keyword scan does not re-introduce them. Enforced by: the candidate dict assertion in tests (`"subject" not in dict`, full-subject-string not in `json.dumps(candidate)`).
2. **`check_ref` stays LLM-free + deterministic (Seam 5).** All new admit logic is pure string ops over ≤`max_candidates` cache rows. No model, no embedder, no network in the tick. The X3 config is read once at composition, not per tick.
3. **D2 exclude is the final gate.** Bank transaction alerts (UOB/SCB/DBS) are structurally prevented from becoming urgency notifications even when their subject contains an urgency keyword (e.g. "payment warning") — preventing the urgency hook from spamming the owner with routine bank alerts (those are Finance's domain). The exclude wins over every admit reason.
4. **VIP force-admit (D3) is bounded.** The VIP set is the static `RuntimeConfig.gmail.vip_senders` (owner-curated, default 2 first-names) ∪ the memory-derived `known_senders` (already bounded by `build_known_senders`'s `k`). It is a substring test, not an LLM call. A malicious sender spoofing a VIP display-name can at most cause a force-admit into the urgency briefing — which still routes through the DR-a `QuarantinedReader` Extract before any privileged model sees content (the frozen quarantine boundary is unchanged). No new egress surface.
5. **Tier-1 unchanged.** The hook stays `tier=1` on the OWNER_PRIVATE Gmail module — it never runs while the vault is locked (M6-a gate).

[apex-security review: the widen does not weaken the quarantine boundary — admitted candidates still go through `fetch_extracts` → `QuarantinedReader` before M6-b. The new surface is the keyword/VIP admit (deterministic, bounded) and the exclude (a strict drop). Confirm `admit_reason` is a `Literal`, not the matched string; confirm the exclude is applied after admit so it cannot be bypassed by an Important+VIP message from a bank domain.]

### Performance

- The widen adds, per cache row, one VIP-substring scan, one keyword-substring scan over `f"{subject} {sender}"`, and (post-admit) one `parseaddr` + domain-suffix check. All O(token count) over ≤`max_candidates` rows (default 10) — sub-millisecond, no I/O. The three frozensets are built once at composition. No change to the per-tick model-call budget (still ≤`max_candidates` pre-flight extracts + 1 M6-b batch, only when candidates exist).

### Accessibility

(none — headless proactive hook)

## Documentation

| Doc type | File | Action |
|----------|------|--------|
| Inline | `src/artemis/modules/gmail/urgency.py` | Document the three admit paths (Important / keyword / VIP), the exclude-wins ordering, the `admit_reason` enum, and the Seam-7 "subject read locally, never stored" invariant |
| Inline | `src/artemis/modules/gmail/hook.py` | Document that keyword/VIP/exclude lists are read from X3 at composition (rebuild to pick up edits); document the D3 hybrid union (static ∪ memory) |

## Acceptance Criteria

- [ ] `uv run mypy --strict src tests/test_gmail_urgency_hook.py` → verify: exit 0.
- [ ] `uv run ruff check . && uv run ruff format --check .` → verify: both exit 0.
- [ ] `uv run pytest -q tests/test_gmail_urgency_hook.py` → verify: D1 keyword OR-in admits a non-Important message with `admit_reason="keyword"` (and not when keywords empty); D1 leaks no subject text into the payload; D3 VIP force-admits a non-Important VIP sender with `admit_reason="vip"`; D3 hybrid union force-admits both a memory-derived and a static VIP; D2 bank-sender exclude drops an Important+keyword bank email; D2 subdomain exclude matches by domain-suffix; backward-compat (defaults = empty frozensets) preserves the frozen Important-only admit; `admit_reason="important"` on the original path.
- [ ] `uv run python -c "from artemis.modules.gmail.urgency import GmailUrgencyPreFilter; import inspect; print('vip_senders' in inspect.signature(GmailUrgencyPreFilter.__init__).parameters)"` → verify: prints `True`.
- [ ] (GATED, on Mini) real VIP non-Important email force-admitted; real UOB alert excluded; no subject in info logs → recorded in handoff.

## Progress
_(Coding mode writes here — do not edit manually)_
