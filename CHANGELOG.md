# Changelog

All notable changes to this project will be documented in this file.
Format based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).

## [Unreleased]

### Changed
- The test suite now runs under strict mypy type-checking across both source and test files (previously only source was checked), catching type errors at lint-time rather than at test runtime.
- `FakeEmbedder` in manifest tests uses a process-stable SHA-256 hash instead of Python's builtin `hash()`, eliminating the one flaky test that depended on `PYTHONHASHSEED`.
- Hollow conformance assertions in manifest tests were tightened to perform real structural type-checking against the `VectorStore` protocol.
- Removed a stray duplicate docstring in `src/artemis/ports/types.py`.
