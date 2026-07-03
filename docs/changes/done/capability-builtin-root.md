# capability-builtin-root — tracked builtin capabilities (Wave 2c-1)

**Identity:** Give `FileCapabilityStore` a second, read-only search root for **builtin** (repo-shipped,
tracked) capabilities that resolve independent of the runtime data dir — so a spec-built fetcher
travels with the repo (and to the Mac Mini, where the data dir is `/opt/artemis`). Owner decision
2026-07-03 (Option B: tracked builtin location). Prereq for `calendar-sync` (2c-2).

**Scoping rule:** only `get(name)` gains the builtin fallback (so internal runners like the
FetcherRunner resolve a builtin capability by name). `list()` and `retrieve()` stay **library-only** —
builtin capabilities are infrastructure (scheduled fetchers), NOT owner-facing selectable/listed
capabilities. This also means no existing selector/list test changes behaviour.

## Files to change
| Op | Path |
|----|------|
| modify | `src/artemis/capabilities/store.py` |
| modify | `src/artemis/api/app.py` |
| modify | `tests/capabilities/test_store.py` |

## Exact changes

### Task 1 — `src/artemis/capabilities/store.py` (modify)
**a.** Add a module-level resolver (near the bottom, beside `slug`):
```python
def builtin_capabilities_root() -> Path:
    """Repo-shipped (tracked, read-only) builtin capabilities, independent of the data dir.

    Resolved relative to this source file so it points at the checked-out repo's
    capabilities/builtin/ on any machine (dev box or Mini) where the runtime data dir differs.
    """
    return Path(__file__).resolve().parents[3] / "capabilities" / "builtin"
```
(`store.py` is `src/artemis/capabilities/store.py`, so `parents[3]` is the repo root.)

**b.** Add an optional `builtin_root` to `__init__`:
```python
    def __init__(self, root: Path, *, builtin_root: Path | None = None) -> None:
        self._staging = root / "staging"
        self._library = root / "library"
        self._builtin = builtin_root
        self._staging.mkdir(parents=True, exist_ok=True)
        self._library.mkdir(parents=True, exist_ok=True)
```
(Do NOT `mkdir` the builtin root — it is read-only and repo-managed; a missing dir just yields no
builtin capabilities.)

**c.** `get` falls back to builtin (library wins on a name clash):
```python
    def get(self, name: str) -> Skill | None:
        skill_path = self._library / name / "SKILL.md"
        if skill_path.exists():
            return self._read_skill(skill_path)
        if self._builtin is not None:
            builtin_path = self._builtin / name / "SKILL.md"
            if builtin_path.exists():
                return self._read_skill(builtin_path)
        return None
```
`list`, `retrieve`, `promote`, `stage`, `mark_auth_verified`, `staging_dir` are UNCHANGED (builtin
is library-invisible and never written).

### Task 2 — `src/artemis/api/app.py` (modify)
Import the resolver and pass it when constructing the store. Change the import line
`from artemis.capabilities.store import FileCapabilityStore` to also import the resolver:
```python
from artemis.capabilities.store import FileCapabilityStore, builtin_capabilities_root
```
and the construction (currently line ~70):
```python
    capability_store = FileCapabilityStore(
        resolved_data_dir / "capabilities", builtin_root=builtin_capabilities_root()
    )
```

### Task 3 — `tests/capabilities/test_store.py` (modify)
Append tests (reuse the file's existing helpers for writing a capability into a dir — a
`write_skill_md(dir/"SKILL.md", ...)` + `sandbox_policy.json`, mirroring how the file already seeds
library capabilities). Cover:
```python
def test_get_falls_back_to_builtin(tmp_path):
    builtin = tmp_path / "builtin"
    # write a capability under builtin/foo/ (SKILL.md via write_skill_md, matching this file's helper)
    _seed_capability(builtin / "foo", name="foo")
    store = FileCapabilityStore(tmp_path / "data", builtin_root=builtin)
    got = store.get("foo")
    assert got is not None and got.name == "foo"

def test_builtin_not_in_list_or_retrieve(tmp_path):
    builtin = tmp_path / "builtin"
    _seed_capability(builtin / "foo", name="foo")
    store = FileCapabilityStore(tmp_path / "data", builtin_root=builtin)
    assert store.list() == []                      # builtin is infra, not listed
    assert await store.retrieve("foo") == []       # not selectable

def test_library_wins_over_builtin_on_name_clash(tmp_path):
    builtin = tmp_path / "builtin"
    _seed_capability(builtin / "foo", name="foo", description="builtin one")
    store = FileCapabilityStore(tmp_path / "data", builtin_root=builtin)
    _seed_capability(store._library / "foo", name="foo", description="library one")
    got = store.get("foo")
    assert got is not None and got.description == "library one"

def test_no_builtin_root_is_fine(tmp_path):
    store = FileCapabilityStore(tmp_path / "data")  # builtin_root defaults to None
    assert store.get("anything") is None

def test_builtin_capabilities_root_points_at_repo():
    root = builtin_capabilities_root()
    assert root.name == "builtin" and root.parent.name == "capabilities"
```
(Import `builtin_capabilities_root` from `artemis.capabilities.store`. If the file has no
capability-seeding helper yet, add a small `_seed_capability(dir, *, name, description="d")` that
`mkdir`s the dir and `write_skill_md`s a minimal valid SKILL.md — do not weaken assertions.)

## Acceptance criteria
1. `get(name)` returns a builtin capability when it is absent from the library. → `test_get_falls_back_to_builtin`
2. `list()` and `retrieve()` never surface builtin capabilities. → `test_builtin_not_in_list_or_retrieve`
3. A library capability shadows a builtin of the same name. → `test_library_wins_over_builtin_on_name_clash`
4. A store with no builtin root behaves exactly as before. → `test_no_builtin_root_is_fine`
5. `builtin_capabilities_root()` resolves to `<repo>/capabilities/builtin`. → `test_builtin_capabilities_root_points_at_repo`
6. Whole-project `uv run mypy src/` clean, `ruff check` + `ruff format --check` clean, full suite green.

## Commands to run
```
uv run ruff check src/ tests/
uv run ruff format --check src/artemis/capabilities/store.py src/artemis/api/app.py tests/capabilities/test_store.py
uv run mypy src/
uv run pytest -q tests/capabilities/test_store.py
uv run pytest -q
```
