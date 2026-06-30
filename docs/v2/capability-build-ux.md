# Capability-Build UX — design note

_Status: design discussion (2026-06-30), not yet built. Captures how "building a capability" should
feel as a gated conversation in the Ask chat. Owner-driven; refine before speccing._

## Context

The capability forge works end-to-end (author → sandbox → promote; fix in commit `02e7506`, the
author-contract + self-correcting retry). But today it's **one-shot and autonomous**: a goal goes in
via a script, the model guesses everything, and it auto-promotes. For real capabilities (e.g. the
`email_intake` test build), that's wrong — the agent should ask, plan, and confirm. This note is the
target experience.

## The build conversation (gated, multi-turn)

A build becomes a conversation in the Ask chat with **two human gates** (plan-before-build,
promote-after-verify):

```
You:      build me an email module that pulls payment/interview/travel info...
Artemis:  [clarify]  A few things before I build:
            • Which account — Gmail (IMAP) or something else?
            • I'll need an app-password to read it — okay to set that up?
            • Anything beyond payment / interview / travel?
You:      gmail, yes, also add "security" alerts
Artemis:  [PLAN CARD]  email_intake — pulls Gmail via IMAP, classifies into
            payment·interview·travel·security·general, exposes EmailRecord for
            other modules. Secrets: IMAP app-password.
            [ Build it ]  [ Adjust ]                       ← GATE 1
You:      (Build it)
Artemis:  [STATUS]  Authoring… → Testing in sandbox… → ✓ Verified (3/3 pass)
          [RESULT CARD]  email_intake built & verified.
            [ Add to my capabilities ]  [ Discard ]        ← GATE 2
You:      (Add)
Artemis:  ✓ Added. It's now a node on your map; future modules can use it.
```

The gates fix the "silently guesses + auto-promotes" problem.

## UI adjustments

The Ask chat shifts from pure text bubbles → a chat that can render **structured cards + action
buttons**. New message variants (same Ask popup, no new screen):

1. **Plan card** — proposed capability (name, what it does, secrets needed) + `Build it` / `Adjust`.
2. **Build-status line** — live stages streaming: `Authoring → Sandboxing → Verified`.
3. **Result card** — built summary + test result + `Add` / `Discard`.
4. **Mode chip** in the header ("Building capability") so it's clearly a build flow, not Q&A.

## Open decisions (for next session)

- **Gates** — the 2 above, plus a possible third gate when the agent needs a **secret** (owner pastes
  the token in-flow; stored in the keychain, never echoed back).
- **What a map node looks like** when a capability lands (labeled card? status/health? click → detail
  showing what it does + its `uses`).
- **Clarify depth** — how many questions before it's annoying; when to just proceed with sensible
  defaults vs. ask.
- **Verification trust** — the agent writes its own test (circular). Add an independent check or an
  owner-reviews-the-diff step before promote? (Relates to the self-test weakness.)

## What it needs on the brain side (later spec work)

- Forge wired behind an endpoint (`POST /app/capabilities/build` or similar) that drives the gated
  flow, streaming the stages over SSE like Ask does.
- Chat **intent detection** ("build/create a capability/module" → enter build mode vs normal Q&A).
- Capability store pointed at the **real data root** (not the throwaway `.forge-test/`), so built
  capabilities persist and feed the map (`/app/capabilities` endpoint → nodes).
- **WSL2 sandbox** (no-network + egress allowlist) is a hard gate before running authored code that
  touches `imaplib`/network — the interim `SubprocessSandbox` has no isolation.

## Related

- Forge: `src/artemis/capabilities/forge.py` · sandbox: `capabilities/sandbox.py` (interim).
- Map must be capability-driven: memory `client-map-capability-driven`; the empty map already shows
  an "Open Ask" empty-state.
- Roadmap: `docs/v2/client-revival-roadmap.md` (CR-7+ tail covers real spokes/voice/vault).
