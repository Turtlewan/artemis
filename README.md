# Artemis

A personal assistant that integrates with everything, with a RAG-heavy second brain as its knowledge subsystem.

> **Status:** pre-SP0 — requirements-gathering and stack confirmation not yet done. See `docs/status.md`.

## Voice Ask

Press **Alt+Space** (or the push-to-talk button in the Ask popup) to speak a query. Artemis transcribes it, sends it to the brain, streams the answer to the overlay, and speaks it aloud. Requires the brain server running locally (`uvicorn artemis.main:app`) and the audio sidecar.
