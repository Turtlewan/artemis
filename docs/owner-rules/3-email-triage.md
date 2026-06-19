# Owner Rules — 3. Email Triage

_Feeds: M8-b1 (read-only connector) · M8-b2 (urgency hook). The urgency hook is the most
misfire-prone owner surface in the corpus — there is currently **no explicit owner rubric**; it's
inferred. Hook cadence lives in `1-proactivity.md`._

Status: ⬜ not started

## On the Mini
Config fields + consts in `modules/gmail/`; the urgency rubric is an LLM query string in `urgency.py`.

## Tunable rules
| Rule | Default | Lands in | Your value |
|------|---------|----------|------------|
| ⭐ VIP / "known senders" list | *inferred* via `recall("known contact person name")` — no explicit list | M8-b2 `build_known_senders` | **Ashley, Debby** (exact addresses TBD on Mini). NB: importance is also **topic-driven**, not only sender — see rubric. |
| Signal categories (deep ingest: body+attachments+memory) | `PRIMARY, UPDATES, FORUMS` | M8-b1 `SIGNAL_CATEGORIES` | |
| Urgency candidate categories (eligible to notify) | `PRIMARY, UPDATES` (Forums excluded) | M8-b2 `URGENCY_CANDIDATES` | |
| Backfill window | `12 months` | `ARTEMIS_GMAIL_BACKFILL_MONTHS` | |
| Attachment size cap | `10 MB` | `ARTEMIS_GMAIL_ATTACHMENT_MAX_MB` | |
| Max emails scored per scan | `10` | M8-b2 hook param | |
| Notification dedup | once/day | M8-b2 `dedup_value=today_iso` | |
| Memory-extraction objective | `"standing facts, commitments, key contacts about the owner"` | M8-b1 `GmailMemoryExtractor` query | |

## Prompt text (your voice)
**⭐ Urgency-scoring rubric** (M8-b2) — what makes an email *urgent enough to notify you today*.
Default query: `"urgent action required, important request, time-sensitive"`. The Stage-3
"reply-today vs FYI" judgment currently has **no explicit owner rubric** (it rides M6-b's generic
prompt). Write yours:
```
NOTIFY me ONLY when an email is one of:
  1. Legal — anything legal in nature (notices, disputes, contracts needing action).
  2. Payment warning — a payment is late/overdue, OR a transaction looks fraudulent / faulty / unexpected.

Treat as IMPORTANT (surface & track, but do NOT push a notification):
  - interview-related emails
  - faulty / disputed transactions
  - emails from Ashley or Debby

Stay SILENT (no notification):
  - routine bank transaction confirmations (UOB / Standard Chartered / DBS) → these feed FINANCE
    tracking, not alerts
  - newsletters, receipts, marketing, social, automated notifications
```
**VIP list** (concrete senders/domains that should always boost urgency):
```
Ashley, Debby  (exact email addresses to confirm on the Mini)
Topic signals that mark importance: interviews · faulty/fraudulent transactions · legal · payment warnings
```

## ⚠️ Flags surfaced during capture (need a design decision)
1. **Bank transaction emails → Finance, not urgency.** Owner uses UOB / Standard Chartered / DBS
   transaction emails as **finance tracking** input, explicitly NOT as notifications. This is a
   cross-module routing rule that belongs to the **Finance spoke** (`finance.md`, DESIGNED/deferred,
   email-extraction ledger). Carry into Finance design: these senders should be ingested by Finance
   and **excluded** from the M8-b2 urgency candidates so they never push an alert. → captured for
   Finance surface when it's built.
   **Reconciliation requirement recorded in `finance.md` 2026-06-19** (owner case): the local model
   classifies + extracts per email, but a **deterministic ledger** must (a) dedup duplicate
   notifications of one purchase, and (b) use a new `transaction.type` to **exclude credit-card bill
   payments / inter-account transfers from spend** (else double-count). Ambiguous → owner-review.
2. **Stage-1 Important-marker gate may DROP exactly the emails owner cares about.** M8-b2 Stage-1
   pre-filter requires `unread AND Gmail-IMPORTANT AND category∈{PRIMARY,UPDATES}` before anything
   is scored. Legal notices and fraud/payment-warning emails often are NOT flagged Important by
   Gmail (esp. first contact / unknown sender), so they'd be filtered out before reaching the
   scorer. The owner's notify-policy is **topic/keyword-driven**, which the hard Important gate
   undercuts. → Decision: widen Stage-1 to also admit topic/keyword or VIP-sender signals
   (legal / fraud / payment-warning / Ashley / Debby) regardless of Gmail's Important marker.

## 🔒 Frozen invariants (not owner-tunable)
- Quarantine posture: raw mail never reaches the scoring model; tool returns body spotlighted,
  metadata plain, snippet dropped — security boundary.
- History-API sync, OAuth/token mechanics, `gmail.readonly` least-privilege scope.
- Stage-1 uses Gmail's own "Important" marker as a trust signal (structure fixed; you can still
  retune what's eligible via the category lists above).
