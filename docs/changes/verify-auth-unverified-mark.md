---
spec: verify-auth-unverified-mark
status: ready
token_profile: lean
autonomy_level: L5
coder_effort: medium
---

# Spec: Honest "auth-unverified" marking for credentialed capabilities (Light)

## Prerequisites
- **`capability-metadata` (build FIRST).** It defines the `auth_status` field on `Skill`, in SKILL.md frontmatter (`write_skill_md`), the `_read_skill` default, and the `InstalledCard`/`CapabilitySummary` DTOs. This spec adds ONLY the logic that *sets* `auth_status` — it no longer defines the field (consolidation, 2026-07-03).

## Intent
A network+secret capability is verified at build time WITHOUT its secrets (the verify sandbox gets an
egress allowlist via `sandbox_policy.json` but never a credential — only the invoke path injects secrets;
owner decision: keep it that way, the "credential only reaches an approved, deliberately-invoked
capability" invariant is load-bearing). So a promoted capability that declares `secrets` had its
authenticated path UNVERIFIED. This spec records that honestly as a status field on the capability and
surfaces it at promote, and flips it to `verified` the first time a real credentialed invoke succeeds.
No new secret or egress flow — this is a status/labeling change only.

## Key decisions
- **Three-state enum `auth_status` on the capability**, persisted in SKILL.md frontmatter:
  `not-required` (declares no secrets → verify fully exercised it), `unverified` (declares secrets →
  verify ran credential-less), `verified` (a real credentialed invoke has since succeeded). Legacy
  SKILL.md without the key reads back as `not-required` (backward-compatible, mirrors how `inputs` is
  treated).
- **Computed at promote**, not at author/stage: `"not-required" if not draft.secrets else "unverified"`.
  (Staging SKILL.md is unchanged — `write_skill_md` gets a defaulted param, so `stage` needs no edit.)
- **First-invoke write-back is in this spec but is the one separable task** (Task 4). It's a small store
  method + one call in the invoke success path. If the owner wants the absolute-minimum labeling-only
  version, Task 4 can be dropped without affecting Tasks 1–3.
- **Brain-only.** The client shows the promote message (`askStore.ts` composes `… — built & verified.`).
  This spec adds `auth_status` to the `InstalledCard`/`CapabilitySummary` DTOs so the client CAN render an
  honest suffix, but the client TS change (append e.g. "network auth confirmed on first use" when
  `auth_status == "unverified"`) is a **small follow-up**, out of scope here.
- **No security review, no ADR, no cross_model_review**: introduces no new credential or egress flow;
  it only records and surfaces a verification-status field. Verify stays credential-less exactly as today.

## Gotchas / edge cases
- `write_skill_md` currently takes a fixed keyword set; add `auth_status: str = "not-required"` with a
  default so the `stage` caller is untouched and only `promote` passes a computed value.
- `Skill.auth_status` must default so `_read_skill` on a legacy library SKILL.md (no key) doesn't fail —
  use `meta.get("auth_status", "not-required")`.
- The write-back (Task 4) must only fire on a **successful credentialed** invoke: `exit_code == 0` AND
  `skill.secrets` non-empty AND current `auth_status == "unverified"`. Never downgrade; never write on a
  no-secret capability. Rewrite SKILL.md in place preserving body + all other frontmatter (use
  `read_skill_md` → set key → `write_skill_md`); do not bump `version`.
- `mark_auth_verified` must be a no-op (not an error) if the capability is missing or already `verified`
  — the invoke path should never fail because of a status write-back.

## Tasks
<!-- The `auth_status` FIELD (model + frontmatter + `_read_skill` default + DTOs) is provided by the
     `capability-metadata` prerequisite. This spec adds ONLY the logic that SETS it. -->
1. Compute + persist `auth_status` at promote. In `src/artemis/capabilities/store.py` `promote`: compute
   `auth_status = "not-required" if not draft.secrets else "unverified"` and pass it into the existing
   `write_skill_md(...)` call and the returned `Skill(...)`, overriding the metadata default. (The field,
   frontmatter round-trip, `_read_skill` default, and DTO surface already exist from `capability-metadata`.)
   — files: src/artemis/capabilities/store.py, tests/capabilities/test_store.py — done when: promoting a
   draft with a non-empty `secrets` list yields a library SKILL.md with `auth_status: unverified` and
   `store.get(name).auth_status == "unverified"`; a no-secret draft yields `not-required`.
2. First-invoke write-back. In `src/artemis/capabilities/store.py`, add
   `mark_auth_verified(self, name: str) -> None` — read the library SKILL.md; if it is missing or its
   `auth_status` is not `"unverified"`, return silently; else rewrite it with `auth_status="verified"`
   (preserve body + all other frontmatter, do not bump version). In `src/artemis/capabilities/invoke.py`,
   in the successful-invoke path (`confirm_invoke`, after `FetchSandbox.run` returns with `exit_code == 0`),
   if `skill.secrets` is non-empty call `capability_store.mark_auth_verified(skill.name)` (best-effort —
   must never raise into the invoke flow). — files: src/artemis/capabilities/store.py,
   src/artemis/capabilities/invoke.py, tests/capabilities/test_store.py, tests/capabilities/test_invoke.py
   — done when: a successful credentialed invoke flips `auth_status` `unverified → verified`; a failed
   (non-zero) invoke leaves it `unverified`; a no-secret capability is untouched; `mark_auth_verified` on a
   missing/already-verified capability is a silent no-op.

## Files to touch
- src/artemis/capabilities/store.py — compute `auth_status` at promote; `mark_auth_verified`
- src/artemis/capabilities/invoke.py — best-effort write-back on successful credentialed invoke
- tests: test_store.py, test_invoke.py
<!-- skill_md.py / types.py / capability_routes.py are NO LONGER touched here — the field lives in capability-metadata. -->

<!-- NOTE: the Key-decisions bullets above still describe the field being *added* here; that part is
     superseded by the capability-metadata consolidation (2026-07-03) — the field is defined there,
     this spec only sets it. The compute-at-promote + first-invoke write-back logic is unchanged. -->

## Acceptance criteria
- [ ] Promote a capability declaring `secrets=["GMAIL_APP_PASSWORD"]` → library SKILL.md has
      `auth_status: unverified`; `InstalledCard.auth_status == "unverified"`.
- [ ] Promote a capability with `secrets=[]` → `auth_status: not-required`.
- [ ] A pre-existing library SKILL.md with no `auth_status` key → `store.get(name).auth_status == "not-required"` (no crash).
- [ ] `GET /app/capabilities` returns `auth_status` on each `CapabilitySummary`.
- [ ] A successful credentialed invoke of an `unverified` capability → its SKILL.md becomes `verified`; body + version unchanged.
- [ ] A failed credentialed invoke → stays `unverified`. `mark_auth_verified` on missing/already-verified → no-op, no raise.
- [ ] `uv run mypy` clean; `uv run ruff check` clean; `uv run pytest -q` green.

## Commands to run
- `uv run mypy`
- `uv run ruff check src/ tests/ && uv run ruff format --check src/ tests/`
- `uv run pytest -q`
