# Handoff — 2026-07-04 (session 11 cont., AFK coding): model-role roster + hardening

Owner AFK ~1.5h; greenlit "finish the AFK run." Shipped 7 commits (2 hardening + AGENTS.md + the
4-spec ADR-049 roster) on `v2-rebuild`, all Codex-built + host-verified + committed. What changed →
`git log`; state → `docs/status.md`. This handoff = what the build learned.

## Decisions Made
- **ADR-049 written mid-session** (roles-in-code / models-in-config / owner-toggleable). Owner
  clarifications folded live: `forge_author` role added (build-by-chat model is toggleable too);
  a distinct `selector` role split from `loop_driver` (so upgrading the future driver tier doesn't
  silently raise every classify/select call's cost).
- **Both registry security BLOCKs are "safe-by-coincidence → safe-by-rule" fixes** (autonomous
  ruling): no-tools is now structural provider-eligibility (`_NO_TOOLS_PROVIDERS`), not a property
  of the current provider; the persisted roster file is re-validated fail-closed on load, never
  trusted. Same species of finding, both folded pre-build.
- **Cache tokens kept as distinct `Usage` fields** (autonomous, from ai-systems FLAG): folding them
  into `prompt_tokens` would have overstated Claude's cost vs GPT in exactly the comparison the meter
  exists for. Rippled a pre-build amendment into the (queued) metering spec — build-order independent
  via getattr-default.
- **Build-time crew reassigned by owner** (status.md `apex_model_roles`): reason=fable/opus,
  orchestrate=sonnet (AFK hosts), draft=opus, code=codex. Not client-toggleable (APEX config).
- **Panel split 3A/3B**: only the data layer (3A) built AFK; the visible Models UI (3B) is NOT
  drafted — held for owner (it's the one piece with visual judgment).

## Specialist Flags
- **Codex-as-reader is viable** (`docs/findings/codex-no-tools-research-2026-07-04.md`): a specific
  config strips shell+web tools verifiably (mock-payload 13→4 tools, live injection → text-only).
  Version-pinned (0.141.0) — admit to `_NO_TOOLS_PROVIDERS` ONLY behind the two-layer smoke in that
  doc. This is the path to cheaper-GPT readers.
- **usage-parse live-smoke PASSED** (`ARTEMIS_LIVE_SMOKE=1`): real codex `--json` token counts flow
  through — the one unconfirmable-from-source risk (field names) is verified. The meter shows real
  numbers, not zeros.
- **New benign warning**: `HTTP_422_UNPROCESSABLE_ENTITY` deprecation from FastAPI/Starlette (upstream
  rename to `_CONTENT`). Trivial one-line cleanup in `model_routes.py` when convenient; not a defect.
- Scoped-out composition roots (CLI ingress, `reachout/web_tool.py` synth) still bind hardcoded
  ports — deliberately deferred to the agent-loop arc (web_tool synth rebinding is a behavior change).

## Blocked Actions
- none

## What's Next (discoveries)
- **Roster is live but has no UI** — brain endpoints + client data layer ship; the Models PANEL
  (part 3B, status.md Pending #13) is the visible piece. Until then, roster edits are hand-JSON in
  the data dir (safe: fail-closed load) or "tell an open session."
- **Agent-loop arc is UNBLOCKED except for two owner decisions** (status.md Open Q): loop driver tier
  + escalation ladder. Recommended: sonnet drives / haiku grunt-work; in-family Sonnet→Opus
  escalation; independent no-tools haiku judge. These block spec drafting.
- **Brain died once mid-session (exit 127, no traceback)** — restarted; watch item filed. If it
  recurs, add a supervisor to `scripts/launch-artemis.ps1`.
- **`git mv` fails on a not-yet-committed promoted spec** — use plain `mv` + `git add` when archiving
  a spec that was created (untracked) this session. Minor dispatch-mechanics note.
