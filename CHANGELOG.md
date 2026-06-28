# Changelog

All notable changes to this project will be documented in this file.
Format based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [Unreleased]

### Added
- Tauri desktop client: app auth/pairing, the spatial command-map shell, live Ask overlay (floating window plus brain connection), and the pending-actions / recipe review surface (GATE-b).
- Windows brain runtime bring-up.
- Owner data on Windows is now encrypted at rest. All owner-private stores (mail cache, tasks, finances, agent checkpoint, inbox) are keyed with SQLCipher and the per-store data-encryption key is sealed via Windows DPAPI (user-scope), binding it to this Windows user and machine. A stolen disk or another Windows user account cannot read Artemis data. (Same-user-credential protection — e.g. malware in the same session — is deferred to a later milestone.)

### Changed
- The test suite now runs under strict mypy type-checking across both source and test files (previously only source was checked), catching type errors at lint-time rather than at test runtime.
- `FakeEmbedder` in manifest tests uses a process-stable SHA-256 hash instead of Python's builtin `hash()`, eliminating the one flaky test that depended on `PYTHONHASHSEED`.
- Hollow conformance assertions in manifest tests were tightened to perform real structural type-checking against the `VectorStore` protocol.
- Removed a stray duplicate docstring in `src/artemis/ports/types.py`.

### Fixed
- Client now calls the brain's `/review/auto-enabled` contract; quarantine reader tolerates local-model prose output; `test_health.py` teardown is hardened; dead `_EnvKeyProvider` removed.
