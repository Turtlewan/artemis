import json
import re
import shutil
import subprocess
from typing import Protocol

from tenacity import retry, stop_after_attempt, wait_exponential


class TeacherPort(Protocol):
    def complete(self, system: str, user: str) -> str: ...


class TeacherCallError(Exception):
    pass


class TeacherAdapter:
    """Calls `claude -p <prompt> --output-format json` as a subprocess."""

    def __init__(self, *, timeout_s: int = 600) -> None:
        exe = shutil.which("claude")
        if exe is None:
            raise RuntimeError("claude CLI not found on PATH - install and log in first")
        self._exe = exe
        self._timeout_s = timeout_s

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(min=4, max=30))
    def complete(self, system: str, user: str) -> str:
        prompt = f"{system}\n\n{user}"
        proc = subprocess.run(
            [self._exe, "-p", prompt, "--output-format", "json"],
            capture_output=True,
            text=True,
            timeout=self._timeout_s,
            check=False,
        )
        try:
            data = json.loads(proc.stdout)
        except json.JSONDecodeError as exc:
            raise TeacherCallError(proc.stderr or proc.stdout) from exc
        if proc.returncode != 0 or data.get("is_error"):
            raise TeacherCallError(proc.stderr or json.dumps(data))
        result = data.get("result")
        if not isinstance(result, str):
            raise TeacherCallError("claude JSON stdout did not contain a string result")
        return result


class FakeTeacher:
    """Returns a deterministic BATCH of k <trace> blocks for tests."""

    def __init__(self, *, batch_size: int = 10) -> None:
        self._batch_size = batch_size
        self.calls = 0

    def complete(self, system: str, user: str) -> str:
        del system
        self.calls += 1
        batch_size = self._extract_requested_count(user)
        start = self._extract_start(user)
        blocks = []
        for offset in range(batch_size):
            idx = start + offset
            blocks.append(
                "<trace>"
                f"<task>Synthetic task {idx}</task>"
                f"<reasoning>Step 1 for {idx}. Step 2 for {idx}.</reasoning>"
                f"<answer>Answer {idx}</answer>"
                "</trace>"
            )
        return "".join(blocks)

    def _extract_requested_count(self, user: str) -> int:
        match = re.search(r"Generate\s+(\d+)\s+DISTINCT", user, flags=re.IGNORECASE)
        if match is None:
            return self._batch_size
        return int(match.group(1))

    @staticmethod
    def _extract_start(user: str) -> int:
        match = re.search(r"indices starting at\s+(\d+)", user, flags=re.IGNORECASE)
        if match is None:
            return 0
        return int(match.group(1))
