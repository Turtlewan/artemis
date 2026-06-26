import hashlib
import json
import logging
import os
from dataclasses import dataclass
from typing import Protocol

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class JudgeScore:
    trace_id: str
    score: float
    reasoning: str
    passed: bool


class JudgePort(Protocol):
    def score(self, task: str, reasoning: str, answer: str) -> JudgeScore: ...


class JudgeParseError(Exception):
    pass


class JudgeAdapter:
    """DeepSeek chat-completions API as judge."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        threshold: float = 0.6,
    ) -> None:
        resolved_api_key = api_key or os.environ.get("DEEPSEEK_API_KEY")
        if not resolved_api_key:
            raise RuntimeError("DEEPSEEK_API_KEY is required for JudgeAdapter")
        self._api_key = resolved_api_key
        self._base_url = (
            base_url or os.environ.get("DEEPSEEK_BASE_URL") or "https://api.deepseek.com/v1"
        ).rstrip("/")
        self._model = model or os.environ.get("DEEPSEEK_JUDGE_MODEL") or "deepseek-chat"
        self._threshold = threshold
        self._client = httpx.Client(timeout=60)

    def score(self, task: str, reasoning: str, answer: str) -> JudgeScore:
        trace_id = _trace_id(task, reasoning, answer)
        try:
            score, rationale = self._score_payload(task, reasoning, answer)
        except JudgeParseError:
            LOGGER.warning("Judge returned unparseable JSON twice for trace %s", trace_id)
            score = 0.0
            rationale = "Judge response could not be parsed."
        bounded_score = max(0.0, min(1.0, score))
        return JudgeScore(
            trace_id=trace_id,
            score=bounded_score,
            reasoning=rationale,
            passed=bounded_score >= self._threshold,
        )

    @retry(
        stop=stop_after_attempt(2),
        wait=wait_exponential(min=1, max=4),
        retry=retry_if_exception_type(JudgeParseError),
        reraise=True,
    )
    def _score_payload(self, task: str, reasoning: str, answer: str) -> tuple[float, str]:
        response = self._client.post(
            f"{self._base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self._api_key}"},
            json={
                "model": self._model,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "You are a quality-filter judge. Score the reasoning trace 0.0-1.0 "
                            "on: (1) chain-of-thought completeness - real steps, not just a "
                            "conclusion; (2) factual plausibility - answer follows from reasoning; "
                            "(3) task relevance. Respond JSON: "
                            '{"score": <float>, "reasoning": "<one sentence>"}.'
                        ),
                    },
                    {
                        "role": "user",
                        "content": f"Task: {task}\nReasoning: {reasoning}\nAnswer: {answer}",
                    },
                ],
            },
        )
        response.raise_for_status()
        payload = response.json()
        content = payload["choices"][0]["message"]["content"]
        if not isinstance(content, str):
            raise JudgeParseError("judge content was not a string")
        try:
            parsed = json.loads(content)
            score = float(parsed["score"])
            rationale = str(parsed["reasoning"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise JudgeParseError("judge content was not expected JSON") from exc
        return score, rationale


class FakeJudge:
    """Deterministic pass/fail by content hash vs pass_rate."""

    def __init__(self, *, pass_rate: float = 1.0) -> None:
        self._pass_rate = pass_rate

    def score(self, task: str, reasoning: str, answer: str) -> JudgeScore:
        trace_id = _trace_id(task, reasoning, answer)
        value = int(hashlib.sha256((task + reasoning + answer).encode()).hexdigest(), 16)
        score = (value % 100) / 100
        passed = score < self._pass_rate
        returned_score = 1.0 if passed else 0.0
        return JudgeScore(
            trace_id=trace_id,
            score=returned_score,
            reasoning="Deterministic fake judge score.",
            passed=passed,
        )


def _trace_id(task: str, reasoning: str, answer: str) -> str:
    return hashlib.sha256((task + reasoning + answer).encode()).hexdigest()
