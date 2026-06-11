<!-- amended 2026-06-11 per Decision D2 -->
# Module design — Gmail (read-only mirror)

_Per-module design doc (second of the spoke-module design docs, after `calendar.md`). The complete
intended surface for the Gmail spoke **for v1 = read-only awareness**. Source-of-truth for the M8-b
spec. Created 2026-06-09._

> Posture (ADR-011): **mirror, read-only.** Gmail is the source of truth; Artemis reads (incremental
> History-API sync) and is **aware** of mail — it never sends, modifies, labels, archives, or deletes.
> Sending/other-people scheduling is deferred (needs Gmail send + the write-gating path; out of M8-b).
> All external mail content is **UNTRUSTED** (attacker-controllable) → it passes through the
> `artemis.untrusted`/spotlighting layer (DR-a) before any of it reaches the brain.

## Plugs into the contract
- **Module** = a `ModuleManifest` (M1-a): typed read `tools` (§B) + one `proactive_hook` (§E) +
  `data_scope = OWNER_PRIVATE` (mail is owner data) → its hook is **Tier-1** (queued while the vault is
  locked, ADR-006).
- **Auth**: the shared **M8-a** Google-auth foundation. Gmail registers its least-privilege scope
  `https://www.googleapis.com/auth/gmail.readonly` via `register_google_scopes("gmail", {...})` and
  obtains an auto-refreshing `Credentials` from `GoogleCredentialsFactory`. No new token store.
- **Knowledge push** (M3-a `Connector` → `IngestPipeline.ingest`): signal-mail bodies + parsed
  attachments → searchable knowledge (LanceDB on the encrypted volume).
- **Memory** (M4-b `MemoryWritePath` / `build_write_path`): standing facts via A.U.D.N. on signal mail.
- **Untrusted** (DR-a `artemis.untrusted`): the quarantine/spotlighting primitive every external mail
  body + attachment passes through before the brain reads it.
- **Heartbeat** (M6): the proactive hook (§E) runs on the M6 tick-loop; the urgency briefing is batched
  via M6-b's batched-LLM HIT handling.
- **Brain composes**: the module ships typed read primitives; "did the bank email me about the
  transfer?" is the brain composing `gmail.search` + `gmail.get_message` over the retrieved corpus.

## A. Ingestion model — **split by depth** (decided 2026-06-09)
Gmail auto-categorises every message. We exploit that label as a free signal and ingest at two depths:

| Tier | Categories | What is ingested |
|---|---|---|
| **Signal** | Primary, Updates, Forums | **Full body** (cleaned text) + **attachments** (parsed) → knowledge; **memory extraction** (A.U.D.N.) |
| **Awareness** | Promotions, Social, Spam, Trash | **Metadata only** — sender, subject, date, Gmail category, snippet. NO body embedding, NO attachment parse, NO memory extraction |

Rationale (the "why", not for the spec): keeps Artemis *aware of everything* (it can answer "anything
from X?", count/triage promos, and the retained category lets it differentiate marketing from real)
while pointing the marketing firehose **away** from the LLM — minimal injection surface, no memory
pollution, far lower embed/storage cost on the Mini. Differentiation comes from Gmail's category label
(kept as metadata), **not** from deep-reading junk: this is retrieval, not model training.

- **Backfill:** on first connect, ingest a **bounded window** — default **12 months**, configurable via
  `ARTEMIS_GMAIL_BACKFILL_MONTHS` (Settings, M0-a). After backfill → incremental forever.
- **Attachments (signal mail only):** download + Docling-parse the **Docling-parseable types**
  (PDF/docx/pptx/md/html…), **size-capped** (a `Settings` cap, e.g. `ARTEMIS_GMAIL_ATTACHMENT_MAX_MB`);
  skip images/archives/unknown types in v1. Parsed attachment text is **untrusted** (a malicious PDF is
  attacker-controlled) → same `artemis.untrusted` path as bodies, then `IngestPipeline.ingest`.
- **Untrusted boundary:** every external body + attachment is quarantined/spotlighted (DR-a) before it
  reaches the brain. Mail the owner *sent* is trusted; received mail is not.

## B. Read / awareness tools — `action_risk: read` (never gated)
| Tool | Purpose |
|---|---|
| `gmail.search(query, window?, max_results?)` | Gmail-syntax search over the owner's mail (server-side `messages.list q=`) → message refs |
| `gmail.get_message(message_id)` | full (spotlighted) detail of one message — headers + cleaned body |
| `gmail.list_threads(query?, window?)` | threads matching a query/window |
| `gmail.get_thread(thread_id)` | a full conversation thread |
| `gmail.list_unread(category?)` | unread messages (optionally by category) |

All read-only. No `send`, `modify`, `trash`, `label`, `archive` — those need `gmail.send`/`gmail.modify`
scopes and the write-gating path; **deferred** (ADR-011).

## C. Sync — incremental, polling (not push)
- **First run:** backfill the bounded window via `messages.list` (paged), record the latest `historyId`.
- **Steady state:** `history.list(startHistoryId=…)` returns the delta (added/removed/label-changed
  messages); apply to the read-cache + ingest new signal mail. Heartbeat drives cadence (polling, no
  public webhook — mirrors Calendar's `syncToken` posture).
- **Idempotency:** ingestion is `content_hash`-idempotent (M3-a) keyed by the Gmail message id; a
  re-seen unchanged message is a no-op.

## D. Memory integration — A.U.D.N. on signal mail (M4-b)
Extract standing facts from **signal mail only** (Primary/Updates/Forums) via the M4-b write path:
key contacts + recurring senders, relationships, and explicit commitments ("I'll send the report
Friday"). Deduped/updated by the existing A.U.D.N. cardinality rubric. Promotions/Social/Spam/Trash
**never** reach memory. Extraction runs on the **spotlighted** content (untrusted), never raw mail.

## E. Proactive hook — "important unread", end-state 3-stage funnel (decided 2026-06-09), Tier-1
A single `HookSpec` on the M6 Heartbeat (`check_ref → HookResult`), all **Tier-1** (queued while locked):

1. **Stage 1 — cheap pre-filter:** unread in **Primary or Updates** (`URGENCY_CANDIDATES = {PRIMARY, UPDATES}`) **AND** Gmail's own **Important** marker →
   a small candidate set. (Free signal; discards the bulk. No LLM. Forums is excluded — in `SIGNAL_CATEGORIES` for ingestion depth but not in `URGENCY_CANDIDATES` for urgency scoring. Decision D2 2026-06-11.)
2. **Stage 2 — memory boost:** candidates whose **sender is known to memory** (key people — boss,
   family, recurring contacts via M4) are bumped up in priority.
3. **Stage 3 — LLM urgency scoring:** ONLY the pre-filtered candidates are scored by the brain
   ("needs a reply today" vs "FYI") over their **spotlighted/quarantined** content (DR-a toolless
   reader — never raw mail to the brain), then bundled into ONE **batched urgency briefing** via
   M6-b's batched-LLM HIT handling → delivered to ntfy / the CLIENT Review-Status surface.

Cost-bounded by construction: the LLM only ever sees a handful of pre-filtered messages, never the
whole inbox. Stages 2–3 are additive and **degrade gracefully** (empty memory / no served model →
Stage 1 still produces a useful unread briefing). Off-hardware tested with fakes; the real LLM
scoring + real Gmail round-trips are **GATED on-hardware** (served model + real account).

## F. Data
- **Read-cache** (mirror): per-message metadata (id, threadId, historyId, sender, subject, date, Gmail
  category, snippet, label ids, has-attachments, unread/important flags) keyed by Gmail message id, in
  the owner-private encrypted SQLCipher store (M2 wall). The metadata-index for **all** mail lives here;
  it is the "awareness" layer and is never authoritative (Gmail is).
- **Knowledge** (M3-a): signal-mail bodies + parsed attachments → LanceDB on the encrypted volume.
- **Memory** (M4): standing facts from signal mail.
- **Sync cursor:** the latest `historyId` persisted in the owned store.
All owned stores are SQLCipher under the owner-private scope (M2 wall). Refresh token stays in the
M8-a owner-private token store; **never logged**.

## Security — external mail content is UNTRUSTED
Sender display names, subjects, bodies, and attachments all originate from other people →
attacker-controllable → an injection vector the moment they reach the LLM (search results, the urgency
scorer, memory extraction, briefings). **Every externally-sourced byte passes through `artemis.untrusted`
/ spotlighting (DR-a) before the brain.** The urgency scorer (§E Stage 3) is a toolless reader over
quarantined content (dual-LLM pattern), so a malicious email cannot drive a tool call. Refresh token is
owner-private, never logged. Read-only scope means no destructive blast radius even if compromised.

## Seam reconciliations (for the drafter — confirm against the live specs, park on mismatch)
- **M3-a `Connector` seam:** `Source.kind` is currently `Literal["file","web"]`. Gmail needs an
  `"email"`/`"gmail"` source kind OR the Gmail connector produces `RawItem`s directly and the spoke
  calls `IngestPipeline.ingest` per message. Reconcile minimally; prefer NOT to widen M3-a's Literal if
  a `RawItem`-producing connector + a thin ingest call suffices. Flag if M3-a must change.
- **M4-b `MemoryWritePath`/`build_write_path`:** confirm the exact constructor + call signature for the
  extraction path; the Gmail extraction feeds the same A.U.D.N. write path Calendar uses.
- **M6-a `HookSpec` + M6-b batching:** confirm `check_ref`/`HookResult` shape and how a hook emits a
  batched briefing through M6-b.
- **DR-a `artemis.untrusted`:** confirm the `Extract`/spotlighting entry point the body + attachment +
  urgency-scorer paths call.
- **M8-a:** `register_google_scopes`, `GoogleCredentialsFactory`, `required_scopes` — Gmail registers
  `gmail.readonly` and consumes the factory; no new auth code.

## Decisions (2026-06-09)
- **Read-only mirror** for v1; sending deferred (ADR-011).
- **Bounded backfill**, default 12 months, configurable.
- **Split-by-depth ingestion**: metadata-all + full-body/attachments/memory for signal categories only.
- **Attachments parsed on signal mail** (Docling types, size-capped, untrusted).
- **Memory extraction on signal mail only.**
- **History-API incremental sync**, Heartbeat-driven polling (no webhook).
- **End-state 3-stage urgency hook** (Gmail-Important+unread → memory boost → LLM on spotlighted
  content → batched briefing), gracefully degrading, scored on quarantined content only.
- **One spec** (owner's call 2026-06-09) — drafter applies the atomic-exception justification and flags
  back only if the readiness gate's file/phase budget genuinely cannot be met.

## Deferred / future
- **Send + reply** (Gmail send scope + write-gating through the Review screen).
- **Label/modify/archive** management.
- **Image/OCR attachments** (beyond Docling-parseable types).
- **Other-people scheduling assistant** (negotiating times via email — needs send; see `calendar.md`).
