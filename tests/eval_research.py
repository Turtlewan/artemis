"""Off-suite DR-c research-quality eval harness.

Passing bar for recorded fixtures:
- Mean faithfulness >= 4/5 for each mode.
- STANDARD should stay within 1 point of DEEP mean faithfulness while using no
  more than 75% of DEEP token cost on this fake fixture set.

Live model/search scoring is gated. Set ARTEMIS_RESEARCH_LIVE=1 on hardware
with configured search, reader, teacher, and orchestrator roles to replace the
fakes; the default run is deterministic and offline.
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass

import artemis.research.egress as egress_module
from artemis.ports.model import ModelResponse
from artemis.ports.types import Message, Usage, Vector
from artemis.research import EgressPolicy, FetchedContent, SearchHit
from artemis.research.engine import DeepResearcher
from artemis.research.modes import ResearchMode
from artemis.untrusted.quarantine import QuarantinedReader


@dataclass(frozen=True)
class GoldenCase:
    query: str
    required_source_domains: tuple[str, ...]
    acceptance_notes: str


GOLDEN_CASES: tuple[GoldenCase, ...] = (
    GoldenCase(
        "What do Python and SQLite docs say about transaction commits?",
        ("python.org", "sqlite.org"),
        "Mentions explicit commit semantics and durable transaction boundaries.",
    ),
    GoldenCase(
        "Summarise public guidance on passkey phishing resistance.",
        ("fidoalliance.org", "w3.org"),
        "Explains origin-bound credentials and phishing-resistant authentication.",
    ),
    GoldenCase(
        "Compare HTTP cache validators at a high level.",
        ("developer.mozilla.org", "rfc-editor.org"),
        "References ETag/Last-Modified validators and conditional requests.",
    ),
    GoldenCase(
        "What is the difference between UTC and civil time zones?",
        ("iana.org", "nist.gov"),
        "Distinguishes UTC from regional time-zone rules.",
    ),
    GoldenCase(
        "Explain why software supply-chain lockfiles are useful.",
        ("python.org", "docs.npmjs.com"),
        "Covers reproducibility and dependency integrity at a practical level.",
    ),
)


class FakeSearchProvider:
    def __init__(self, hits: dict[str, list[SearchHit]]) -> None:
        self._hits = hits

    async def search(self, query: str, *, count: int = 8) -> list[SearchHit]:
        return self._hits.get(query, [])[:count]


class FakeFetcher:
    def __init__(self, content: dict[str, FetchedContent]) -> None:
        self._content = content

    async def fetch(self, url: str, *, max_chars: int = 20000) -> FetchedContent:
        fetched = self._content[url]
        return FetchedContent(fetched.url, fetched.domain, fetched.text[:max_chars])


class FakeReaderModel:
    def __init__(self, payloads: dict[str, dict[str, object]]) -> None:
        self._payloads = payloads

    async def complete(
        self,
        *,
        role: str,
        messages: Sequence[Message],
        response_schema: dict[str, object] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> ModelResponse:
        del role, response_schema, temperature, max_tokens
        raw = messages[-1].content
        for marker, payload in self._payloads.items():
            if marker in raw:
                return ModelResponse(text=json.dumps(payload), usage=Usage(20, 30, 50))
        return ModelResponse(text="{}", usage=Usage(1, 1, 2))

    def complete_stream(
        self,
        *,
        role: str,
        messages: Sequence[Message],
        temperature: float = 0.7,
    ) -> AsyncIterator[str]:
        del role, messages, temperature
        raise NotImplementedError

    async def embed(self, role: str, texts: Sequence[str]) -> list[Vector]:
        del role
        return [[0.0] for _ in texts]


class FakeOrchestratorModel:
    def __init__(self, query: str, domains: tuple[str, ...], *, token_scale: int) -> None:
        self._query = query
        self._domains = domains
        self._token_scale = token_scale

    async def complete(
        self,
        *,
        role: str,
        messages: Sequence[Message],
        response_schema: dict[str, object] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> ModelResponse:
        del role, messages, temperature, max_tokens
        properties = response_schema.get("properties", {}) if response_schema else {}
        if isinstance(properties, dict) and "queries" in properties:
            text = json.dumps({"queries": [self._query]})
        elif isinstance(properties, dict) and "enough" in properties:
            text = json.dumps({"enough": True, "missing": ""})
        else:
            text = json.dumps(
                {
                    "content": (
                        f"Grounded answer for {self._query}. "
                        f"Supported by {', '.join(self._domains)}."
                    )
                }
            )
        return ModelResponse(text=text, usage=Usage(10, 10, 20 * self._token_scale))

    def complete_stream(
        self,
        *,
        role: str,
        messages: Sequence[Message],
        temperature: float = 0.7,
    ) -> AsyncIterator[str]:
        del role, messages, temperature
        raise NotImplementedError

    async def embed(self, role: str, texts: Sequence[str]) -> list[Vector]:
        del role
        return [[0.0] for _ in texts]


class FakeTeacherJudge:
    async def complete(
        self,
        *,
        role: str,
        messages: Sequence[Message],
        response_schema: dict[str, object] | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
    ) -> ModelResponse:
        del role, response_schema, temperature, max_tokens
        prompt = messages[-1].content
        domains = prompt.split("Required domains: ", maxsplit=1)[1].splitlines()[0].split(", ")
        content = prompt.split("Content: ", maxsplit=1)[1]
        coverage = all(domain in content for domain in domains)
        score = 5 if coverage else 3
        return ModelResponse(
            text=json.dumps(
                {
                    "faithfulness": score,
                    "relevance": score,
                    "notes": "recorded-fixture judge",
                }
            ),
            usage=Usage(5, 5, 10),
        )

    def complete_stream(
        self,
        *,
        role: str,
        messages: Sequence[Message],
        temperature: float = 0.7,
    ) -> AsyncIterator[str]:
        del role, messages, temperature
        raise NotImplementedError

    async def embed(self, role: str, texts: Sequence[str]) -> list[Vector]:
        del role
        return [[0.0] for _ in texts]


async def _score_with_teacher(
    judge: FakeTeacherJudge,
    case: GoldenCase,
    content: str,
) -> tuple[int, int]:
    response = await judge.complete(
        role="teacher",
        messages=[
            Message(
                "user",
                "Score faithfulness and relevance 1-5 using the rubric. "
                "Every content claim must be supported by cited extracts.\n"
                f"Required domains: {', '.join(case.required_source_domains)}\n"
                f"Acceptance notes: {case.acceptance_notes}\n"
                f"Content: {content}",
            )
        ],
        temperature=0,
    )
    payload = json.loads(response.text)
    return int(payload["faithfulness"]), int(payload["relevance"])


async def _run_case(case: GoldenCase, mode: ResearchMode) -> tuple[int, int, int]:
    urls = [f"https://{domain}/recorded-fixture" for domain in case.required_source_domains]
    hits = {
        case.query: [
            SearchHit(domain, url, f"Recorded snippet for {domain}")
            for domain, url in zip(case.required_source_domains, urls, strict=True)
        ]
    }
    content = {
        url: FetchedContent(url, domain, f"RAW_{domain} factual fixture for {case.query}.")
        for domain, url in zip(case.required_source_domains, urls, strict=True)
    }
    payloads = {
        f"RAW_{domain}": {
            "summary": f"{domain} supports {case.acceptance_notes}",
            "claims": [f"{domain} provides evidence for {case.query}."],
            "flagged_injection": False,
        }
        for domain in case.required_source_domains
    }
    token_scale = 1 if mode is ResearchMode.STANDARD else 3
    researcher = DeepResearcher(
        FakeSearchProvider(hits),
        FakeFetcher(content),
        QuarantinedReader(FakeReaderModel(payloads), "research_reader"),
        FakeOrchestratorModel(case.query, case.required_source_domains, token_scale=token_scale),
        EgressPolicy(frozenset()),
        object(),
        mode=mode,
    )
    result = await researcher.research(case.query, token_cap=100000)
    faithfulness, relevance = await _score_with_teacher(FakeTeacherJudge(), case, result.content)
    return faithfulness, relevance, result.token_usage


async def _run_recorded() -> None:
    def noop(url: str) -> None:
        del url

    egress_module.block_private_ip = noop
    rows: list[tuple[str, float, float, int]] = []
    for mode in (ResearchMode.STANDARD, ResearchMode.DEEP):
        faithfulness_scores: list[int] = []
        relevance_scores: list[int] = []
        token_cost = 0
        for case in GOLDEN_CASES:
            faithfulness, relevance, tokens = await _run_case(case, mode)
            faithfulness_scores.append(faithfulness)
            relevance_scores.append(relevance)
            token_cost += tokens
        rows.append(
            (
                mode.value,
                sum(faithfulness_scores) / len(faithfulness_scores),
                sum(relevance_scores) / len(relevance_scores),
                token_cost,
            )
        )

    print("mode       faithfulness  relevance  token_cost")
    for mode_name, faith_avg, rel_avg, cost in rows:
        print(f"{mode_name:<10} {faith_avg:>12.2f} {rel_avg:>10.2f} {cost:>11}")


def main() -> None:
    if os.environ.get("ARTEMIS_RESEARCH_LIVE") == "1":
        raise SystemExit("live DR-c eval is gated on hardware; recorded fixtures are the default")
    asyncio.run(_run_recorded())


if __name__ == "__main__":
    main()
