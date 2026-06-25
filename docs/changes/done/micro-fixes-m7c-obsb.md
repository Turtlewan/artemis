---
spec: micro-fixes-m7c-obsb
status: ready
token_profile: lean
autonomy_level: L3
---

# Spec: micro-fixes — M7-c tldextract deprecation + OBS-b codex tier mapping

**Identity:** Two 1-line fixes to already-shipped modules surfaced as follow-ups in the 2026-06-24 handoff (continuation 3).

## Intent

1. **M7-c** — `tldextract` 5.3.1 deprecates `.registered_domain`; replace with `.top_domain_under_public_suffix` in `curiosity/research.py` to silence ~18 DeprecationWarnings per test run and future-proof against removal.
2. **OBS-b** — `tier_for` in the cost model predates the `codex` adapter; `codex` currently maps to `LOCAL` (else-branch), so codex tokens aren't tagged as `SUBSCRIPTION` quota in `usage_summary`. Add `"codex"` → `SUBSCRIPTION` alongside `"claude-cli"`.

## Key decisions

- `top_domain_under_public_suffix` is the tldextract 5.3.1 recommended replacement for `registered_domain`; semantically equivalent for Artemis's URL-dedup use case (both return `example.com` from `sub.example.com`).
- `codex` maps to `SUBSCRIPTION` (not `CLOUD_API`) — it runs on the ChatGPT subscription (no per-token metered cost); same tier as `claude-cli` per ADR-022/ADR-026.
- Flat-rate SUBSCRIPTION cost is 0 in the `CostModel` either way, but the tier tag matters for `usage_summary` quota-signal reporting (OBS-b's purpose).

## Gotchas / edge cases

- The `registrable_domain` function in `research.py` may be used in more than one place — grep before patching.
- `tier_for` likely lives in `src/artemis/obs/cost.py`; confirm the exact file before editing.
- Both fixes must pass `mypy --strict src` and the full test suite — neither changes behaviour, only corrects a label and silences a warning.

## Tasks

1. Fix `.registered_domain` → `.top_domain_under_public_suffix` — files: `src/artemis/curiosity/research.py` — grep for `registered_domain` in the file, replace every occurrence with `top_domain_under_public_suffix`. — done when: `uv run python -W error -c "from artemis.curiosity import research"` exits 0 (no DeprecationWarning); `uv run mypy --strict src` exits 0.

2. Add `"codex"` → `SUBSCRIPTION` in tier mapping — files: `src/artemis/obs/cost.py` (or wherever `tier_for` is defined; grep `tier_for` in `src/artemis/obs/`) — in the `tier_for` function/mapping, add `"codex"` to the same branch/key as `"claude-cli"` (both → `SUBSCRIPTION`). — done when: `tier_for("codex") == ModelTier.SUBSCRIPTION` (or equivalent); `uv run mypy --strict src` exits 0.

3. Verify — run `uv run pytest -q` and `uv run ruff check .` → done when both exit 0.

## Files to touch

- `src/artemis/curiosity/research.py` — 1-line replacement (`.registered_domain` → `.top_domain_under_public_suffix`)
- `src/artemis/obs/cost.py` (confirm path) — 1-line addition (`"codex"` → `SUBSCRIPTION`)
