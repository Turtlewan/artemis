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
- Wired-network headroom for the inference box — Mini↔box Ethernet (WoL needs it), TB5 only if Mac-clustering ever  [hardware][aci]  (2026-06-13)
- UPS + power monitoring for 24/7 inference box  [hardware][aci]  (2026-06-13)
- Inference-box bring-up runbook + secrets/disk-encryption posture (pairs with the trust-boundary decision)  [security][aci]  (2026-06-13)
- Capability-lane convergence: x86/GPU inference box doubles as the DPO/RLAIF training home (homelab-control-plane.md frames this)  [capability][aci]  (2026-06-13)
- Model-weight storage management — hundreds of GB per model; versioning + eviction policy  [aci]  (2026-06-13)
- Wake-on-demand power orchestration — Mini wakes inference box per queued job, sleeps it after  [aci]  (2026-06-13)
- Re-check exo/TB5 RDMA Mac-clustering maturity in 2027 (would change the top-rung calculus)  [hardware][research]  (2026-06-13)
- Reserve a **planning/spec-authoring generation category** in `distill-datagen-pipeline` (teacher = Claude producing real Artemis specs/ADRs) so the eventual local student can be evaluated as a PLANNER, not just a coder — supports the D-plan-1 "fully-local distilled planner" end-state  [capability][aci]  (2026-06-13)

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



## Triaged (pulled into SP0 / requirements)

_Item → where it went (REQUIREMENTS.md section / ADR / spec). Keeps the trail._

- **Camera/vision module** (2026-06-09) → dedicated discussion 2026-06-11 **reframed** it from a home-cameras spoke into a **vision build-assistant** (overhead desk-vision HUD + voice-first guided builds) → **ADR-014** (DESIGNED, deferred; capability ladder Rung 0→3). Mini-local, NOT a home-cameras spoke, no ACI Phase-4. Full design + research: `docs/findings/desk-vision-hud-deep-dive.md`.

<!-- - Morning email briefing → REQUIREMENTS.md §Assistant; spec: docs/changes/morning-brief.md -->
