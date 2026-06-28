# Agentic runtime (ADR-031) — open-fork decision brief

_Planning prep, 2026-06-28. Six forks were flagged 2026-06-25 as "minor parked flags for the build"
(status.md Open Questions; ADR-031 § Parked/next). Since then the dev-buildable spec series was
**built** (AGENT-* · `sensitivity-ground-rules` · `retriever-wiring`, all in `docs/changes/done/`).
That build silently resolved several of these forks in code. This brief separates the **genuinely-open**
ones (need an owner call) from the **already-decided-by-build** ones (ratify-or-revisit only)._

**TL;DR routing**

| # | Fork | Status | One-line recommendation |
|---|------|--------|--------------------------|
| 1 | `cloud_reasoning_enabled` default | **OPEN** | Ship **default `false`** (off) — opt-in. |
| 2 | sensitive-screen pre-filter app list | **OPEN** (Mac-gated, not urgent) | Starter **denylist + owner-extensible**, fail-toward-skip on unknown. |
| 3 | OpenHands→GATE wiring seam | **DECIDED + BUILT** | Ratify as-built; skip. |
| 4 | retriever general-scope eager-construct | **DECIDED + BUILT** | Ratify as-built; skip. |
| 5 | NRIC M-series checksum | **BUILT best-effort, flagged** | Accept as-is (low-stakes detector); add ICA-verify TODO. |
| 6 | `SensitivityConfig.owner_overrides` field | **DECIDED + BUILT** | Ratify as-built; skip. |

So only **Fork 1 and Fork 2 truly need an owner decision now.** 3/4/6 are code already; 5 is code with a verification footnote.

---

## Fork 1 — `cloud_reasoning_enabled` default (GENUINELY OPEN)

**Plain English.** The GEPA self-improvement loop is the part of Artemis that gets *better over time*
by sending its own past task transcripts to a top-tier cloud model and asking "how could I have done
that better?". Those transcripts can contain sensitive content (the owner already approved this as a
deliberate exception — Fork 3 in ADR-031). `cloud_reasoning_enabled` is the master kill-switch for
that whole path. The decision: when Artemis first ships, is that switch **on or off**?

**Why it matters.** This is the single most privacy-sensitive egress in the whole system — raw,
un-sanitised personal traces leaving the box. Its default sets the *opt-in vs opt-out* posture for
the riskiest data flow.

**Options.**
1. **Default OFF (`false`)** — opt-in. No sensitive traces ever leave until the owner deliberately flips it.
2. **Default ON (`true`)** — opt-out. Self-improvement works out of the box; owner must remember to disable.
3. **Default OFF + first-run prompt** — ship off, but surface a one-time "enable self-improvement?" ask the first time a recipe would benefit.

**Key trade-off.** Privacy/safety vs convenience. GEPA is **Phase 7 / end-state** (ADR-031 G) — it
literally cannot run until recipes exist, which is far down the road. So defaulting OFF costs *nothing
today* (the feature isn't live anyway) and avoids any chance of a forgotten switch leaking traces during
early bring-up. Fully reversible (one config flag).

**Recommendation: Default OFF (`false`).** Conservative-by-default on the one irreversible-leak path
costs nothing while GEPA is dormant, and an explicit owner flip is the documented escape-hatch ADR-031
already calls for. (Option 3's first-run prompt is a nice end-state polish — fold in when GEPA ships, not now.)

---

## Fork 2 — sensitive-screen pre-filter app list (GENUINELY OPEN; Mac-gated, low urgency)

**Plain English.** At Rung 3, Artemis controls the desktop by taking screenshots and sending them to
Anthropic's cloud vision model (another owner-approved exception). The pre-filter is the guard that says
"if the focused window is my banking app / password manager / health record, DON'T send that frame to
the cloud — redact it or skip it." The decision: **which apps go on that block-list, and how is the list
defined?**

**Why it matters.** This is the mitigation that makes the Fork-2 cloud-vision concession acceptable. Too
narrow a list and sensitive screens leak; too broad and Rung 3 becomes useless. It reuses the ADR-029
`SensitivityClassifier` as the detector.

**Options.**
1. **Fixed built-in denylist** — hard-code categories (banking/finance, password managers, health/medical, auth/2FA prompts).
2. **Built-in denylist + owner-extensible config** — ship sensible defaults *plus* a `policy.json` list the owner can add to.
3. **Classifier-only (no app list)** — rely purely on the on-frame content classifier, no app-identity gate.

**Key trade-off.** Coverage/safety vs effort/false-positives. App-identity (window title / process name)
is a cheap, robust signal that catches a banking screen *before* any pixel is analysed; the content
classifier is the backstop for everything else. Defining the list is small effort; the end-state wants
both layers. Fully reversible (config).

**Recommendation: Option 2 — built-in denylist + owner-extensible, fail-toward-skip on unknown.** Seed
with banking/finance, password managers (1Password/Bitwarden/KeePass), health/medical portals, and any
full-screen credential/2FA prompt; let the owner append; when app identity is unknown, lean on the
content classifier and skip-on-doubt. **Not urgent** — this is parked to the Rung-3 spec, which is
**Mac-gated (Phase 5)**; decide it when Rung 3 is actually specced, not now. Flagging it as "decide at
Rung-3 spec time" is a valid disposition.

---

## Fork 3 — OpenHands→GATE wiring seam (ALREADY DECIDED + BUILT — ratify, skip)

**Plain English.** The borrowed OpenHands coding SDK has its own "stop and ask before doing something
risky" mechanism (`WAITING_FOR_CONFIRMATION`). Artemis has its own single approval surface (the GATE /
AuthorityGate + owner-inbox). The fork was: how do those two connect so there's *one* approval flow, not two?

**Status: resolved in ADR-031 Refinement 2026-06-26 §5 and BUILT in `AGENT-coder` (now in done/).** The
implementation: a custom OpenHands `ConfirmationPolicy` + `SecurityAnalyzer` defers every
`WAITING_FOR_CONFIRMATION` to `AuthorityGate.authorize` + `OwnerInbox.ask`, with no change to OpenHands'
tool executors. Acceptance criteria already enforce: the gate fires **regardless** of the analyzer's risk
rating, and it's **fail-closed** (gate raising or inbox timeout → DENY, nothing proceeds).

**Recommendation: Ratify as-built. Skip — no decision needed.** The design doc effectively decided this;
the only residual is the build-follow-up item "spine approve→graduate happy-path is incomplete" (status.md),
which is a wiring polish gated on GATE-b, not a fork.

---

## Fork 4 — retriever general-scope eager-construct (ALREADY DECIDED + BUILT — ratify, skip)

**Plain English.** When the brain answers a question it retrieves supporting chunks from two stores: the
owner-private store and the general store. The fork was a wiring detail: *how/when* are those LanceDB
stores constructed inside `compose_brain` — eagerly up front, or lazily via a deferred factory?

**Status: resolved in `retriever-wiring` (now in done/), Ambiguity A1.** The LanceDB production adapter
requires its `is_unlocked` callable **bound at construction time**, so a deferred factory doesn't work —
the stores are **eagerly constructed inside the `if key_provider is not None:` unlocked block**, covering
both `OWNER_PRIVATE` + `GENERAL` scopes via the `store_for` callable; the privacy enforcer partitions at
query time (retrieval itself is privacy-unaware).

**Recommendation: Ratify as-built. Skip — no decision needed.** This was a forced move (the adapter's
construction contract dictated it), already implemented and tested (`test_retrieve_fn_merges_scopes`).

---

## Fork 5 — NRIC M-series checksum (BUILT best-effort — accept, with a verify-TODO)

**Plain English.** One of the deterministic sensitivity detectors recognises Singapore NRIC/FIN numbers
so documents containing them get auto-tagged sensitive. Singapore's newer **M-series** FIN (foreign IDs,
introduced 2022) has its own checksum rule. The fork: is Artemis's M-series checksum math actually correct?

**Status: BUILT in `sensitivity-ground-rules` (done/) but self-flagged "best-effort, verify before relying."**
The code uses offset **+3** with the F/G letter table (`_NRIC_M_LETTERS = "XWUTRQPNMLK"`). The spec's own
Gap #2 says the exact offset and letter table "should be verified against the official ICA specification
before committing. Treat as best-effort until confirmed."

**Options.**
1. **Accept as-is** — keep the +3 / F-G-table implementation, add a verification TODO.
2. **Verify against ICA / a community-validated reference** before relying on it, then correct if wrong.
3. **Drop M-series from the regex** until verified (only validate S/T/F/G).

**Key trade-off.** Correctness vs effort — but the **stakes are low by design**. This is one of *three*
sensitivity layers (deterministic detector → classifier → ask-owner). The detector **fails toward
sensitive**: a correct M-series number that the checksum wrongly rejects just means this one layer misses;
the classifier layer still catches NRIC-shaped content. A false-negative is a missed *auto-tag*, not a
leak. Fully reversible (one function).

**Recommendation: Option 1 — accept as-is, add an ICA-verification TODO.** It's a low-stakes,
defence-in-depth detector with two backstops; blocking the series on an exact-checksum-table confirmation
is over-investment. Worth a 15-minute verification pass against an authoritative source opportunistically,
but it does not gate anything.

---

## Fork 6 — `SensitivityConfig.owner_overrides` field (ALREADY DECIDED + BUILT — ratify, skip)

**Plain English.** Sometimes the owner wants to override how Artemis classifies a particular source's
sensitivity ("always treat *this* feed as sensitive / as general, regardless of the classifier"). The fork
was whether/how to give the owner that override lever.

**Status: BUILT in `sensitivity-ground-rules` (done/).** `policy.json` carries a `sensitivity.owner_overrides`
dict mapping a **source_id pattern → sensitivity**; the ask-and-graduate flow writes into it, and future
ingestion of matching sources honours the override. `SensitivityConfig` is a Pydantic model on `RuntimeConfig`.

**Recommendation: Ratify as-built. Skip — no decision needed.** The mechanism the owner described exists
and is wired into ingestion. Only revisit if the override *granularity* (per-source-pattern) turns out too
coarse in practice — not a pre-build decision.

---

## Bottom line for the owner

- **Decide now (2 forks):** Fork 1 (`cloud_reasoning_enabled` default → recommend **OFF**) and Fork 2
  (sensitive-screen denylist → recommend **built-in + owner-extensible**, or formally defer to the
  Mac-gated Rung-3 spec).
- **Ratify / skip (3 forks):** Forks 3, 4, 6 are already built code — confirm you're happy with the
  as-built behaviour and close them.
- **Accept with footnote (1 fork):** Fork 5 is built best-effort; accept it and leave a verify-TODO.
