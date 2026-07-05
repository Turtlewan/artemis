from __future__ import annotations

import subprocess
import sys


def test_memory_embedder_import_does_not_load_model_providers() -> None:
    script = """
import sys
import artemis.memory.embedder
raise SystemExit("artemis.model.anthropic_provider" in sys.modules)
"""

    result = subprocess.run(
        [sys.executable, "-c", script],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_model_errors_reexports_top_level_errors() -> None:
    from artemis.errors import ProviderUnavailableError as TopLevelProviderUnavailableError
    from artemis.model.errors import ProviderUnavailableError as ModelProviderUnavailableError

    assert ModelProviderUnavailableError is TopLevelProviderUnavailableError
