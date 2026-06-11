# Full-Corpus Quality Sweep — Synthesis (2026-06-10/11)

11 parallel fresh-context reviewers (Fable 5) swept all ~60 ready specs, 13 ADRs, architecture/module
docs, and the research corpus. Full per-area reports live in this folder. This file is the synthesis.

## Verdict

**The corpus is NOT batch-handoff-ready.** 67 BLOCK findings would each produce a broken or wrong
build under a literal executor (DeepSeek V4-Flash). The designs are sound — the failures are
overwhelmingly *interface fictions between specs drafted in separate sessions*, not design gaps.

## Counts by area

| Area | Report | BLOCK | UPGRADE | FLAG | RESEARCH |
|------|--------|-------|---------|------|----------|
| M0 foundation + M1 brain | m0-m1-foundation-brain.md | 11 | 6 | 14 | 5 |
| M2 security + OBS + DR | m2-obs-dr-security.md | 6 | 4 | 14 | 3 |
| M3 knowledge + M4 memory/entity | m3-m4-knowledge-memory.md | 4 | 7 | 11 | 4 |
| M5 voice + M6 heartbeat | m5-m6-voice-heartbeat.md | 6 | 7 | 14 | 5 |
| M7 teacher + CAP distill | m7-cap-teacher-distill.md | 5 | 6 | 12 | 3 |
| Calendar + GATE | cal-gate.md | 12 | 8 | 12 | 5 |
| Gmail | m8-gmail.md | 6 | 5 | 9 | 3 |
| Productivity | m8-productivity.md | 7 | 10 | 18 | 5 |
| CLIENT | client.md | 7 | 6 | 16 | 4 |
| Cross-corpus consistency | cross-corpus-consistency.md | 3 | 3 | 10 | 2 |
| Research currency | research-currency.md | — | — | — | (8-axis verdicts) |
| **Total** | | **67** | **62** | **130** | **39** |

## The six cross-cutting themes

1. **Interface fiction (dominant — causes most BLOCKs).** Spec B consumes an interface spec A never
   defines: `ModelPort` has no streaming shape (M1-b) and no `temperature` (DR-c) and no
   cloud-detection capability (M7-a2); `CalendarClient` has no write methods (CAL-b/c); GATE-b calls
   `ActionStagingService.list_pending()` which GATE-a never defines; M6-c's `pre_tick_steps` patches a
   runner M6-a never seams; M3-d needs `PageImage` no spec produces; M4-c must edit `gateway.py` but
   scope-lock excludes it; M8-b2 needs `GmailApiPort` thread methods b1 lacks. **Fix pattern: a frozen
   shared-contracts pass, then per-spec amendments.**

2. **The GATE approval loop (worst single design bug).** GATE-a `approve()` re-dispatches the gated
   tool through the ToolRegistry; the entrypoint re-runs the classifier and re-stages — owner-approved
   actions can NEVER execute, and CAL-c even stages the approve tool itself (recursion). Needs an
   explicit staging-bypass token on the re-dispatch path.

3. **Security posture sound, leaks at seams.** Raw email subject/snippet reaches privileged models via
   M8-b1 tool returns and M8-b2's urgency payload (contradicting the dual-LLM quarantine); M6-c's
   `held.json` persists full message bodies plaintext; M7-a1 `set_status` re-signs unverified recipes
   (tamper-laundering); M8-d-c2 graduation can silently demote an owner-approved recipe back to
   CANDIDATE; `.gitignore` as specced does not cover the secret-bearing `config/.env.<slot>` files.

4. **Acceptance criteria that ship green on broken behaviour.** DR-b egress test only covers
   exact-host match (all subdomains denied in prod); CAL-a fakes hide the missing `showDeleted=true`
   (deletions never propagate); `pytest -m integration` exits 5 with zero tests and aborts pipeline.sh.

5. **Governing-doc drift (cross-corpus).** ROADMAP.md — the designated build authority — still says
   "32 specs READY, spokes not specced" (actual: 60, full M8/CAL/GATE/M4-d wave); overview.md/
   calendar.md still describe gated writes as TAKES_ACTION recipes (superseded by ADR-012);
   brain.md + data-model.md say memory extraction "runs on the teacher" — privacy-load-bearing
   contradiction (it's the local `sensitive_reasoner`).

6. **Executor-readiness gaps.** M8-d-c2 contains "Wait — simpler approach" self-revisions and a
   twice-defined `CaptureService` (a literal executor will build the wrong version); distill-datagen
   uses `&&` and bare `claude` subprocess calls that fail on Windows PowerShell 5.1. DeepSeek V4-Flash
   itself: strong coder, but Terminal-Bench 56.9% and community-reported lazy execution — research GAP
   on its executor profile; a spec-lint pass against that profile is recommended pre-handoff.

## Research currency (8 axes)

CURRENT: local model tier · embeddings/LanceDB (pin SDK at M3-a) · M5 Mini timing (late Aug–Oct 2026,
prices rising — **note: agent assessed this strengthens buy-M4-Pro-64GB-now over waiting; owner
decision was WAIT — worth a re-look**) · search providers (re-verify Jina free-token allowance).
STALE: voice stack (Kokoro no longer unambiguous — Qwen3-TTS/CosyVoice 3 in mlx-audio; Sortformer
diarization; SmartTurn EOU; SpeechAnalyzer-vs-Parakeet conflict unresolved).
GAP: Docling (unpinned, Heron vs Granite-Docling pipeline undecided, before M3-a) · DeepSeek V4-Flash
executor profile (shapes spec authoring + lint pass).
PARKED updates: Pipecat-or-neither (Wyoming out) · Litestream v0.5 LTX rewrite postdates parked note ·
mlx-tune now claims native DPO/GRPO (weakens "DPO is CUDA-only" GPU-box driver).

## Recommended remediation sequence

1. **Contracts freeze (1 doc + targeted amendments):** resolve every cross-spec interface fiction in
   one pass — fix the *defining* spec, then patch consumers. Covers the majority of the 67 BLOCKs.
2. **Design-bug fixes:** GATE approval bypass · M6-c seam rework · quarantine leak closure (M8-b1/b2,
   M6-c held.json) · M7-a1 verify-before-resign · M8-d-c2 clean rewrite.
3. **Doc-drift wave:** ROADMAP rewrite (build authority), overview/brain/data-model/calendar.md
   alignment to ADR-012/013 + local-extraction privacy line.
4. **Research refreshes (build-impact order):** DeepSeek V4-Flash executor profile + spec lint →
   Docling pin (pre-M3-a) → voice-stack refresh (pre-M5).
5. **UPGRADE folding:** security-relevant first (DNS-rebinding TOCTOU, redaction substring bug,
   backfill cursor ordering), the rest opportunistically during amendments.
