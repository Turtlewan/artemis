# Owner Rules — 5. Self-Teaching & Safety Policy

_Feeds: M7-b (promotion policy) · M7-a2 (escalation / cloud-egress) · M7-c (curiosity loop) · GATE-a
(action staging) · DR-b (web egress). These are the "**what may Artemis do without asking me, and
what may leave the box**" controls — safety-critical, several have **no safe default**._

Status: ⬜ not started

## On the Mini
Mostly ctor default args + pure-function class boundaries (`classify_safety`, `grounding_gate`) +
the `is_cloud_safe` upstream classification. Some (token caps) have **no default and must be set**
before the loop is allowed to run.

## Tunable rules
| Rule | Default | Lands in | Your value |
|------|---------|----------|------------|
| ⭐ Auto-enable vs gate boundary | auto-enable iff `action_class ∈ {READ_ONLY, NO_DATA}`; else owner-gated | M7-b `classify_safety` | **Auto = internal & reversible** (read-only, no-data, **+ internal data-organization: tagging/filing/categorizing**). **Gate = external-effect** (send/book/pay). Destructive internal ops (delete/merge memory) already confirm-gated. ⚠️ Widens spec default → adds an "internal-reversible data action" tier to `classify_safety`. **Confirmed 2026-06-19.** |
| ⭐ Recipe promotion threshold (N re-occurrences) | `2` (also gates M8-d-c2 capture) | M7-b `Promoter.threshold` | |
| ⭐ Cloud-egress: "what is sensitive" (`is_cloud_safe`) | caller-supplied bool; sensitive + cloud teacher → refuse | M7-a2 `teacher_origin` boundary | |
| ⭐ Curiosity per-cycle token cap | **no default** | M7-c `TokenLedger.per_cycle_cap` | |
| ⭐ Curiosity weekly token cap | **no default** (rolling 7-day) | M7-c `TokenLedger.weekly_cap` | |
| Curiosity idle window | `00:30–08:30 SGT` | M7-c `is_idle` | **`00:00 → 07:00 SGT`** (proposed; asleep ~23:30–00:00, up ~07:15) |
| Grounding gate: independent source count | `≥2` distinct eTLD+1 | M7-c `grounding_gate` | |
| Gap-scan thresholds | `confidence_floor=0.5, staleness_days=90` | M7-c `scan_gaps` | |
| Staged-action expiry (TTL) | `24h` | GATE-a `ActionStagingService.default_ttl` | |
| ⭐ Web-egress static allow-list (domains/APIs Artemis may ever reach) | API endpoints only | DR-b `EgressPolicy.static_hosts` | |
| Fetch caps | `5MB / 20k chars / 8s` | DR-b ctor | |
| Search provider preference | Brave default, Tavily fallback | DR-b adapter | |

## ⭐ Auto-tagging policy (owner requirement, 2026-06-19)
Owner: **tagging must be automated AND accurate.** Decomposed:
- **Autonomy = AUTO.** Tagging / categorizing / filing (internal, reversible, no external effect)
  is NEVER gated — Artemis applies tags without asking. (This steers the self-teaching boundary
  below toward auto for internal organization; the gate is reserved for external-effect actions.)
- **Accuracy = safeguarded, not assumed.** Three mechanisms, none of which ask the owner per item:
  1. **Confidence floor** — below threshold, leave untagged / "needs review" rather than mis-tag
     (resolves the M4-b no-cutoff gap; applies to every auto-tagger: memory, email categories,
     knowledge ingestion, productivity areas, future finance categorization).
  2. **Always correctable** — tags visible + one-tap editable; nothing locked.
  3. **Learns from corrections** — owner fixes feed back so it's right next time.
- **RESOLVED 2026-06-19 — precision-first.** When confidence is below the floor → apply **NO tag**
  and mark **"needs review"** (never a wrong tag). The threshold *value* is TBD (tune on-Mini against
  real data). **⚠️ Spec gap:** auto-taggers need a `needs_review` state + the confidence-floor check
  added — applies to M4-b (memory), Gmail categories, M3 ingestion tags, Productivity areas, and
  future Finance categorization. A consistent "needs review" surface should be a planning item.
- **Scope (pending confirm):** which surfaces "tagging" covers for the owner — email · tasks/areas ·
  memory facts · finance categories · knowledge. →

## Prompt text (your voice)
**Cloud-sensitivity policy** (CONFIRMED 2026-06-19) — one line: **Artemis may ask the cloud teacher
for general SKILLS, never about the owner's actual LIFE.**
```
LOCAL-ONLY (never leaves the box):
  - Email — bodies, subjects, senders (incl. Ashley, Debby)   [local model is good enough — see below]
  - Calendar — titles, attendees, locations, times
  - People & contacts — anyone by name
  - Memory facts — everything Artemis remembers about the owner
  - Tasks & projects — titles, notes, contents
  - Ingested documents — file contents
  - Home address / standing logistics
  - Voice recordings & transcripts
  - (Financial & health — never even stored)

CLOUD-OK (general, NO personal specifics):
  - Abstract how-to / coding ("how do I parse a PDF table?")
  - General world knowledge / definitions
  - Capability-learning from the teacher — system already strips specifics (M7-a2 distillation is
    instance-free: never embeds the owner's actual request text, only the abstract problem shape)
```
**Email stays local — confirmed.** Local model is good enough for triage / summarize / extract; the
hard part (deciding what matters, pulling key points) is well within local capability, and
precision-first flags low-confidence cases rather than erring. Reply-DRAFTING is where big models
lead, but that's owner-reviewed (never auto-sent) and not worth leaking the inbox for → use a local
draft or a larger *local* model. Quality is a model-size tunable, **verified on the Mini** (run real
email, spot-check, bump model size if needed); privacy is non-negotiable.

## 🔒 Frozen invariants (not owner-tunable)
- SSRF deny-list (private/loopback/link-local/reserved/metadata IPs); https-only egress.
- Distillation is instance-free (never embeds your request text); script recipes run only behind a
  sandbox (fail-closed); curiosity never self-generates and never auto-commits (owner-only).
- GATE: expired actions never execute; at-most-once dispatch; approve/reject need vault+session.
- Owner command (`promote(name)`) always overrides the threshold.
