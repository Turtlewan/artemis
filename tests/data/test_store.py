from artemis.data.store import DataStore, Record


def _rec(**over: object) -> Record:
    base = dict(
        domain="calendar", kind="event", key="e1",
        payload={"title": "Standup"}, sanitized_text="Standup at 9am",
        source="today-calendar", fetched_at=100.0, owner_fields={},
    )
    base.update(over)
    return Record(**base)  # type: ignore[arg-type]


def test_upsert_get_roundtrip() -> None:
    s = DataStore()
    s.upsert(_rec(payload={"title": "Standup", "n": 3}, owner_fields={"note": "skip"}))
    got = s.get("calendar", "event", "e1")
    assert got is not None
    assert got.payload == {"title": "Standup", "n": 3}
    assert got.owner_fields == {"note": "skip"}


def test_upsert_preserves_owner_fields() -> None:
    s = DataStore()
    s.upsert(_rec(owner_fields={"note": "keep me"}))
    s.upsert(_rec(sanitized_text="Standup moved to 10am", fetched_at=200.0))  # re-pull, no owner_fields
    got = s.get("calendar", "event", "e1")
    assert got is not None
    assert got.sanitized_text == "Standup moved to 10am"  # feed field updated
    assert got.fetched_at == 200.0
    assert got.owner_fields == {"note": "keep me"}  # preserved


def test_query_newest_first_and_filters() -> None:
    s = DataStore()
    s.upsert(_rec(key="e1", sanitized_text="Standup", fetched_at=100.0))
    s.upsert(_rec(key="e2", sanitized_text="Lunch with Sam", fetched_at=200.0, kind="event"))
    s.upsert(_rec(key="t1", domain="calendar", kind="task", sanitized_text="File taxes", fetched_at=150.0))
    newest = s.query(domain="calendar")
    assert [r.key for r in newest] == ["e2", "t1", "e1"]  # fetched_at desc
    assert [r.key for r in s.query(domain="calendar", kinds=["task"])] == ["t1"]
    assert [r.key for r in s.query(domain="calendar", since=160.0)] == ["e2"]
    assert [r.key for r in s.query(domain="calendar", text="lunch")] == ["e2"]  # case-insensitive


def test_query_text_wildcards_are_literal() -> None:
    s = DataStore()
    s.upsert(_rec(key="a", sanitized_text="50% off"))
    s.upsert(_rec(key="b", sanitized_text="5000 off"))
    assert [r.key for r in s.query(domain="calendar", text="50%")] == ["a"]  # % is literal, not wildcard


def test_latest_fetched_at() -> None:
    s = DataStore()
    assert s.latest_fetched_at("calendar") is None
    s.upsert(_rec(key="e1", fetched_at=100.0))
    s.upsert(_rec(key="e2", fetched_at=250.0))
    assert s.latest_fetched_at("calendar") == 250.0


def test_delete() -> None:
    s = DataStore()
    s.upsert(_rec())
    s.delete("calendar", "event", "e1")
    assert s.get("calendar", "event", "e1") is None
