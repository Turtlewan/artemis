"""Version-scoped capability bless store."""

from __future__ import annotations

import json
import os
import secrets
from pathlib import Path


class BlessStore:
    """Atomic JSON store for standing capability consent.

    Reads intentionally fail closed and always re-read from disk so revokes made by
    another process take effect on the next decision.
    """

    def __init__(self, path: Path | None = None) -> None:
        root_or_path = path or Path(os.environ.get("ARTEMIS_DATA_DIR", "."))
        self._path = root_or_path if root_or_path.suffix == ".json" else root_or_path / "bless.json"

    def is_blessed(self, name: str, version: int) -> bool:
        return self._read().get(name) == version

    def bless(self, name: str, version: int) -> None:
        data = self._read()
        data[name] = version
        self._write(data)

    def unbless(self, name: str) -> None:
        data = self._read()
        data.pop(name, None)
        self._write(data)

    def list_blessed(self) -> list[tuple[str, int]]:
        return sorted(self._read().items())

    def _read(self) -> dict[str, int]:
        try:
            raw = self._path.read_text(encoding="utf-8")
            decoded = json.loads(raw)
            if not isinstance(decoded, dict):
                return {}
            out: dict[str, int] = {}
            for name, version in decoded.items():
                if isinstance(name, str) and isinstance(version, int) and not isinstance(
                    version, bool
                ):
                    out[name] = version
            return out
        except Exception:
            return {}

    def _write(self, data: dict[str, int]) -> None:
        self._path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        temp_path = self._path.with_name(f".{self._path.name}.{secrets.token_hex(8)}.tmp")
        temp_path.write_text(
            json.dumps(data, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        try:
            os.chmod(temp_path, 0o600)
        except OSError:
            pass
        os.replace(temp_path, self._path)
