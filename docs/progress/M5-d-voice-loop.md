# M5-d-voice-loop-orchestrator — build progress / security review

Built by Codex, host-verified: full mypy clean (324 files), ruff clean, 8 new tests, full suite
865 passed / 5 skipped. Opus cross-model security review: CLEAN — handle_voice_stream is FAIL-CLOSED
(owner Tier-1 with key_provider None OR locked -> raise NeedsPhoneUnlock, never serves); the loop
catches NeedsPhoneUnlock and plays the spoken NEEDS_UNLOCK_PROMPT (not the sentinel), serving nothing;
no direct brain.respond bypass (voice serves only via the gated handle_voice_stream); no audio/
transcript logging. SidecarAudioFrontend is transport-aware (mirrors IPCServer.endpoint(): AF_UNIX ->
audio.sock else audio.port -> 127.0.0.1). GATED Task 6 (real mic->speaker + latency budget) on-Mac.

## FOLLOW-UP (planning) — two voice gates now exist
The Gateway has handle_voice (M5-c, non-streaming, FAIL-OPEN on absent key_provider — flagged) AND
handle_voice_stream (M5-d, streaming, FAIL-CLOSED — correct). The voice loop uses ONLY the streaming
fail-closed path, so the live voice path is secure. Harmonize: make handle_voice fail-closed too, or
retire it if the streaming path supersedes it (see M5-c progress flag).
