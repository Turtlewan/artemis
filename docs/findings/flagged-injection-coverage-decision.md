# flagged_injection coverage sweep (Item 3) — decision record

_Decided 2026-06-25 (planning, owner-led). The continuation-7 status note flagged only `GmailMemoryExtractor`; this sweep found it is **systemic** — three quarantine-`Extract` consumers ignore the `flagged_injection` flag, two of them writing flagged content into long-term memory._

## Finding — coverage of every `Extract` consumer

| Consumer | Feeds into | Checks `flagged_injection`? |
|---|---|---|
| `finance/extraction.py` | finance suggestions | ✅ yes (FIN-b fix) |
| `research/engine.py` | research synthesis | ✅ yes |
| `gmail/ingest.py` (`GmailMemoryExtractor`) | **long-term memory** | ❌ GAP (high) |
| `calendar/memory.py` via `calendar/untrusted.py` | **long-term memory** | ❌ GAP (high) — `untrusted.py:68` **logs** the flag then returns content with `parse_failed=False` |
| `gmail/urgency.py` | urgency-scoring LLM payload (M6-b) | ❌ GAP (medium) |

Root cause: the contract requires every consumer to remember to check two booleans (`parse_failed`, `flagged_injection`). Consumers written with review check both; the earlier memory-writers check only `parse_failed`. Memory poisoning is the worst sink — it persists and re-surfaces.

## Decision: centralized defense-in-depth (owner, 2026-06-25)
Make carelessness harmless rather than trusting every consumer — consistent with the "powerless by construction" design of the `untrusted/` layer.

1. **Blank-on-flag at the reader.** `QuarantinedReader.read` returns **empty `summary` + `claims` when `flagged_injection=True`**, while keeping `flagged_injection=True` on the `Extract` (signal preserved for telemetry). Any consumer that forgets the check now gets empty text → nothing to poison → fails **safe**, not open. (Note: `gmail/ingest.py:194` already returns `False` on empty text — so it auto-drops once content is blanked.)
2. **`Extract.usable` property** = `not parse_failed and not flagged_injection`. The single gate memory/LLM consumers should use.
3. **Fix the 3 sites explicitly** to gate on `.usable` (clarity + removes the calendar whitespace edge where `"" + "\n" + ""` would still enqueue `"\n"`).
4. **Telemetry on detection** — emit an OBS event `injection attempt flagged from <source_domain>` so arriving attacks are visible (not silent-drop). Cheap; OBS layer's job.

## Scope note
This is the **email/calendar half** of the "is every untrusted-content consumer protected?" sweep. The **knowledge-ingestion half** (web/file → RAG chunks not yet routed through quarantine; retrieved chunks need spotlighting before a responder) is folded into **Item 2** (`docs/findings/retriever-wiring-decision.md`).

## To author at session end
Build spec: `QuarantinedReader.read` blank-on-flag + `Extract.usable` + gate `gmail/ingest`, `calendar/untrusted`+`calendar/memory`, `gmail/urgency` on `.usable` + OBS injection-flag event + regression tests (flagged content never reaches memory / urgency payload). Small, dev-buildable, no HW gate.
