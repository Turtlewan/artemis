---
spec: m2-d-security-gate
status: ready
token_profile: balanced
autonomy_level: L2
---

# Spec: M2-d — apex-security threat-model gate (REVIEW) — must pass before M3/M4 build the sensitive stores

**Identity:** A REVIEW-only gate (no production code) that runs the apex-security threat-model pass over the M2 security wall (M2-a/b/c) against ADR-005's five residual risks, producing a sign-off record + any required hardening follow-up specs; M3/M4 are BLOCKED until this gate passes.
→ why: see docs/technical/adr/ADR-005-owner-key-broker.md § "apex-security threat-model gate" + § "Build-time spikes" · docs/research/owner-key-brain-architecture.md § "Residual risks → apex-security pass focus".

<!-- Split rule: ONE logical phase (a review gate). It produces ONE durable artifact (the gate record) + optionally spawns follow-up hardening specs (which are separate specs, not files here). No source files. Within the rules. This is deliberately a REVIEW task per the M2 brief, not a build task. -->

## Assumptions
- M2-a (key-broker), M2-b (scope model + data-layer wall), M2-c (broker client + mlock + Tier-0 + auto-login) are all built and their off-hardware acceptance criteria pass; the gated on-hardware tasks (SE `.userPresence`, SQLCipher `cipher_memory_security`, mlock, auto-login+FileVault boot, macOS-26 daemon-restriction re-check, encrypted-volume mount/unmount lifecycle (ADR-007)) have been RUN on the Mini and recorded in `docs/handoff/`. → impact: Stop (the gate reviews real built+spiked artefacts, not drafts; an unrun spike is itself a gate finding).
- This gate is invoked via the `apex-security` skill (planning-mode review), not a code change. The output is a written record + a pass/conditional-pass/fail verdict + (on conditional/fail) follow-up hardening specs into `docs/changes/`. → impact: Stop (no source edits; the gate's job is to ASSESS and ROUTE, per the apex-security BLOCK/FLAG model).
- The gate is BLOCKING: M3 (document RAG corpus) and M4 (memory engine) — which build the sensitive stores born encrypted under this key model — must not start until this gate returns pass (or conditional-pass with the conditions tracked). → impact: Stop (ADR-005: the gate "fires at M2 before any sensitive store is built"). The build-order prerequisite is explicit: M2-d is a hard predecessor of every M3 and M4 spec (deepest focus = prompt-injection DEK exfiltration).

Simplicity check: considered folding the security review into each of M2-a/b/c — rejected: ADR-005 mandates a single consolidated threat-model gate across the whole wall before M3/M4 (the cross-cutting risks — e.g. DEK exfiltration — span all three specs and can only be judged together). A dedicated gate spec is the decided, minimal form.

## Prerequisites
- Specs that must be complete first: **M2-a, M2-b, M2-c** (built; off-hardware green; on-hardware spikes run + recorded). This gate is a blocking prerequisite OF M3-* and M4-* (they must list M2-d as a prerequisite; M3/M4 build order may not begin until this gate's verdict is PASS or CONDITIONAL-PASS).
- Environment setup required: the `apex-security` skill; access to the M2 source + the handoff records of the on-hardware spikes.

## Files to Change
| File | Operation | Notes |
|------|-----------|-------|
| /Users/artemis-build/artemis/docs/technical/security/M2-wall-threat-model.md | create | the gate record: each residual risk → assessment → BLOCK/FLAG/accepted → verdict |

## Tasks
- [ ] Task 1: Run the apex-security threat-model pass over the M2 wall — files: `/Users/artemis-build/artemis/docs/technical/security/M2-wall-threat-model.md` — invoke the `apex-security` skill against M2-a/b/c. For EACH of ADR-005's five residual risks, record: the attack, the as-built mitigation, the verdict (BLOCK / FLAG / accepted), and any required follow-up. The five (verbatim from the research doc) MUST each be addressed:
  1. **Prompt-injection DEK/data exfil from the live brain (the core risk)** — verify: the DEK lives only in M2-c's mlock'd buffer, never logged/disk/swap; tool I/O is scoped; egress filtering exists or is a tracked follow-up; all tool/web/file content is treated as untrusted data (cross-ref brain.md § Security CaMeL/dual-LLM — confirm whether M2 needs an interim egress guard or it is M3+ tracked).
  2. **`.userPresence` vs `.biometryCurrentSet` semantics on the Mini-side key** — verify: the M2-a Task 9 on-hardware result (did `.userPresence` degrade to login-unlock on the no-Touch-ID Mini?); if it degraded, confirm the proof-gated fallback was adopted.
  3. **Proactive-key scope creep** — verify: the Tier-0 `proactive` scope (M2-c) is provisioned EMPTY, its key policy is the distinct `proof_required=false` boot-unwrappable policy (no phone proof, M2-a), and there is an explicit audit (ADR-006 line 25) that the `proof_required=false` proactive key decrypts ONLY the minimised Tier-0 corpus — NEVER any owner-private/general data; confirm the M6 minimised-corpus seam can't widen it silently.
  4. **Phone-as-authority compromise/loss** — verify: enrol/de-enrol/rotate/escrow flows exist or are tracked follow-up specs (M2 ships pair/counter/replay-block; confirm de-enrol + rotate are at least seamed); a fully-compromised enrolled phone can mint proofs → confirm phone-loss is treated as key-compromise with a remote de-enrol path planned.
  5. **macOS 26.x daemon/data-protection-keychain status (version-dependent)** — verify: the on-hardware re-check (M2-c Task 8c) confirms the restriction still holds on the running macOS 26 build (and thus the LaunchAgent + auto-login design is still required, or if lifted, auto-login can be dropped — record either way).
  Also confirm (i) the IPC wall (peer-uid + code-signing, M2-a) rejects the build-agent user; (ii) the M2-b owner-auth model (unlocked-session ⇒ owner) has no unauthenticated path to owner scope; (iii) the per-scope encrypted-volume mount (M2-a/ADR-007) mounts ONLY after a verified proof and UNMOUNTS on lock/idle/exit — a mounted volume left attached after lock is a wall breach. — done when: the record addresses all five risks + the IPC wall + the owner-auth model + the volume mount/unmount lifecycle, each with an explicit verdict.

- [ ] Task 2: Issue the gate verdict + route follow-ups — files: `/Users/artemis-build/artemis/docs/technical/security/M2-wall-threat-model.md` (same file) — conclude with a single verdict: **PASS** (M3/M4 unblocked), **CONDITIONAL-PASS** (M3/M4 may proceed with listed conditions tracked as follow-up specs in `docs/changes/`), or **FAIL** (M3/M4 BLOCKED until the listed hardening specs land). For any BLOCK/CONDITIONAL finding, write a concrete follow-up spec stub into `docs/changes/` (e.g. `m2-hardening-<topic>.md`) naming the exact files/changes — do NOT fix in this gate (planning routes, coding fixes). Record the verdict date + the reviewed commit SHAs of M2-a/b/c. — done when: the file ends with one of {PASS, CONDITIONAL-PASS, FAIL}, the reviewed SHAs are recorded, and every CONDITIONAL/FAIL finding has a corresponding `docs/changes/` follow-up stub.

## Permissions

The following actions will run autonomously during build.
Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Create | /Users/artemis-build/artemis/docs/technical/security/M2-wall-threat-model.md, /Users/artemis-build/artemis/docs/changes/m2-hardening-*.md (only if findings require) |
| Modify | (none) |
| Delete | (none) |

### Commands
| Command | Purpose |
|---------|---------|
| (invoke the `apex-security` skill) | Run the threat-model pass |
| `git rev-parse --short HEAD` | Record the reviewed commit SHA |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | docs/technical/security/M2-wall-threat-model.md, docs/changes/m2-hardening-*.md (if any) |
| `git commit` | "docs: M2-d apex-security threat-model gate record + follow-ups" |

### Environment Access
| Variable | Purpose |
|----------|---------|
| (none) | Review only |

### Network
| Action | Purpose |
|--------|---------|
| (none) | Review only |

## Specialist Context
### Security
This IS the security specialist task — the consolidated apex-security gate ADR-005 mandates before any sensitive store (M3/M4). It is BLOCKING. The deepest focus is residual risk #1 (prompt-injected DEK exfiltration from the live brain) per ADR-005's "⭐ Deepest apex-security focus". The gate does not write production fixes; it assesses and routes hardening to `docs/changes/`.

### Performance
(none — review)

### Accessibility
(none — review)

## Documentation
| Doc type | File | Action |
|----------|------|--------|
| Security | docs/technical/security/M2-wall-threat-model.md | Write the gate record (the five risks + IPC wall + owner-auth, verdict, reviewed SHAs) |
| Follow-up specs | docs/changes/m2-hardening-*.md | Write only if findings require hardening |

## Acceptance Criteria
- [ ] The gate record addresses all FIVE ADR-005 residual risks + the IPC peer-uid/code-signing wall + the M2-b owner-auth model + the encrypted-volume mount/unmount lifecycle (ADR-007) → verify: each has an explicit BLOCK/FLAG/accepted verdict in the file.
- [ ] The on-hardware spike results (SE `.userPresence`, SQLCipher `cipher_memory_security`, mlock, auto-login+FileVault, macOS-26 daemon re-check, encrypted-volume mount/unmount lifecycle) are cited from the handoff records → verify: each spike is referenced with its result, not left "unrun".
- [ ] The file ends with one verdict ∈ {PASS, CONDITIONAL-PASS, FAIL} + the reviewed M2-a/b/c commit SHAs → verify: present.
- [ ] The verdict record states explicitly that M3-* and M4-* remain BLOCKED until this gate is PASS/CONDITIONAL-PASS, and is referenced as a prerequisite by the M3/M4 specs → verify: the block statement is present in the file.
- [ ] Every CONDITIONAL/FAIL finding has a matching `docs/changes/m2-hardening-*.md` stub → verify: one stub per open finding; PASS ⇒ none required.

## Progress
_(Coding mode writes here — do not edit manually)_
