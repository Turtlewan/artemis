# freshness-gate — per-domain staleness gate on the read path (Wave 2e)

**Identity:** Add a per-domain freshness threshold to the read path: synced data younger than the
threshold answers locally; older (or absent) falls through to the live path. ADR-046 #5. Modifies
`ReadService` (shipped in `data-read`). Uses the existing `DataStore.latest_fetched_at`.

## Files to change
| Op | Path |
|----|------|
| modify | `src/artemis/data/read.py` |
| modify | `tests/data/test_read.py` |

## Exact changes

### Task 1 — `src/artemis/data/read.py` (modify)
**a.** Add a `freshness_s` field to `DomainSpec` (default 15 minutes):
```python
class DomainSpec(BaseModel):
    """A synced domain the read path can answer from. `keywords` route an ask to this domain;
    `freshness_s` is the max age of stored data still answered locally (older -> live path)."""

    model_config = ConfigDict(frozen=True)

    domain: str
    keywords: tuple[str, ...]
    limit: int = 50
    freshness_s: float = 900.0
```

**b.** In `ReadService.read`, gate on freshness after resolving the domain. Replace the body's
`rows = ...` / `if not rows` block with a freshness check first:
```python
    async def read(self, text: str) -> ReadResult | None:
        spec = self.resolve_domain(text)
        if spec is None:
            return None
        latest = self._store.latest_fetched_at(spec.domain)
        if latest is None or (self._now() - latest) > spec.freshness_s:
            # empty or stale -> fall through to the live path (don't answer from stale local data)
            return None
        rows = self._store.query(domain=spec.domain, limit=spec.limit)
        if not rows:
            return None
        answer = await self._phrase(text, rows)
        if answer is None:
            return None
        return ReadResult(domain=spec.domain, answer=answer)
```
(The empty-store case is now subsumed by `latest is None`; keep the `if not rows` guard as
belt-and-suspenders.)

### Task 2 — `tests/data/test_read.py` (modify)
The existing `_seed` helper stamps `fetched_at=100.0`. Add a `now` to `ReadService` in the seeded
tests so freshness is deterministic, and add two tests:
```python
async def test_read_fresh_data_answers_locally():
    store = DataStore()
    _seed(store, fetched_at=1000.0)
    phraser = FakePhraser(answer="You have Standup at 9am.")
    svc = ReadService(store, phraser=phraser, now=lambda: 1300.0)  # 300s old < 900s threshold
    result = await svc.read("what's on my calendar")
    assert result is not None and result.answer == "You have Standup at 9am."

async def test_read_stale_data_falls_through():
    store = DataStore()
    _seed(store, fetched_at=1000.0)
    svc = ReadService(store, phraser=FakePhraser(), now=lambda: 2500.0)  # 1500s old > 900s threshold
    assert await svc.read("what's on my calendar") is None  # stale -> live path
```
Update any existing seeded read test that would now trip the freshness gate: pass a `now` close to
the seed's `fetched_at` (e.g. `now=lambda: 100.0`) so previously-passing local-answer tests still
answer locally. (The empty-store and no-match tests are unaffected.)

## Acceptance criteria
1. `DomainSpec.freshness_s` defaults to 900s; fresh stored data (age < threshold) answers locally. → `test_read_fresh_data_answers_locally`
2. Stale stored data (age > threshold) makes `read` return `None` (fall through to live). → `test_read_stale_data_falls_through`
3. Existing `data-read` tests still pass (seeded local-answer tests use a `now` within threshold). → existing tests green
4. Whole-project `uv run mypy src/` clean, `ruff check` + `ruff format --check` clean, full suite green.

## Commands to run
```
uv run ruff check src/ tests/
uv run ruff format --check src/artemis/data/read.py tests/data/test_read.py
uv run mypy src/
uv run pytest -q tests/data/test_read.py
uv run pytest -q
```
