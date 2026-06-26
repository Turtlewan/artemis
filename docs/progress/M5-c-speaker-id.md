# M5-c-speaker-id — build progress / security review

Built by Codex, host-verified: full mypy clean (320 files), ruff clean, 9 new tests + 14 gateway/
scope-wall regression pass, full suite 857 passed / 5 skipped. Opus cross-model SECURITY review:
CLEAN on all core invariants (voice-ID never unlocks DEK; Tier-1-locked-owner -> NEEDS_PHONE_UNLOCK
before any serve; unknown->guest with no owner scope; voiceprints embeddings-only AES-GCM under the
Tier-0/GENERAL key, never plaintext; no audio/transcript logging). GUEST_PERSON_ID defined in
gateway.py (not scope.py) to honour surgical scope.

## FLAG (security hardening, review-needed) — Tier-1 gate fails open on absent key_provider
`Gateway.handle_voice`'s gate condition includes `self._key_provider is not None`, so if the Gateway
has NO key_provider the Tier-1-owner-while-locked branch is skipped and it falls through to
`brain.respond` (fail-OPEN). It SHOULD fail-CLOSED: a missing key_provider means "cannot verify
unlock" -> treat as locked -> NEEDS_PHONE_UNLOCK. NOT exploitable in the real wiring (compose_brain
always injects a key_provider, and the brain-side scope wall backstops — owner-private data won't
decrypt without the DEK), so it's defense-in-depth, not an open hole. ACTION: make the gate
fail-closed (drop the `is not None` escape, or require key_provider for the voice path).
