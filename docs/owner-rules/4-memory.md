# Owner Rules — 4. Memory & Forgetting

_Feeds: M4-a (schema/cardinality) · M4-b (A.U.D.N. write path) · M4-c-1 (recall + decay) · M4-c-2
(decay sweep + owner surface). The two LLM prompts here define "**what Artemis remembers about me
and how memories merge**" — the highest-stakes content in the module (mistakes corrupt the store)._

Status: ⬜ not started

## On the Mini
Decay constants in `decay.py`; the cardinality seed in `relation_cardinality`; the two prompts are
string literals in `extraction.py` / `decide.py`. All decay knobs are flagged **GATED for tuning**
against real usage traces — capture your *starting* values; final tuning happens on-Mini.

## Tunable rules
| Rule | Default | Lands in | Your value |
|------|---------|----------|------------|
| ⭐ Decay half-life | `14 days` (sweep 7/14/21/30) | `decay.py HALF_LIFE_DAYS` | |
| Inject relevance threshold | `0.2` | `decay.py INJECT_THRESHOLD` | |
| Auto-forget tombstone floor | `0.02` | `decay.py TOMBSTONE_FLOOR` | |
| Inject token budget (per turn) | `512` | `Brain.inject_token_budget` | |
| Candidate facts shown to A.U.D.N. decider | `5` | `MemoryWritePath.candidate_k` | |
| Owner-edit salience boost | `2.0` | M4-c-2 `edit_fact` | |
| ⭐ SINGLE-cardinality relations (overwrite prior value) | `lives_in, birthday, name, age, employer, home_address, phone_number, email` | M4-a `SEED_SINGLE_RELATIONS` | |
| Default cardinality for unknown relations | `MULTI` (fail-safe, never overwrites) | M4-a `DEFAULT_CARDINALITY` | |

## Prompt text (your voice)
**⭐ Fact-extraction prompt** (M4-b) — what counts as a fact worth remembering. Default: "extract
atomic, self-contained (subject, relation, object) facts; subject defaults to 'owner'; no
inferences." Your preferences (CONFIRMED 2026-06-19 — financial + health excluded entirely):
```
REMEMBER:
  ✓ Important dates (deadlines, renewals, appointments, recurring events)
  ✓ Awareness of ongoing projects + how the owner approaches them
      (NB: the live task/project RECORDS — status, due dates, recurrence — live in the Productivity
       module, S6, NOT memory. Memory holds only the awareness + execution style, never the task list.)
  ✓ How the owner likes to execute things (work style, methods, formats, preferences)
  ✓ KEY-PERSON "Ashley" (primary VIP): birthday, anniversary, flights/travel, events
  ⊕ Other key people & relationships (family, friends, colleagues) + their key dates/preferences
  ⊕ Commitments the owner makes ("I'll send X by Fri") — feeds task capture
  ⊕ Goals the owner is working toward
  ⊕ Travel & itineraries (owner's + Ashley's)
  ⊕ Vendors/services the owner uses (banks UOB/SCB/DBS, tools, providers)
  ⊕ [SENSITIVE] Standing logistics (home address, key contacts/service info — NON-financial)

DON'T REMEMBER:
  - passing moods / emotional venting
  - small talk / chit-chat
  - anything that requires INFERENCE beyond what was explicitly said
  - third parties' private details not relevant to the owner
  - one-off trivia with no future relevance
  - FINANCIAL facts/details (balances, transactions, account numbers, bills) — excluded from memory
    entirely; financial data lives ONLY in the Finance module's ledger (S3 routes bank emails there)
  - HEALTH / medical facts (conditions, meds, allergies) — excluded entirely

NOTE: The only [SENSITIVE]-in-memory category now is standing logistics → is_cloud_safe=false
(never sent to cloud teacher). Cross-ref S5 cloud-sensitivity.
```
**⭐ A.U.D.N. decision prompt** (M4-b) — when to Add / Update / Delete / Noop a fact.
Your preferences (CONFIRMED 2026-06-19 — "keep, but date it"):
```
DEFAULT: cardinality-driven —
  SINGLE relations (employer, home address, phone, name): supersede the prior value, but KEEP the
    old fact in bitemporal history (valid_to set; never hard-deleted).
  MULTI relations (likes, knows, projects): ADD (keep both).
WHEN UNSURE whether it's the same fact updated vs a new one → prefer ADD (KEEP BOTH) over UPDATE.
  Never silently overwrite.
DATE EVERYTHING: every fact carries valid_from / recorded_at so the timeline is visible and the
  owner can always tell which value is current and what it used to be.
NEVER auto-DELETE: superseding only sets valid_to (history retained). Hard delete is owner-only +
  confirm-gated (frozen invariant).
```
_Fully supported by the M4-a bitemporal schema — "date it" = the valid-time + transaction-time
timestamps that already exist. No spec gap; this confirms the default + the keep-both-when-unsure bias._

## Gap to decide
- **⭐ No confidence cutoff exists today — OWNER WANTS ONE (2026-06-19).** Extraction emits a
  `confidence` (0–1) but no spec drops low-confidence facts/tags at write time — it only feeds the
  decay score. Owner requirement: **auto-tagging must be accurate** → add a confidence floor so
  Artemis prefers "no tag / needs-review" over a wrong tag. This is a NEW knob to add to M4-b (and
  any other auto-tagger). **Behaviour RESOLVED: precision-first** — below the floor, no tag +
  "needs review" (never mis-tag). Threshold value TBD (tune on-Mini). See S5 §Auto-tagging.

## 🔒 Frozen invariants (not owner-tunable)
- Bitemporal mechanics (4-timestamp, sentinel, partial-unique index, dimension-lock).
- Owner-edit / purge require `confirm=True` (human-in-the-loop); purge = hard-delete only.
- Write-queue overflow (`maxsize=100`, drop+log).
