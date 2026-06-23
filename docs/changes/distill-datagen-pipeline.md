---
spec: distill-datagen-pipeline
status: ready
token_profile: lean
autonomy_level: L2
---
<!-- amended 2026-06-11 per contracts.md (Seam 1) + m7-cap-teacher-distill.md BLOCKs B5; FLAGs F10, F11; UPGRADE U6 -->

# Spec: Tier-2 distillation data-generation pipeline (offline, Windows PC, pre-Mac)

**Identity:** An offline Python CLI pipeline — runs on the Windows PC now — that generates a versioned JSONL reasoning-trace dataset for fine-tuning a smaller student model. Six task categories; Claude-subscription teacher (via `claude -p` headless); DeepSeek-API-as-judge quality filter; near-dedup + per-category balance; hold-out eval set; Git-tracked output under `datasets/distill/`.
→ design: `docs/research/self-training-local-model.md` § "Recommended minimal high-value path" · `docs/research/homelab-control-plane.md` § "Capability / self-training workstream (P0)".

<!-- Split rule: TWO logical phases (1: generate + judge-filter; 2: dedup + balance + output + versioning). ~5 src files. Justified atomic exception: all five files are links in one linear pipeline (prompts→generate→judge→dedup→write) that must be tested end-to-end; sub-splitting leaves a pipeline that can't be exercised at all. Flagged per rules. -->

<!-- WINDOWS-ONLY scope: NO mlx, NO Apple-only deps. All teacher/judge calls go through subprocess or HTTP API. Training run (mlx_lm.lora) is a SEPARATE Mac-side spec — this spec produces the training-ready JSONL; it does not touch mlx. -->

<!-- RESERVATION (architecture-validation 2026-06-23, reservation H2 — recipe re-seed path; ADR-022 Refinement 2026-06-23): besides generating the initial trace dataset, reserve a RE-SEED/REFRESH mode that re-authors traces/recipes flagged `needs_reseed` by M7-b (those distilled under a weak/unavailable teacher) once a stronger teacher rung is available — so a degraded seeding window can't permanently imprint the local recipe library. Pair with the pluggable teacher seam (Claude or Codex) the ADR-022 Refinement 2026-06-22 already adds here. Producer only; M7-b owns the flag/gate. Not built now — reserved mode. -->
<!-- Also pending (ADR-022 Refinement 2026-06-22): add sensitive-domain (finance/health/journal/memory) reasoning categories to the six task categories + the pluggable Codex teacher, for the Codex-distilled sensitive_reasoner. -->

## Resolved seams (planning, 2026-06-09)
All four draft-stage parks are resolved; this spec is `status: ready`.

| # | Question | Resolution |
|---|----------|------------|
| P1 | Teacher CLI on Windows | **VERIFIED on the Windows build machine 2026-06-09:** `claude -p "<prompt>" --output-format json` returns parseable JSON; the completion is in the top-level `.result` string; `.is_error` (bool) flags failure. Use exactly this. **NB — fixed per-call overhead ≈ 44k tokens** (full context reloads each invocation); see § Planning refinement: batched generation. On the subscription this is quota, not dollars (ADR-001 flat-rate). |
| P2 | DeepSeek judge config | **New secret.** Env vars: `DEEPSEEK_API_KEY` (required) + `DEEPSEEK_BASE_URL` (default `https://api.deepseek.com/v1`) + `DEEPSEEK_JUDGE_MODEL` (default `deepseek-chat`). Add `DEEPSEEK_API_KEY` to `docs/bring-up/SECRETS-INVENTORY.md` and a `.env` example. The judge sees only synthetic traces (no owner data). |
| P3 | `datasets/` Git tracking | **Git-tracked, plain** (JSONL is tens of MB at pilot/v1 scale). Ensure no `.gitignore` pattern matches `datasets/`; add `!datasets/` if needed. Revisit Git LFS only if a version exceeds ~100 MB. |
| P4 | pyproject structure | **Standalone** `tools/distill/pyproject.toml` (isolated uv project). Do NOT add to / touch the brain's root `pyproject.toml` or its locked deps. |

## Planning refinement: batched generation (amortise teacher overhead)
Each `claude -p` call carries a large fixed context-load cost (~44k tokens observed). Generating one trace
per call multiplies that overhead by the trace count. **Therefore the teacher generates a BATCH of traces
per call**, not one:
- `Category` gains `batch_size: int = 10`. The `user_prompt_template` asks the teacher for **`{k}` distinct
  trace instances in one response**, each wrapped in its own `<trace>…</trace>` block (containing the
  `<task>/<reasoning>/<answer>` tags). The pipeline issues `ceil(target_raw / batch_size)` calls per
  category instead of `target_raw` calls — a ~10× reduction in fixed-overhead.
- `_parse_trace` is preceded by a `_split_traces(raw) -> list[str]` that extracts each `<trace>` block;
  each block is then parsed by the existing `_parse_trace`. A malformed block is dropped + logged (never
  raises). A call returning fewer than `k` parseable traces is acceptable (logged; the shortfall is **not** retried — the pipeline issues a fixed `ceil(target_raw / batch_size)` calls, so final per-category counts may land slightly under target. This is intentional; the pilot validates whether the fixed count yields acceptable totals. "The next call covers the remaining target" is retracted — it contradicts the fixed-call rule.)
- This changes Tasks 2, 3, 5 as noted inline below. `FakeTeacher` returns a batch of `k` `<trace>` blocks.

## Assumptions
- **No runtime brain code.** This pipeline is a standalone offline tool, NOT part of `src/artemis/`. It lives under `tools/distill/` (a new top-level directory). Output JSONL is consumed by a later Mac-side training spec. Do NOT import from `artemis.*`; no shared ports from the brain.
- **Teacher = Claude via `claude -p` headless** (ADR-001 flat-rate subscription). Adapter shells out via `subprocess.run`. Interface verified — see Resolved seam P1.
- **Judge = DeepSeek API.** Config per Resolved seam P2. The judge receives only the generated synthetic trace — never owner personal data. A `FakeJudge` runs the full pipeline in tests with no network.
- **Dataset path** = `datasets/distill/` at repo root, Git-tracked (Resolved seam P3). Created by the pipeline if absent.
- **Python toolchain**: `uv`/`ruff`/`mypy --strict`/`pytest`. Standalone `tools/distill/pyproject.toml` (Resolved seam P4); add `httpx` + `tenacity`.
- **No MLX / no Apple-only deps.** Dedup uses `hashlib`-based SimHash (no model call). JSONL is training-ready (`{"messages": [...]}` chat format) so the Mac-side `mlx_lm.lora` spec consumes it without transformation.
- **Cloud-safety:** all generated content is synthetic. The pipeline MUST NOT read any file from `/opt/artemis` or any brain SQLCipher store.
- **Hold-out set**: 10–15% of post-filter traces, stratified per category, written to a separate `eval.jsonl`, never in `train.jsonl`. Deterministic given the seed.

Simplicity check: considered reusing `ClaudeCliModelPort` from M7-a2 — not possible (M7-a2 is Mac-only, depends on `artemis.*` ports unavailable here; the subprocess pattern is replicated simply). Considered a vector embedding model for dedup — rejected (no model on Windows PC; SimHash over tokens suffices for near-dup at this scale). Considered a DB for pipeline state — rejected (JSONL + a manifest JSON is the minimum for a one-shot offline pipeline).

## Files to Change

| File | Operation | Notes |
|------|-----------|-------|
| `<repo-root>/.gitignore` | modify-or-create | add `!datasets/` if needed (P3/B5 — ensure datasets/ is Git-tracked) |
| `tools/distill/pyproject.toml` | create | standalone uv project; deps: `httpx`, `tenacity`; dev: `ruff`, `mypy`, `pytest` |
| `tools/distill/distill/__init__.py` | create | package marker |
| `tools/distill/distill/categories.py` | create | 6 category definitions + prompt templates + `batch_size` |
| `tools/distill/distill/teacher.py` | create | `TeacherAdapter` — subprocess to `claude -p` headless |
| `tools/distill/distill/judge.py` | create | `JudgeAdapter` + `JudgeScore`; `JudgePort` Protocol + `FakeJudge` |
| `tools/distill/distill/pipeline.py` | create | `DatagenPipeline.run()` — generate(batch)→split→judge→dedup→balance→write |
| `tools/distill/distill/output.py` | create | JSONL writer + manifest + train/eval split |
| `tools/distill/tests/test_pipeline.py` | create | end-to-end pipeline test with `FakeTeacher` + `FakeJudge` |
| `docs/bring-up/SECRETS-INVENTORY.md` | modify | add `DEEPSEEK_API_KEY` entry (P2/F11) |

## Tasks

### Task 1: Scaffold the standalone tool project
**Files:** `tools/distill/pyproject.toml`, `tools/distill/distill/__init__.py`

- `pyproject.toml`: `[project] name = "artemis-distill" version = "0.1.0" requires-python = ">=3.12"`. Runtime deps: `httpx>=0.27`, `tenacity>=8`. Dev deps: `ruff`, `mypy`, `pytest`. `[tool.mypy] strict = true`. `[tool.ruff.lint] select = ["E","F","I"]`. Entry point: `[project.scripts] distill = "distill.pipeline:main"`.
- `distill/__init__.py`: empty package marker.
- **P3 gitignore (B5):** check `<repo-root>/.gitignore`; if any pattern would exclude `datasets/`, add `!datasets/` to ensure the directory is Git-tracked. File: `<repo-root>/.gitignore` (create if absent; otherwise append). This task has no other owner.
- **P2 doc edit (F11):** add to `docs/bring-up/SECRETS-INVENTORY.md` an entry for `DEEPSEEK_API_KEY` (required for judge) + `DEEPSEEK_BASE_URL` (default `https://api.deepseek.com/v1`) + `DEEPSEEK_JUDGE_MODEL` (default `deepseek-chat`). **No dotenv loading in the pipeline** — document usage as `$env:DEEPSEEK_API_KEY = "..."` (PowerShell) or set in the shell env before running. The pipeline reads env vars directly via `os.environ.get`.

Done when: `uv sync` succeeds inside `tools/distill/` and `uv run python -c "import distill"` exits 0; repo-root `.gitignore` does not suppress `datasets/`; `DEEPSEEK_API_KEY` documented in SECRETS-INVENTORY.md.

---

### Task 2: Define the 6 task categories + prompt templates
**Files:** `tools/distill/distill/categories.py`

Frozen dataclass `Category`:
```python
@dataclass(frozen=True)
class Category:
    key: str          # slug, e.g. "scheduling_calendar"
    display_name: str
    system_prompt: str
    user_prompt_template: str  # receives {k} (traces wanted this call) and {start} (instance index base)
    target_count: int          # post-nothing raw target per category (configurable)
    batch_size: int = 10       # traces requested per teacher call (amortises overhead — see refinement)
```

Define exactly these 6 instances in `CATEGORIES: tuple[Category, ...]` (no others):

| `key` | `display_name` | Default `target_count` |
|---|---|---|
| `scheduling_calendar` | Scheduling & calendar reasoning | 200 |
| `email_triage` | Email triage & urgency classification | 200 |
| `second_brain_qa` | Second-brain Q&A and multi-hop synthesis | 200 |
| `task_project_planning` | Task & project planning / decomposition | 200 |
| `voice_drafting` | Drafting in the owner's voice | 150 |
| `research_tool_use` | Multi-hop research & tool-use reasoning | 150 |

Total default = 1,100 traces (pilot; scale via `--count-per-category`).

Each `user_prompt_template` instructs the teacher to produce **`{k}` distinct synthetic instances** for the category, each with full chain-of-thought, wrapped as:
```
<trace><task>...</task><reasoning>...</reasoning><answer>...</answer></trace>
```
…repeated `{k}` times. The `{start}` value lets the prompt vary instances across calls. Skeleton for `scheduling_calendar`:
```python
user_prompt_template = (
    "Generate {k} DISTINCT synthetic scheduling tasks (indices starting at {start}). "
    "For each: produce a realistic calendar/scheduling problem, reason step-by-step "
    "(full chain of thought), then give the final answer. "
    "Wrap EACH one as <trace><task>...</task><reasoning>...</reasoning><answer>...</answer></trace>."
)
```
Adapt wording per category (same tag structure; change domain).

Done when: `uv run mypy --strict distill/categories.py` exits 0; `len(CATEGORIES) == 6`; `target_count` sums to 1,100.

---

### Task 3: Implement the teacher adapter
**Files:** `tools/distill/distill/teacher.py`

```python
class TeacherPort(Protocol):
    def complete(self, system: str, user: str) -> str: ...

class TeacherAdapter:
    """Calls `claude -p <prompt> --output-format json` as a subprocess.
    VERIFIED interface (planning 2026-06-09): JSON stdout; completion in .result; .is_error flags failure.
    U6: resolves the executable via shutil.which (handles .cmd/.ps1 shims on Windows without shell=True).
    """
    def __init__(self, *, timeout_s: int = 600) -> None:
        # U6: resolve at init; raise immediately if not found
        import shutil
        exe = shutil.which("claude")
        if exe is None:
            raise RuntimeError("claude CLI not found on PATH — install and log in first")
        self._exe = exe
        # timeout_s=600: sized for a batch of 10 full-CoT traces (180s was sized for one trace)
    def complete(self, system: str, user: str) -> str:
        # prompt = system + "\n\n" + user  (single string; no multi-turn)
        # proc = subprocess.run([self._exe, "-p", prompt, "--output-format", "json"],
        #                       capture_output=True, text=True, timeout=timeout_s)
        # U6: use self._exe (resolved at init) — handles .cmd/.ps1 shims on Windows
        # data = json.loads(proc.stdout); if data.get("is_error") or proc.returncode != 0:
        #     raise TeacherCallError(proc.stderr or data)
        # return str(data["result"])
        ...

class FakeTeacher:
    """Returns a deterministic BATCH of k <trace> blocks for tests."""
    def __init__(self, *, batch_size: int = 10) -> None: ...
    def complete(self, system: str, user: str) -> str:
        # return batch_size repetitions of:
        # "<trace><task>Synthetic task</task><reasoning>Step 1. Step 2.</reasoning><answer>42</answer></trace>"
        ...

class TeacherCallError(Exception): ...
```
`complete` is **synchronous** (offline batch). Decorate with `tenacity.retry(stop=stop_after_attempt(3), wait=wait_exponential(min=4, max=30))` for transient subprocess failures. The batch size to request is passed by the pipeline via the rendered `user` prompt (`{k}`); the adapter itself is batch-agnostic (one call → one response string).

Done when: `uv run mypy --strict distill/teacher.py` exits 0; `FakeTeacher().complete("s","u")` returns a string containing at least one `<trace>` and `<reasoning>`.

---

### Task 4: Implement the DeepSeek judge adapter
**Files:** `tools/distill/distill/judge.py`

```python
@dataclass(frozen=True)
class JudgeScore:
    trace_id: str          # sha256 of the trace content
    score: float           # 0.0–1.0; keep threshold = 0.6
    reasoning: str         # one-sentence rationale (logged, not in output JSONL)
    passed: bool           # score >= threshold

class JudgePort(Protocol):
    def score(self, task: str, reasoning: str, answer: str) -> JudgeScore: ...

class JudgeAdapter:
    """DeepSeek chat-completions API as judge (Resolved seam P2).
    Config: DEEPSEEK_API_KEY (required), DEEPSEEK_BASE_URL (default https://api.deepseek.com/v1),
    DEEPSEEK_JUDGE_MODEL (default deepseek-chat). httpx client.
    """
    def __init__(self, *, api_key: str | None = None, base_url: str | None = None,
                 model: str | None = None, threshold: float = 0.6) -> None: ...
    def score(self, task: str, reasoning: str, answer: str) -> JudgeScore: ...

class FakeJudge:
    """Deterministic pass/fail by content hash vs pass_rate (default pass all).
    passed = (int(sha256((task+reasoning+answer).encode()).hexdigest(), 16) % 100) / 100 < pass_rate
    (so pass_rate=0.0 → never passes, 1.0 → always passes, 0.5 → deterministic ~half by hash)."""
    def __init__(self, *, pass_rate: float = 1.0) -> None: ...
    def score(self, task: str, reasoning: str, answer: str) -> JudgeScore: ...
```
Judge prompt:
```
System: "You are a quality-filter judge. Score the reasoning trace 0.0–1.0 on: (1) chain-of-thought
completeness — real steps, not just a conclusion; (2) factual plausibility — answer follows from reasoning;
(3) task relevance. Respond JSON: {\"score\": <float>, \"reasoning\": \"<one sentence>\"}."
User: "Task: {task}\nReasoning: {reasoning}\nAnswer: {answer}"
```
Parse JSON; on parse failure retry once via `tenacity`; on second failure assign `score=0.0` + log warning (never skip silently — always return a `JudgeScore`).

Done when: `uv run mypy --strict distill/judge.py` exits 0; `FakeJudge(pass_rate=0.5).score(...)` returns a `JudgeScore` with `passed` in `{True, False}` by hash.

---

### Task 5: Implement the core pipeline
**Files:** `tools/distill/distill/pipeline.py`

```python
@dataclass
class PipelineConfig:
    count_per_category: int = 200      # raw target per category (before filtering)
    judge_threshold: float = 0.6
    dedup_threshold: float = 0.85      # SimHash similarity
    hold_out_fraction: float = 0.12    # 10–15%
    seed: int = 42
    output_dir: Path = Path(__file__).resolve().parents[3] / "datasets" / "distill"
    # B5: default resolves to repo-root datasets/distill/ regardless of cwd (P3: Git-tracked).
    # The --output-dir CLI arg overrides this; pass an absolute path.
    version: str = "v0.1"

class DatagenPipeline:
    def __init__(self, teacher: TeacherPort, judge: JudgePort, config: PipelineConfig | None = None) -> None: ...
    def run(self) -> DatasetManifest:
        """
        Per category (in order):
          1. issue ceil(count_per_category / category.batch_size) teacher calls, each requesting
             {k}=batch_size traces (passing a {start} index that advances per call)
          2. _split_traces(raw) -> list[str]; _parse_trace(block) -> (task, reasoning, answer) | None
             (drop+log unparseable blocks)
          3. judge.score each; drop score < threshold (log count)
          4. SimHash dedup within the category (drop near-dups; log count)
        After all categories:
          5. global SimHash dedup across categories (log count)
          6. balance: subsample any category > 2× the minimum post-filter count (deterministic by seed)
          7. stratified train/eval split per category (hold_out_fraction)
          8. write train.jsonl + eval.jsonl + manifest.json via OutputWriter
          9. return DatasetManifest
        """
        ...
```
Inline helpers (not separate files): `_split_traces(raw) -> list[str]` (extract `<trace>` blocks via `re.findall`), `_parse_trace(block) -> tuple[str,str,str] | None` (extract task/reasoning/answer via `re.search`; None if any missing), `_simhash(text, n_bits=64) -> int` (token-level SimHash), `_simhash_similar(a, b, threshold) -> bool` (Hamming distance / 64 <= 1 - threshold). SimHash dedup is O(n²) in-order (≤2,000/category — acceptable).

CLI `main()` (argparse): `--count-per-category` (default 200), `--version` (default v0.1), `--output-dir` (default datasets/distill), `--seed` (default 42), `--dry-run` (use `FakeTeacher`+`FakeJudge`, no API). Builds `PipelineConfig`, selects real vs fake adapters, runs, prints summary.

Done when: `uv run mypy --strict distill/pipeline.py` exits 0; `DatagenPipeline(FakeTeacher(), FakeJudge()).run()` completes (tested Task 7).

---

### Task 6: Implement the JSONL output writer + manifest
**Files:** `tools/distill/distill/output.py`

```python
@dataclass
class TraceRecord:
    id: str                   # sha256(task+reasoning+answer)[:16]
    category_key: str
    messages: list[dict[str, str]]   # [{"role":"user","content":task},
                                     #  {"role":"assistant","content":reasoning+"\n\n"+answer}]
    judge_score: float
    split: Literal["train", "eval"]

@dataclass
class DatasetManifest:
    version: str
    created_at: str           # ISO-8601 UTC
    total_train: int
    total_eval: int
    per_category: dict[str, dict[str, int]]  # {cat: {train, eval, dropped_judge, dropped_dedup}}
    generation_params: dict[str, object]
    output_dir: str
    train_file: str
    eval_file: str

class OutputWriter:
    def __init__(self, output_dir: Path, version: str) -> None: ...   # creates output_dir/version/
    def write(self, records: list[TraceRecord]) -> DatasetManifest: ...
```
Writes under `datasets/distill/<version>/`: `train.jsonl` (bare `{"messages": [...]}`), `eval.jsonl` (`{"id","category_key","messages"}`), `manifest.json`. All writes utf-8, `newline="\n"`, atomic (`.tmp` then `os.replace`).

Done when: `uv run mypy --strict distill/output.py` exits 0; `OutputWriter(tmp,"v0.1").write([...])` produces three files; manifest round-trips; each `train.jsonl` line parses as `{"messages":[{"role":"user",...},{"role":"assistant",...}]}`.

---

### Task 7: Write the end-to-end pipeline tests
**Files:** `tools/distill/tests/test_pipeline.py`

Typed pytest, `FakeTeacher`+`FakeJudge`, no network:
1. **Full dry run** (`count_per_category=5`, tmp output): train/eval/manifest exist; `total_train+total_eval <= 6*5`; messages have user+assistant roles.
2. **Judge filter** (`FakeJudge(pass_rate=0.0)`): `total_train==0` and `total_eval==0`; empty files written (not missing).
3. **Hold-out fraction** (`pass_rate=1.0`, `count=20`, `hold_out=0.1`): eval fraction per category in [0.08, 0.15].
4. **SimHash dedup**: inject near-identical traces → kept count < injected count.
5. **Unparseable trace**: teacher returns no tags → dropped gracefully (no exception; logged; manifest drop count > 0).
6. **Manifest round-trip**: `manifest.json` re-parses; all `generation_params` keys present.
7. **Train JSONL format**: every line has exactly key set `{"messages"}`.
8. **Eval JSONL extras**: every line has `id`, `category_key`, `messages`.
9. **Batch split**: a `FakeTeacher(batch_size=10)` response yields 10 parsed traces from one `complete()` call (verifies `_split_traces`).
10. **mypy**: `uv run mypy --strict distill/ tests/` exits 0.

Done when: `uv run pytest -q tests/test_pipeline.py` passes AND `uv run mypy --strict distill/ tests/` passes.

## Acceptance Criteria
- [ ] **Task 1** — In PowerShell: `cd tools/distill; uv sync` exits 0; `uv run python -c "import distill"` exits 0. (F10: `&&` is a parser error in PowerShell 5.1; use `;` or separate commands.)
- [ ] **Task 2** — `uv run python -c "from distill.categories import CATEGORIES; assert len(CATEGORIES)==6"` exits 0.
- [ ] **Task 3** — `uv run mypy --strict distill/teacher.py` exits 0; `uv run python -c "from distill.teacher import FakeTeacher; assert '<trace>' in FakeTeacher().complete('s','u')"` exits 0.
- [ ] **Task 4** — `uv run mypy --strict distill/judge.py` exits 0; `uv run python -c "from distill.judge import FakeJudge; s=FakeJudge().score('t','r','a'); assert hasattr(s,'passed')"` exits 0.
- [ ] **Task 5** — `uv run mypy --strict distill/pipeline.py` exits 0.
- [ ] **Task 6** — `uv run mypy --strict distill/output.py` exits 0.
- [ ] **Task 7** — `uv run pytest -q tests/test_pipeline.py` passes; `uv run mypy --strict distill/ tests/` exits 0.
- [ ] **Ruff gate** — `uv run ruff check distill/ tests/` exits 0; `uv run ruff format --check distill/ tests/` exits 0. (Run as separate commands — F10.)
- [ ] **Dry-run CLI smoke** — `uv run distill --dry-run --count-per-category 2 --version smoke --output-dir <absolute-repo-root-path>/datasets/distill` creates `train.jsonl`/`eval.jsonl`/`manifest.json` under repo-root `datasets/distill/smoke/`; no exceptions. (B5: pass an absolute path so output lands at the P3-tracked location regardless of cwd.)

## Commands to Run
<!-- F10: Windows PowerShell 5.1 — && is a parser error. Use separate lines or semicolons. Run from within tools/distill/ or use Set-Location first. -->
```powershell
# Run from the tools/distill/ directory (cd tools/distill first in PowerShell)
uv sync
uv run mypy --strict distill/ tests/
uv run ruff check distill/ tests/
uv run ruff format --check distill/ tests/
uv run pytest -q tests/test_pipeline.py

# Dry-run end-to-end (no API calls) — --output-dir MUST be absolute so output lands at the P3-tracked location regardless of cwd (B5)
uv run distill --dry-run --count-per-category 5 --version smoke --output-dir <absolute-repo-root-path>/datasets/distill

# Real pilot run (requires $env:DEEPSEEK_API_KEY set + claude CLI logged in)
$env:DEEPSEEK_API_KEY = "sk-..."
uv run distill --count-per-category 200 --version pilot --output-dir datasets/distill

# v1 run (5k–10k traces; after pilot validates quality)
uv run distill --count-per-category 1500 --version v1 --output-dir datasets/distill
```

## Progress
_(Coding mode writes here — do not edit manually)_
