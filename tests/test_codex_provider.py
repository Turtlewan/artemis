from __future__ import annotations

from pathlib import Path

from artemis.model.codex_provider import CodexProvider


def test_codex_provider_resolves_binary_and_builds_expected_argv() -> None:
    provider = CodexProvider(binary="definitely-not-a-real-codex-binary")

    argv = provider._build_argv(
        model="gpt-test",
        output_path=Path("out.txt"),
        schema_path=Path("schema.json"),
    )

    assert argv == [
        "definitely-not-a-real-codex-binary",
        "exec",
        "-m",
        "gpt-test",
        "--sandbox",
        "read-only",
        "--ephemeral",
        "--skip-git-repo-check",
        "--color",
        "never",
        "-o",
        "out.txt",
        "--output-schema",
        "schema.json",
        "-",
    ]
