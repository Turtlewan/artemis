---
spec: webtool-eval-calibration
status: ready
token_profile: balanced
autonomy_level: L2
coder_model: codex
coder_effort: high
---

# Spec: Web-tool eval — model-fit calibration sweep

**Identity:** Run the scoring harness across a configurable list of (reader primary/escalate, synth) model line-ups by constructing `WebTool` instances with different model params, and emit a comparison table (per-rubric scores + cost/latency per line-up) to empirically fit models to roles. Thin composition over the harness — NO production change.
→ why: see docs/technical/adr/ADR-038-webtool-eval-and-conflict-adjudication.md

## Assumptions
- `WebTool.__init__` already accepts `reader_models: tuple[str,str]` (primary, escalate) + `synth_model: str | None` — swapping line-ups is pure construction; no source edit → impact: Stop if false (verified in web_tool.py)
- The harness (webtool-eval-harness) exposes a reusable "run one line-up over the corpus → scored result" entrypoint the sweep can call per line-up → impact: Caution (if only a CLI exists, import its run function)
- Line-ups are supplied as config (a small json/py list), not hardcoded, so the owner tunes candidates without code edits → impact: Low

Simplicity check: considered folding the sweep into runner.py behind a `--lineups` flag — rejected to keep runner single-line-up and file-disjoint from this spec; calibration is a thin separate composer.

## Prerequisites
- Specs complete first: webtool-eval-harness (runner, judge, tracing, report), webtool-eval-corpus (transitive)
- Environment: `uv sync`; OAuth `claude` login for judge + candidate models; offline replay corpus present

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| evals/webtool/lineups.py | create | `Lineup` model (reader_primary, reader_escalate, synth_model, label) + `load_lineups(path)`; default candidate list |
| evals/webtool/calibration.py | create | sweep: for each `Lineup` build a `WebTool`, run the harness over the frozen corpus, collect scored result; CLI `python -m evals.webtool.calibration` |
| evals/webtool/corpus/lineups.json | create | editable candidate line-up list (data, not code) |
| tests/evals/test_calibration_smoke.py | create | non-network smoke: 2 stub line-ups over tiny fixtures → comparison table shape |

## Tasks
- [ ] Task 1: Line-up config model + loader + judge-collision guard — files: evals/webtool/lineups.py, evals/webtool/corpus/lineups.json — done when: `load_lineups(path)` returns `list[Lineup]`; each `Lineup` = {label, reader_primary, reader_escalate, synth_model|null}; default json has ≥3 candidate line-ups that DO NOT include the judge model (Opus) as any reader/synth — e.g. `haiku→sonnet / codex`, `haiku→haiku / sonnet`, `sonnet→sonnet / codex`; and `load_lineups` raises (or the sweep rejects) any line-up whose reader_primary/reader_escalate/synth_model equals the judge model-id (`opus`), because scoring a candidate with a judge of the same family is a self-preference-bias violation (ADR-038 dec 3).
- [ ] Task 2: Calibration sweep + comparison table — files: evals/webtool/calibration.py — done when: `uv run python -m evals.webtool.calibration --corpus evals/webtool/corpus --lineups evals/webtool/corpus/lineups.json --out <dir>` runs the harness once per line-up (constructing `WebTool(reader_models=(primary,escalate), synth_model=...)`) and writes a table with one row per line-up × columns {per-rubric reader score, per-rubric synth score, per-category pass-rate (with per-category N annotated), total tokens, total cost est, mean latency}; the report carries a caveat that categories with N<10 are directional only (a 50-query corpus has categories as small as 4 — single-run small-N is not statistically robust).
- [ ] Task 3: Non-network calibration smoke — files: tests/evals/test_calibration_smoke.py — done when: `uv run pytest tests/evals/test_calibration_smoke.py -q` passes offline stubbing at the ModelPort layer over 2 line-ups; asserts the comparison table has one row per line-up, all rubric columns populated, AND each row's recorded reader_primary/reader_escalate/synth_model matches its input `Lineup` (guards against the sweep silently reusing one WebTool for every row).

## Wave plan
Wave 1: [Task 1] | Wave 2: [Task 2] | Wave 3: [Task 3]

## Permissions
### File Operations
| Action | Paths |
|--------|-------|
| Create | evals/webtool/lineups.py, calibration.py, corpus/lineups.json, tests/evals/test_calibration_smoke.py |
| Modify | (none) |
| Delete | (none) |

### Commands
| Command | Purpose |
|---------|---------|
| `uv run python -m evals.webtool.calibration --corpus evals/webtool/corpus --lineups evals/webtool/corpus/lineups.json --out <dir>` | run the model-fit sweep |
| `uv run pytest tests/evals/test_calibration_smoke.py -q` | offline smoke |
| `uv run mypy src evals tests` | typecheck (standardized scope) |
| `uv run ruff check src evals tests` | lint |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | evals/webtool/lineups.py calibration.py corpus/lineups.json tests/evals/test_calibration_smoke.py |
| `git commit` | "feat: web-tool eval model-fit calibration sweep" |

### Environment Access
| Variable | Purpose |
|----------|---------|
| (OAuth `claude` login) | judge + candidate reader/synth models during a real sweep |

### Network
| Action | Purpose |
|--------|---------|
| model calls during a real sweep | judge + candidate models; page fetch is REPLAY (no network) |

## Specialist Context
### Security
Reuses the harness's replay + quarantine untouched. No new egress or model seam; only different model-id strings passed to the existing constructor.

### Performance
N line-ups × full corpus × multi-pass judge = the most expensive artifact here. Standalone CLI, never in default pytest. Reuses per-stage tracing so cost/latency per line-up is directly comparable.

### Accessibility
(none)

## Documentation
| Doc type | File | Action |
|----------|------|--------|
| Inline | evals/webtool/lineups.py, calibration.py | docstrings on public API |
| ADR | docs/technical/adr/ADR-038-webtool-eval-and-conflict-adjudication.md | referenced |

## Acceptance Criteria
- [ ] Line-ups are data-driven → verify: editing corpus/lineups.json changes the swept set with no code edit
- [ ] Judge-collision guard → verify: a line-up naming the judge model (`opus`) as reader/synth is rejected by `load_lineups`/the sweep (unit-asserted)
- [ ] Small-N caveat present → verify: the comparison report annotates per-category N and flags N<10 categories as directional
- [ ] Sweep builds distinct WebTools → verify: each row's reader/synth model-ids in the report match its `Lineup` (asserted in Task 3 smoke)
- [ ] Comparison table complete → verify: one row per line-up with per-rubric reader+synth scores, per-category pass-rate, tokens/cost/latency
- [ ] Offline smoke green → verify: `uv run pytest tests/evals/test_calibration_smoke.py -q` passes with no network
- [ ] Typecheck + lint → verify: `uv run mypy evals tests/evals` + `uv run ruff check evals tests/evals` exit 0

## Progress
_(Coding mode writes here — do not edit manually)_
