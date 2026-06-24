---
spec: x3-runtime-config
status: ready
token_profile: balanced
autonomy_level: L2
---
<!-- Wave F0 · foundation. Implements Decision X3 (LOCKED 2026-06-23): thin owner-editable runtime-config
     layer for all tunable values. Structural constants stay in code. Every downstream cluster spec
     (M8-b2 keywords/VIP/excludes, CalPrefs schedules, FIN-c thresholds, RXN fraud window, hook cadences)
     reads its tunables from here instead of hardcoding them. The client settings UI reads/writes the
     same JSON file later (deferred — not this spec). -->

# Spec: X3 — Runtime config layer (owner-editable `policy.json` for all tunable values)

**Identity:** `RuntimeConfig` — a typed, validated, owner-editable config layer that loads a single JSON file (`policy.json`) into a frozen Pydantic model, exposing all cluster tunables (VIP senders, keyword sets, bank-sender excludes, schedules, thresholds) with code-level defaults that apply when the file (or a key) is absent. Read-only at the brain layer; the client settings UI writes it later.
→ why: see docs/findings/cluster-decisions/DECISIONS-LOG.md (X3 LOCKED) · docs/findings/cluster-spec-roadmap.md Wave F0.

## Assumptions

- **M0-a** complete: `Settings`, `get_settings()` (`@lru_cache`), `paths.scope_dir(settings, scope)`, `paths.slot_root(settings)` are importable from `artemis.config` / `artemis.paths`. The `OWNER_PRIVATE` scope string constant (`"owner-private"`) is available from `artemis.identity.scope`. → impact: Stop (the config file path derives from `paths.slot_root(settings)`; the file is per-slot, NOT per-scope — it holds no secrets, only tunables, so it sits at the slot root beside `logs/`, not inside an encrypted scope dir).
- The config file is **owner-authored, fully trusted** — it is local, owner-edited (later via the client UI), never network-sourced. No `artemis.untrusted` layer applies. → impact: Stop (no quarantine; values are still type/range-validated as defence-in-depth against owner typos).
- This layer holds **tunables only** — values an owner might reasonably want to change without a rebuild (lists, thresholds, schedules). **Structural constants stay in code** (enum vocabularies, schema versions, the reconciliation-ladder *structure*, the recurrence rule grammar). The litmus: would changing this value require a code change to stay correct? If yes → it stays in code. → impact: Caution (do not migrate structural constants; only the leaf scalars/lists named in § Tasks).
- Defaults live **in the Pydantic model field defaults**, not in the JSON file. A fresh install with no `policy.json` (or a partial file) loads fully-defaulted config — the file is purely an override layer. → impact: Stop (downstream specs may assume `RuntimeConfig()` with zero file always returns valid, complete config).
- `get_runtime_config()` is `@lru_cache`d like `get_settings()` (one parse per process). A `reload_runtime_config()` clears the cache (the client settings-UI save path calls it after writing the file). → impact: Low (downstream readers call `get_runtime_config()` at composition/first-use; live-reload is the UI's concern, deferred).
- Off-hardware: no file → all-defaults; a temp `policy.json` under `tmp_path` exercises the override + validation paths. No new PyPI deps (stdlib `json` + Pydantic v2, already present). → impact: Low.

Simplicity check: considered a generic `dict[str, Any]` config with dotted-key lookup — rejected; untyped config defeats `mypy --strict` and pushes validation to every read site. A single frozen Pydantic model with nested sub-models per cluster is the minimum that gives typed access + one validation pass + IDE/discoverability. No TOML (owner-facing + future-UI-writable → JSON is the natural client interchange format). No watch/auto-reload (the UI calls `reload_runtime_config()` explicitly; a file watcher is premature).

## Prerequisites

- Specs complete: **M0-a** (`Settings`, `get_settings`, `paths`).
- Environment: no new PyPI deps. `uv sync` suffices off-hardware.

## Files to Change

| File | Operation | Notes |
|------|-----------|-------|
| `/Users/artemis-build/artemis/src/artemis/runtime_config.py` | create | `RuntimeConfig` (frozen) + nested cluster sub-models + `load_runtime_config(path)` + `get_runtime_config()` (`@lru_cache`) + `reload_runtime_config()` + `runtime_config_path(settings)` |
| `/Users/artemis-build/artemis/config/policy.example.json` | create | example file documenting every key with its default — copy to `policy.json` to override |
| `/Users/artemis-build/artemis/tests/test_runtime_config.py` | create | all-defaults (no file), override round-trip, partial-file merge, validation rejects bad values, cache + reload |

All paths under `/Users/artemis-build/artemis/`.

## Tasks

- [ ] **Task 1: Define the typed config models** — files: `/Users/artemis-build/artemis/src/artemis/runtime_config.py` —

  All models `model_config = ConfigDict(frozen=True, extra="forbid")` (a typo'd key in `policy.json` is a loud `ValidationError`, not a silently-ignored line). Use `from __future__ import annotations`.

  Nested sub-models, one per cluster surface that has tunables. Field defaults ARE the code-level defaults:

  ```python
  class GmailConfig(BaseModel):
      model_config = ConfigDict(frozen=True, extra="forbid")
      # M8-b2 urgency-widen (D1/D2/D3)
      vip_senders: tuple[str, ...] = ("ashley", "debby")          # D3 static set; ∪ memory-derived at runtime
      urgency_keywords: tuple[str, ...] = (                        # D1 OR-in topic admit
          "legal", "fraud", "unauthorized", "payment failed",
          "payment warning", "overdue", "suspended", "deadline",
      )
      urgency_sender_exclude: tuple[str, ...] = (                  # D2 bank-sender exclude
          "uob.com.sg", "scb.com", "standardchartered.com", "dbs.com", "dbs.com.sg",
      )

  class CalendarConfig(BaseModel):
      model_config = ConfigDict(frozen=True, extra="forbid")
      working_days: tuple[int, ...] = (0, 1, 2, 3, 4)             # X1 Mon–Fri (0=Mon … 6=Sun)
      preferred_focus_window: tuple[str, str] = ("09:00", "12:00")  # X2 morning bias
      free_gap_hook_time: str = "08:30"                            # C6 free-gap propose 1/day morning

  class TasksConfig(BaseModel):
      model_config = ConfigDict(frozen=True, extra="forbid")
      # T1 wake-triggered rhythm fixed-time fallbacks + day gates
      morning_digest_fallback_time: str = "08:00"                 # fires if no wake detected by this clock
      weekend_review_day: int = 5                                 # Sat (0=Mon … 6=Sun) — Sat-wake gate
      week_ahead_time: str = "19:00"                              # Sun week-ahead clock
      week_ahead_day: int = 6                                     # Sun

  class FinanceConfig(BaseModel):
      model_config = ConfigDict(frozen=True, extra="forbid")
      bank_sender_allowlist: tuple[str, ...] = (                  # F-D4 extraction allowlist
          "uob.com.sg", "scb.com", "standardchartered.com", "dbs.com", "dbs.com.sg",
      )
      recurring_min_occurrences: int = 2                          # F-D8 suggest at 2 occurrences
      reconcile_date_window_days: int = 1                         # F-D6 reconciliation ±N days
      reconcile_amount_exact: bool = True                         # F-D6 exact-amount match bar
      unusual_spend_sigma: float = 2.0                            # F-D9 outlier = N σ over merchant/cat history

  class ReactionConfig(BaseModel):
      model_config = ConfigDict(frozen=True, extra="forbid")
      fraud_confirm_amount_sgd: float = 500.0                    # I-3 ~S$500 fraud-confirm threshold
      fraud_confirm_window_days: int = 7                          # I-3 ±7d window
      reconciler_nightly_time: str = "03:00"                      # I-7 nightly link-integrity sweep
      maps_intl_buffer_minutes: int = 180                         # I-3/C3 airport buffer fallback (intl)
      maps_domestic_buffer_minutes: int = 90                      # I-3/C3 airport buffer fallback (domestic)
  ```

  Top-level aggregate (frozen, `extra="forbid"`), each sub-model defaulting via `Field(default_factory=...)`:

  ```python
  class RuntimeConfig(BaseModel):
      model_config = ConfigDict(frozen=True, extra="forbid")
      gmail: GmailConfig = Field(default_factory=GmailConfig)
      calendar: CalendarConfig = Field(default_factory=CalendarConfig)
      tasks: TasksConfig = Field(default_factory=TasksConfig)
      finance: FinanceConfig = Field(default_factory=FinanceConfig)
      reaction: ReactionConfig = Field(default_factory=ReactionConfig)
  ```

  **Validation rules (field validators):**
  - Every `*_time` string matches `^\d{2}:\d{2}$` with `00 <= HH <= 23`, `00 <= MM <= 59` (raise `ValueError` otherwise — reuse one shared `_validate_hhmm` validator).
  - `working_days` / `*_day` values are each in `range(0, 7)`.
  - `preferred_focus_window` is a 2-tuple `(start, end)` of valid HH:MM with `start < end`.
  - `recurring_min_occurrences >= 1`, `reconcile_date_window_days >= 0`, `unusual_spend_sigma > 0`, `fraud_confirm_amount_sgd > 0`, `fraud_confirm_window_days >= 0`, buffer minutes `>= 0`.

  — done when: `uv run mypy --strict src` passes; `RuntimeConfig()` constructs with all defaults; `RuntimeConfig(gmail=GmailConfig(vip_senders=("x",)))` overrides only that field; a `*_time` of `"25:00"` raises `ValidationError`; an unknown top-level key in a dict passed to `RuntimeConfig.model_validate({...})` raises `ValidationError` (extra="forbid").

- [ ] **Task 2: Implement load / cache / path helpers** — files: `/Users/artemis-build/artemis/src/artemis/runtime_config.py` —

  ```python
  def runtime_config_path(settings: Settings) -> Path:
      """The owner-editable policy file: <slot_root>/policy.json (per-slot, holds no secrets)."""
      return paths.slot_root(settings) / "policy.json"

  def load_runtime_config(path: Path | None = None) -> RuntimeConfig:
      """Load + validate policy.json. Missing file → all-defaults. Partial file → field-merge
      (absent keys default). Malformed JSON or a validation failure raises (loud — owner fixes the file)."""
      if path is None:
          path = runtime_config_path(get_settings())
      if not path.exists():
          return RuntimeConfig()
      raw = json.loads(path.read_text(encoding="utf-8"))   # JSONDecodeError propagates (loud)
      if not isinstance(raw, dict):
          raise ValueError("policy.json must be a JSON object")
      return RuntimeConfig.model_validate(raw)             # ValidationError propagates (loud)

  @lru_cache(maxsize=1)
  def get_runtime_config() -> RuntimeConfig:
      return load_runtime_config()

  def reload_runtime_config() -> RuntimeConfig:
      """Clear the cache + reload — the client settings-UI save path calls this after writing the file."""
      get_runtime_config.cache_clear()
      return get_runtime_config()
  ```

  **Partial-file merge note:** because each sub-model has its own defaults and `RuntimeConfig.model_validate` constructs absent sub-models via `default_factory`, a `policy.json` of `{"finance": {"recurring_min_occurrences": 3}}` yields full defaults everywhere except that one field. **A partially-specified sub-model object** (e.g. `{"finance": {"recurring_min_occurrences": 3}}`) merges at the field level because Pydantic fills absent fields from the sub-model's own defaults — verify in tests.

  — done when: `uv run mypy --strict src` passes; `load_runtime_config(<nonexistent>)` returns all-defaults; `load_runtime_config(<partial file>)` merges; `get_runtime_config()` is cached (same object identity on repeat call); `reload_runtime_config()` returns a fresh object after a file change.

- [ ] **Task 3: Write the example policy file** — files: `/Users/artemis-build/artemis/config/policy.example.json` —

  A complete JSON object mirroring every default in Task 1 (so an owner copies it to `policy.json` and edits). Every key present with its default value; a leading `"_comment"` key is NOT allowed (extra="forbid" would reject it) — instead document keys in the spec/inline docstring and keep the example file pure-data. Example shape:

  ```json
  {
    "gmail": {
      "vip_senders": ["ashley", "debby"],
      "urgency_keywords": ["legal", "fraud", "unauthorized", "payment failed", "payment warning", "overdue", "suspended", "deadline"],
      "urgency_sender_exclude": ["uob.com.sg", "scb.com", "standardchartered.com", "dbs.com", "dbs.com.sg"]
    },
    "calendar": { "working_days": [0, 1, 2, 3, 4], "preferred_focus_window": ["09:00", "12:00"], "free_gap_hook_time": "08:30" },
    "tasks": { "morning_digest_fallback_time": "08:00", "weekend_review_day": 5, "week_ahead_time": "19:00", "week_ahead_day": 6 },
    "finance": { "bank_sender_allowlist": ["uob.com.sg", "scb.com", "standardchartered.com", "dbs.com", "dbs.com.sg"], "recurring_min_occurrences": 2, "reconcile_date_window_days": 1, "reconcile_amount_exact": true, "unusual_spend_sigma": 2.0 },
    "reaction": { "fraud_confirm_amount_sgd": 500.0, "fraud_confirm_window_days": 7, "reconciler_nightly_time": "03:00", "maps_intl_buffer_minutes": 180, "maps_domestic_buffer_minutes": 90 }
  }
  ```

  — done when: `config/policy.example.json` exists; `RuntimeConfig.model_validate(json.loads(open("config/policy.example.json").read()))` succeeds and equals `RuntimeConfig()` (the example file IS the defaults).

- [ ] **Task 4: Tests** — files: `/Users/artemis-build/artemis/tests/test_runtime_config.py` — typed pytest.

  - **All-defaults:** `load_runtime_config(tmp_path / "absent.json")` → equals `RuntimeConfig()`; `.gmail.vip_senders == ("ashley", "debby")`.
  - **Full override round-trip:** write a `policy.json` with a changed `finance.recurring_min_occurrences=3` + changed `gmail.vip_senders=["boss"]` → `load_runtime_config(path)` reflects both; untouched keys keep defaults.
  - **Partial sub-model merge:** write `{"finance": {"recurring_min_occurrences": 3}}` → `cfg.finance.recurring_min_occurrences == 3` AND `cfg.finance.reconcile_date_window_days == 1` (default preserved) AND `cfg.gmail == GmailConfig()` (absent sub-model fully defaulted).
  - **Validation — bad time:** `{"calendar": {"free_gap_hook_time": "25:99"}}` → `load_runtime_config` raises `ValidationError`.
  - **Validation — bad weekday:** `{"tasks": {"weekend_review_day": 9}}` → raises.
  - **Validation — focus window order:** `{"calendar": {"preferred_focus_window": ["12:00", "09:00"]}}` → raises (start < end).
  - **Validation — unknown key:** `{"gmail": {"nope": 1}}` → raises (extra="forbid").
  - **Malformed JSON:** a file with `"{ not json"` → `load_runtime_config` raises (JSONDecodeError).
  - **Cache + reload:** `get_runtime_config()` twice → same object (identity); after rewriting the file + `reload_runtime_config()` → reflects the new value. (Use `runtime_config_path` via a `Settings(data_root=tmp_path)` fixture + monkeypatched `get_settings`.)
  - **Example file is the defaults:** `RuntimeConfig.model_validate(json.loads(Path("config/policy.example.json").read_text())) == RuntimeConfig()`.

  — done when: `uv run pytest -q tests/test_runtime_config.py` passes AND `uv run mypy --strict src tests/test_runtime_config.py` passes.

## Permissions

The following actions will run autonomously during build.
Approving this spec approves all of them.

### File Operations
| Action | Paths |
|--------|-------|
| Create | `/Users/artemis-build/artemis/src/artemis/runtime_config.py` |
| Create | `/Users/artemis-build/artemis/config/policy.example.json` |
| Create | `/Users/artemis-build/artemis/tests/test_runtime_config.py` |

### Commands
| Command | Purpose |
|---------|---------|
| `uv run mypy --strict src tests/test_runtime_config.py` | Type gate |
| `uv run ruff check . && uv run ruff format --check .` | Lint + format gate |
| `uv run pytest -q tests/test_runtime_config.py` | Test gate |

### Git Operations
| Operation | Scope |
|-----------|-------|
| `git add` | `src/artemis/runtime_config.py`, `config/policy.example.json`, `tests/test_runtime_config.py` |
| `git commit` | `"feat: X3 runtime-config layer — owner-editable policy.json for cluster tunables"` |

### Environment Access
| Variable | Purpose |
|----------|---------|
| `ARTEMIS_ENV_FILE` | Settings + slot_root resolution (off-hardware: tmp_path fixture) |

### Network
| Action | Purpose |
|--------|---------|
| (none) | Pure local file load; no deps |

## Specialist Context

### Security

- The config file is **owner-authored, trusted, local-only** — it never holds secrets (SQLCipher keys stay in Keychain/broker; this file has no key fields, mirroring the M0-a `Settings` no-secrets rule). A leaked `policy.json` exposes only tunable preferences (VIP names, thresholds), not credentials.
- Values are still **type + range validated** (defence against an owner typo turning a threshold into a nonsense value that silently breaks a hook). `extra="forbid"` makes a mistyped key a loud failure, not a silent no-op.
- The file sits at the **per-slot root** (`<data_root>/<slot>/policy.json`), not inside an encrypted scope dir, because it is not sensitive and the future client UI must read/write it without an owner-unlock (settings should be editable while the vault is locked). [apex-security note: confirm no sensitive default (e.g. a real personal VIP email beyond the two first-names) is committed to `policy.example.json`; the example uses generic placeholders.]

### Performance

- One JSON parse + one Pydantic validation per process (`@lru_cache`). Every downstream read is an attribute access on a frozen model — zero I/O. `reload_runtime_config()` is called only on an explicit owner settings-save (rare).

### Accessibility

(none — no frontend in X3; the client settings UI that edits this file is Wave U, deferred)

## Documentation

| Doc type | File | Action |
|----------|------|--------|
| Inline | `src/artemis/runtime_config.py` | Docstring every sub-model + field (what it tunes + which decision/spec consumes it); document the defaults-in-code / overrides-in-file split and the structural-constants-stay-in-code litmus |

## Acceptance Criteria

- [ ] `uv run mypy --strict src tests/test_runtime_config.py` → verify: exit 0.
- [ ] `uv run ruff check . && uv run ruff format --check .` → verify: both exit 0.
- [ ] `uv run pytest -q tests/test_runtime_config.py` → verify: all-defaults with no file; full + partial override merge; validation rejects bad time / weekday / focus-window-order / unknown key / malformed JSON; cache identity + reload; example file equals defaults.
- [ ] `uv run python -c "from artemis.runtime_config import RuntimeConfig, get_runtime_config; print(RuntimeConfig().gmail.vip_senders)"` → verify: prints `('ashley', 'debby')`.

## Progress
_(Coding mode writes here — do not edit manually)_
