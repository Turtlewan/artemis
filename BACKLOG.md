# Artemis — Feature Backlog

Raw idea inbox. **Throw anything here the moment it occurs to you** — half-formed is fine, no
structure required, no commitment to build it. This is the feeder: SP0 and later planning drain
items from here into `REQUIREMENTS.md`, the roadmap, and specs. Capturing ≠ committing.

**How to add an idea:**
- Just add a `- ` line under **Inbox** (hand-edit), **or**
- In any Artemis session say **"backlog: <idea>"** and I'll append it (dated).

When an item gets pulled into the planning corpus, move it to **Triaged** with a pointer so the
trail isn't lost.

---

## Inbox (unsorted — dump here)

<!-- Format is loose. Optional tags in [brackets] if useful, e.g. [integration] [second-brain] [voice]. Example:
- Auto-summarise overnight emails into a morning briefing  [integration][assistant]
-->

- Quote of the day — user adds quotes, assistant serves/finds them (daily or on demand)  [second-brain][assistant]  (2026-06-02)
- Acoustic-gesture activation — finger-snap + clap "turns Artemis full on" (wake/activate the assistant via a sound gesture, not a wake-word). Sits on the M5 audio sidecar; needs a sound-event classifier alongside STT/EOU. Decide: what "full on" means (wake from idle? full attention mode?) + false-trigger handling.  [voice][assistant]  (2026-06-16)

<!-- From the 2026-06-05 repo-studies pass — detail + verified sources in docs/research/repo-studies-prior-art.md -->
- Graph-RAG tier for the brain (symbol/entity knowledge-graph + multi-hop) alongside vector search — compare codegraph-ai/CodeGraph ONNX-memory vs current brain-architecture  [second-brain][rag]  (2026-06-05)
- Incremental fingerprint indexing + committed graph artifact for ingest (re-index only changed files) — from Understand-Anything  [second-brain][rag]  (2026-06-05)
- Enterprise-search query path: decompose → parallel multi-source → confidence-scored synthesis → digest (budget-guarded; HIGH cost) — from anthropics knowledge-work-plugins  [second-brain][assistant]  (2026-06-05)
- Anti-hallucination brain invariants: gap-tagging [MATERIAL GAP], multi-index citation verify, claim-audit gate, SHA-256 resumption ledger — from academic-research-skills  [second-brain][rag]  (2026-06-05)
- Two-tier memory (hot-cache + deep store) — reconcile with memory-engine-research.md  [second-brain]  (2026-06-05)
- Document handling: pdf/docx/pptx/xlsx skills + interactive pdf-viewer — install as plugins at build  [assistant][integration]  (2026-06-05)
- Eval Artemis's own AI quality with withpi encoder-scorer (deterministic, Promptfoo type:pi)  [assistant][eval]  (2026-06-05)
- Assistant persona/tone prior-art: Inflection Pi (empathetic personal assistant)  [assistant]  (2026-06-05)

<!-- [2026-06-13] Future-proofing items surfaced by the local-LLM expansion research (detail: docs/research/2026-06-13-local-llm-expansion/_SYNTHESIS-PLAN.md §6) -->
- **Home-lab / local-inference future-proofing (hardware + items) → lives in its own BANK**, not here. Build checklist, hardware items, path-specific accessories, and the EXP-a/EXP-b future specs are all in `docs/research/2026-06-13-local-llm-expansion/README.md` (§"Future hardware items & build checklist"). Activated when a hardware trigger fires.  [hardware][aci]  (2026-06-13)

<!-- [2026-06-13] UI-polish thread parked back to backlog (was an In-Flight scoping row; no decisions taken). Functional client UI is already specced (CLIENT-a..f). Two genuine gaps below + an undecided discussion-mode (visual mockups vs words+wireframes vs mix). Scoping context: docs/technical/architecture/app-flow.md. -->
- **Visual identity / design system** — no design tokens or concrete "Athena-style" aesthetic; client screens are stock SwiftUI. Define tokens (colour/type/spacing/material), dark mode, the menu-bar/hotkey panel look. Touches all surfaces — do before more screens.  [ui][design-system]  (2026-06-13)
- **Domain-spoke screens** — Calendar/Tasks/Email/Finance have no dedicated client UI (chat-only by current design); give each domain a visual home. Larger surface; depends on the design-system tokens existing first.  [ui]  (2026-06-13)

<!-- From the 2026-06-08 social-media RAG/voice filter pass (dedup'd against locked SP0 specs) -->
- Spotlighting + CaMeL + delimiter discipline for untrusted web content → fold into the **Deep-Research engine spec** (still to draft; already an open question)  [rag][security]  (2026-06-08)
- Versioned retrieval — tag ingest chunks `processing/verified/searchable`, expose only `verified` to retrieval → refines **M3-a** beyond plain idempotency (relates to the incremental-indexing item above)  [rag]  (2026-06-08)
- Summary-first tiered retrieval ("context stinginess") — store raw + a summary, retrieve the summary first, pull full transcript only when needed → **M4** auto-inject + tool design; fits lean profile (relates to two-tier memory item)  [second-brain][assistant]  (2026-06-08)
- Exact-match identifiers (IDs/dates/invoice numbers) fail in pure vector search — make sure **M3-b** keyword path explicitly handles structured tokens  [rag]  (2026-06-08)
- RAGAS/DeepEval RAG eval dimensions (faithfulness, answer-relevancy, context-recall) + red-teaming as the knowledge-core eval rubric → complements the withpi eval item above  [eval]  (2026-06-08)

<!-- From the 2026-06-09 cross-module-links 4-agent dive (detail: docs/research/cross-module-links.md) — prior-art links Artemis wouldn't have designed itself -->
<!-- [2026-06-11] RELATIONSHIP/PERSONAL-CRM CLUSTER discussed → core converged onto an on-demand **Person Briefing** (open-threads + facts; auto-detect threads from comms + manual log; deliberately bounded — "not crazy"). The 4 items below are now the **opt-in extras** layered around that core. Design note: docs/findings/person-briefing-discussion.md. Discussed, NOT specced. -->
- **Person Briefing (core, DISCUSSED 2026-06-11)** — on-demand "brief me on X" → non-obvious brief (open threads/promises + stored facts; skips identity/history). Auto-detect threads from comms at ask-time (dismissable) + manual log. Bounded/passive by default. Reuses M4 + Gmail(`artemis.untrusted`). → `docs/findings/person-briefing-discussion.md`  [memory][comms][assistant]
- **Gift-budget pipeline** — birthday (Calendar) → gift idea (Person/Memory) → budget line (Finance) → shopping item; a 4-hop cross-domain chain  [integration][finance][calendar]  (2026-06-09)
- **Person↔debt edge** — "I owe X $50 / X owes me" as a bidirectional Person↔Finance link (Monica pattern)  [finance][memory]  (2026-06-09)
- **Unlinked-mention detection** — a contact/project name in an email/note/task without an explicit link → suggested connection (Obsidian/Logseq); applies across Email+Notes+Tasks+Journal  [memory][second-brain]  (2026-06-09)
- **Relationship time-decay / reconnection prompts** — surface "haven't talked to X in a while" from comms-frequency patterns, not fixed reminders (Mesh)  [memory][comms]  (2026-06-09)
- **Task-deadline-vs-meeting conflict check** — when scheduling, flag if an attendee (or you) has a hard task deadline that day (task↔calendar↔person); no surveyed tool does this — a differentiator  [calendar][productivity]  (2026-06-09)
- **News-on-contact → pre-meeting brief** — public update/job-change about an attendee surfaced before a meeting (Person→News→Calendar, Mesh)  [comms][calendar][news]  (2026-06-09)
- **Goal entity + goal-cascade** — yearly Goal → project → weekly task → daily habit; Artemis has no Goal node (Habits/Goals deferred) — the missing rollup (Tana)  [productivity]  (2026-06-09)
- **Health↔productivity correlation** — "low-energy/poor-sleep days correlate with missed tasks" cross-link  [health][productivity]  (2026-06-09)
- **Camera receipt-OCR** — photo receipt → transaction extraction; closes the cash-transaction gap email/manual can't (folds into the camera-module discussion)  [vision][finance]  (2026-06-09)
- **Place/Location entity** — unhomed shared entity (Calendar location · Travel · Maps connector); needed as later spokes add location links  [architecture]  (2026-06-09)

<!-- [2026-06-18] From the "5 Levels of an AI Second Brain" video fit-eval (verdict + detail: docs/findings/prebuild-test-review-findings.md § Video fit-eval). Artemis already spans/exceeds all 5 levels; these two are the genuine sharpening ideas. -->
- **Whole-document & aggregate retrieval gap** — vector chunk-retrieval gives *wrong/incomplete* answers for two query shapes: faithful "summarise the WHOLE doc" (top-k chunks ≠ the whole file) and aggregates over structured data ("which week had the highest sales?" grabs one chunk, answers wrong). Fix = route those shapes to **whole-file read** / **structured query**, not top-k chunks. Refines/reinforces the existing **summary-first tiered retrieval** (line ~45) + **exact-match identifiers / structured tokens** (line ~46) items; M3-c agentic is still chunk-based + read-only. Aggregates partly live in M8 spoke tables, but faithful whole-doc summarisation is a real M3 gap.  [rag][second-brain]  (2026-06-18)
- **Active knowledge elicitation ("grill me")** — a proactive **interview-the-owner** capability to extract evergreen knowledge from the owner's head into M4 memory/entities (the video's sharpest non-technical point: the bottleneck is *getting knowledge in*, not retrieval). No such path today — M7-c curiosity is **web-grounded only** (needs ≥2 external sources), never owner-grounded. Natural fit for the voice-first surface (M5) + M4 write path; relates to the Person-Briefing core.  [memory][assistant][voice]  (2026-06-18)

<!-- [2026-06-20] From the "agentic OS perfect-memory" 4-pillar video fit-eval (verdict + dedup detail: ~/apex/docs/research/agentic-os-video-audit.md § sixth-video addendum). Pillars 1–3 already span Artemis's second-brain corpus; pillar 4 (team scoping) out of scope (single-owner/local-first, ADR-001/002). One genuine sharpening: -->
- **Supersession-on-recall (temporal-freshness citation)** — when the brain surfaces a past decision/fact, also confirm whether anything *newer* has superseded it ("…decided {date} by {decider}; no later discussion has changed this since"). Today's citation items (multi-index citation verify, gap-tagging, validation/provenance) are *source*-grounding, not *recency*-grounding — recalling a stale-but-cited decision as current is a distinct failure. Small refinement to the M3/M4 answer layer; pairs with versioned-retrieval (line ~44) + Person-Briefing open-threads.  [rag][memory]  (2026-06-20)

<!-- [2026-06-18] Owner ask: explore Devin desktop on the coding side. CAPTURE only — fit-eval deferred. -->
- **Devin desktop on the coding side** — explore incorporating Cognition's Devin (autonomous AI software engineer; source: trycognition.com / Cognition Labs) into Artemis's coding workflow. **Two distinct targets to disambiguate at triage:** (a) the *meta-build* side — Devin as an alternative/additional autonomous **coder backend in APEX coding mode** (executes whole `docs/changes/` specs), overlapping the existing DeepSeek pipeline (waves/tier-policy/verify-loop); or (b) an Artemis **coding *capability*** (a "delegate-this-coding-task" spoke Artemis orchestrates — no such spoke today; nearest = ACI/homelab control-plane + desk-vision build-assistant). **Key tension:** Artemis is locked local-first / privacy-walled (ADR-001/002); classic Devin is a *cloud* autonomous engineer → cuts against the posture (softer for the build corpus = planning docs/specs, harder for anything touching user data). **Triage step 0: verify what "Devin desktop" actually is/does** — a genuinely local desktop client changes the privacy math materially vs the cloud product. Then fit-eval per the standing "external content = fit-eval, not just capture" routine.  [aci][tooling][build]  (2026-06-18)



## Triaged (pulled into SP0 / requirements)

_Item → where it went (REQUIREMENTS.md section / ADR / spec). Keeps the trail._

- **Camera/vision module** (2026-06-09) → dedicated discussion 2026-06-11 **reframed** it from a home-cameras spoke into a **vision build-assistant** (overhead desk-vision HUD + voice-first guided builds) → **ADR-014** (DESIGNED, deferred; capability ladder Rung 0→3). Mini-local, NOT a home-cameras spoke, no ACI Phase-4. Full design + research: `docs/findings/desk-vision-hud-deep-dive.md`.

<!-- - Morning email briefing → REQUIREMENTS.md §Assistant; spec: docs/changes/morning-brief.md -->
