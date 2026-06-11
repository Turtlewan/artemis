# DeepSeek V4-Flash as a Literal Code Executor — Research Profile
_Date: 2026-06-11 | Scope: executor calibration for Artemis spec pipeline (~60 specs)_

---

## 1. Model Identity & Specs

| Property | Value | Confidence |
|---|---|---|
| Total parameters | 284B MoE | HIGH — HuggingFace model card |
| Active parameters | ~13B | HIGH — HuggingFace model card |
| Context window (Flash) | 256K tokens (Flash API) / 1M tokens (Flash-Max) | HIGH — DeepSeek API docs, April 2026 preview |
| Max output tokens | 384K | MED — reported by multiple aggregators |
| Release date | April 24, 2026 (public preview) | HIGH — DeepSeek API docs |
| License | MIT | HIGH — HuggingFace model card |

Sources: [DeepSeek API docs](https://api-docs.deepseek.com/news/news260424), [HuggingFace](https://huggingface.co/deepseek-ai/DeepSeek-V4-Flash), [MorphLLM overview](https://www.morphllm.com/deepseek-v4)

---

## 2. Benchmark Profile

### Coding / SWE Benchmarks

| Benchmark | V4-Flash | V4-Pro | Notes | Confidence |
|---|---|---|---|---|
| SWE-bench Verified | 79.0% | 80.6% | DeepSeek self-reported; no independent Scale SEAL entry as of June 2026 | MED — internal claim, unverified |
| LiveCodeBench | 91.6% | 93.5% | Self-reported | MED — internal claim |
| Terminal-Bench 2.0 | **56.9%** | 67.9% | Key agentic gap; GPT-5.4 leads at 75.1% | MED — multiple aggregators confirm |

**Key observation:** The ~11-point Terminal-Bench gap between Flash and Pro is the most diagnostic number for Artemis. Terminal-Bench scores agentic, multi-step terminal execution — the closest proxy to "execute a 60-step spec without a human in the loop." Flash at 56.9% means ~43% of complex unattended tasks fail or deviate. For well-scoped, single-file tasks, Flash is essentially equivalent to Pro (79% vs 80.6% SWE-bench). The failure rate climbs as task complexity and step count increase.

Sources: [BenchLM.ai](https://benchlm.ai/models/deepseek-v4-flash), [BuildFastWithAI Flash review](https://www.buildfastwithai.com/blogs/deepseek-v4-flash-review-2026), [Framia benchmarks](https://framia.pro/page/en-US/news/deepseek-v4-benchmarks)

---

## 3. Executor Failure Mode Profile

### 3a. "Benchmark Maxed" / Real-World Sloppy Execution
**Confidence: MED** — community field reports, not reproducible paper

Multiple practitioners report that V4 models are "benchmark maxed" — optimized to score well on standardized tests but exhibiting "subpar, sloppy, and lazy" execution on practical tasks. In one structured 20-task test, Flash won 7/20 tasks outright but notably failed on complex multi-step implementations requiring logical consistency (e.g., rate-limiter logic was syntactically correct but logically flawed, requiring 3 iteration cycles to fix — Claude Opus 4.7 caught all issues in one pass).

Sources: [Kilo.ai Flash vs Claude test](https://blog.kilo.ai/p/we-tested-deepseek-v4-pro-and-flash), [Towards AI 20-task test](https://pub.towardsai.net/i-tested-all-4-deepseek-v4-modes-on-20-real-tasks-the-0-04-flash-won-7-of-them-0ef0fb5c1771), [BSWEN programming review](https://docs.bswen.com/blog/2026-05-07-deepseek-v4-flash-programming/)

### 3b. Long-Context Instruction Degradation
**Confidence: MED** — reported at model level, Flash-specific data limited

At 1M-token context, long-context retrieval (MRCR benchmark) drops to 66% accuracy (Pro-Max). Flash's 256K context sweet spot is 128K or below; feeding full large codebases (800K+ tokens) causes Flash to fail 2/3 multi-hop retrieval tasks that Pro-Max passes 3/3. For Artemis specs, which will likely be 10K–50K tokens per session, this is not the primary risk — but stacking many specs into a single context session without pruning will cause degradation.

Sources: [HuggingFace DeepSeek V4 blog](https://huggingface.co/blog/deepseekv4), [Kilo.ai comparative test](https://blog.kilo.ai/p/we-tested-deepseek-v4-pro-and-flash)

### 3c. Logic Flaws in Complex Multi-Step Code
**Confidence: MED** — structured test evidence

Flash produces syntactically valid code that contains semantic/logic bugs on complex multi-phase tasks (scheduling, lease expiry, validation chains). A scored test suite (100-point rubric) gave Flash 60/100, with failures concentrated in: lease expiry handling, scheduling correctness, validation edge cases, and build integrity. The test suite itself failed to run because Flash's generated setup script reset the database incorrectly before tests executed — a silent pre-flight failure.

Source: [Kilo.ai test](https://blog.kilo.ai/p/we-tested-deepseek-v4-pro-and-flash)

### 3d. Hallucinated Tool Schemas / Silent Tool Misrouting
**Confidence: MED** — reported by vLLM integration community

If using self-hosted V4 with vLLM or SGLang and default Jinja templates from V3-era guides, V4 will silently misroute tool calls — the output looks valid but reasoning content gets misparsed and tool calls are silently dropped or misrouted. This is a harness-configuration failure, not a model failure per se, but it is a real executor risk: the model produces output that appears correct but the agent's tool invocations are wrong.

Source: [vLLM V4 blog](https://vllm.ai/blog/2026-04-24-deepseek-v4), [DeepSeek developer guide](https://www.braincuber.com/tutorial/deepseek-v4-developer-guide-2026)

### 3e. Incomplete Implementations / Setup Script Failures
**Confidence: MED** — structured test evidence (one source)

Flash generated a setup script that silently broke pre-conditions (force-reset database before first test), causing the entire test suite to fail before exercising the actual code under test. This pattern — where the model generates code that is individually plausible but breaks the surrounding workflow — is a known executor antipattern. It is distinct from code bugs: the generated code looks complete but silently violates assumed environment state.

Source: [Kilo.ai test](https://blog.kilo.ai/p/we-tested-deepseek-v4-pro-and-flash)

### 3f. Tool-Calling JSON Reliability
**Confidence: HIGH** — DeepSeek internal data + community reports

JSON mode and function-calling reliability is "meaningfully better than V3." DeepSeek reports JSON parse rate improved from 78% → 85% → 97% (with regex post-processing). Empty content can be returned if the prompt does not steer the model correctly. JSON output can be truncated if `max_tokens` is set too low. Tool calling works reliably for chained multi-step calls under normal conditions; the failure mode is schema mismatch from stale harness templates (see 3d above).

Sources: [Macaron tool calling guide](https://macaron.im/blog/deepseek-v4-tool-calling), [DeepSeek JSON mode guide](https://deepseekai.guide/api/deepseek-api-json-mode/)

---

## 4. Context Window & Instruction-Following Fidelity

- Flash context: 256K tokens (confirmed). Flash-Max: 1M tokens.
- Reliable instruction-following zone: < 128K tokens per session. Above 256K, expect degradation.
- Architecture uses hybrid Compressed Sparse Attention (CSA) + Heavily Compressed Attention (HCA) for long-context efficiency — designed improvement over V3 but not lossless at max context.
- "Lost-in-the-middle" risk: instructions buried mid-context (not at start or end) are more likely to be missed. Standard LLM behavior; confirmed at the V4 generation. 
- For Artemis: each spec is likely 5K–20K tokens; the executor context per run (spec + relevant code + conversation history) should stay well under 128K for reliable fidelity. Do not accumulate many specs into a single context session.

Sources: [DeepSeek V4 context blog (HuggingFace)](https://huggingface.co/blog/deepseekv4), [DEV.to context article](https://dev.to/o96a/deepseek-v4-finally-a-context-window-built-for-agents-228h), [MorphLLM overview](https://www.morphllm.com/deepseek-v4)

---

## 5. Spec-Authoring Conventions for Literal Executors

Based on community best practices (Addy Osmani, Karpathy-style pre-flight, Dagster Python agent guides) and the Flash failure modes above:

### What Reduces Failure

1. **Explicit file lists per task.** Name every file to create/modify/delete. Never write "update the auth flow" — Flash will choose which files to touch and will sometimes choose wrong.

2. **Atomic, single-phase tasks.** One task = one logical change. Tasks that span multiple phases (e.g., "create DB schema AND wire up API AND write tests") invite partial execution where Flash completes the first phase and silently skips the rest.

3. **Self-contained snippets.** Provide actual function signatures, not pseudocode descriptions. Flash executing pseudocode will fill gaps with plausible-looking code that may be logically incorrect.

4. **No cross-references without resolution.** If a spec says "follow the pattern in auth module," Flash will hallucinate what that pattern is unless the actual code snippet is inlined. Cross-references require the executor to retrieve context; retrieval degrades with context length.

5. **Explicit acceptance criteria as runnable commands.** Each task should end with an exact shell command or assertion that the executor can run to verify completion. Flash will not self-verify unless told to.

6. **Environment pre-conditions stated explicitly.** Flash generated a setup script that assumed a clean DB but the environment was not clean (see 3e). State preconditions: "assumes X is not running," "assumes table Y does not exist," "run `clean.sh` before this step."

7. **Max tokens headroom.** JSON output truncates silently if `max_tokens` is too low. Set max output tokens generously (the 384K ceiling is not the constraint — the prompt's `max_tokens` parameter is).

Sources: [Addy Osmani - good spec for AI agents](https://addyosmani.com/blog/good-spec/), [Addy Osmani LLM workflow 2026](https://addyo.substack.com/p/my-llm-coding-workflow-going-into), [Dagster Python agent rules](https://dagster.io/blog/dignified-python-10-rules-to-improve-your-llm-agents), [Spec-to-code workflow](https://medium.com/@mattia.darge/the-spec-to-code-workflow-building-software-using-only-llms-5e025cd28de0)

---

## 6. Spec-Lint Checklist (Pre-Handoff to V4-Flash)

A spec should pass all items before being handed to the executor. Items marked [BLOCK] should stop the handoff; [WARN] are soft flags.

```
IDENTITY & SCOPE
[ ] [BLOCK] Spec has exactly one logical goal (not two builds merged)
[ ] [BLOCK] Spec does NOT reference "follow the pattern in X" without inlining the pattern

FILE EXPLICITNESS
[ ] [BLOCK] Every task names every file it touches (absolute path or project-root-relative)
[ ] [BLOCK] No task says "update relevant files" or "modify as needed"
[ ] [WARN]  New files: parent directory existence is confirmed or creation is explicit

TASK ATOMICITY
[ ] [BLOCK] No task has more than one logical phase (create + wire + test = 3 tasks, not 1)
[ ] [WARN]  Tasks with >3 sub-steps should be split

CODE DETAIL
[ ] [BLOCK] Function signatures are exact (name, args, return type) — not described in prose
[ ] [BLOCK] No "implement as appropriate" or "add error handling" without specifying what
[ ] [WARN]  Pseudocode present: flag for replacement with actual code snippet

ACCEPTANCE CRITERIA
[ ] [BLOCK] Every task has at least one runnable check (shell command, test, assertion)
[ ] [WARN]  Criteria that require human judgment ("looks correct") are flagged

ENVIRONMENT PRE-CONDITIONS
[ ] [WARN]  Any task that touches a database, file system, or service names its preconditions
[ ] [WARN]  Any destructive operation (drop, delete, overwrite) is explicitly gated

CONTEXT SIZE
[ ] [WARN]  Spec + all inlined snippets > 50K tokens: flag for splitting
[ ] [BLOCK] Spec references a file larger than 10K tokens without quoting only the relevant section

CROSS-REFERENCES
[ ] [BLOCK] Any "see ADR-XXX" or "per the architecture doc" must either be resolved inline or
           the referenced section must be quoted directly in the spec
[ ] [WARN]  External URLs referenced: confirm content is stable and accessible to executor

COMMANDS
[ ] [BLOCK] Every "Commands to run" section has exact commands with flags (no "run the tests")
[ ] [WARN]  Commands that require env vars: those vars are listed with expected values

OUTPUT TOKENS
[ ] [WARN]  If spec will generate a file > 500 lines, break into incremental tasks with
           intermediate verification steps (Flash may truncate large single-output generations)
```

---

## 7. Overall Executor Verdict

**V4-Flash is a conditionally reliable literal executor.** On well-scoped, single-file, sub-200-line tasks with explicit acceptance criteria, it is essentially equivalent to Pro (79% vs 80.6% SWE-bench). Reliability degrades significantly on:
- Multi-phase tasks (Terminal-Bench gap: 56.9% Flash vs 67.9% Pro)
- Tasks that require retrieving context from long accumulated conversation history
- Tasks with any ambiguity in file targeting or function signatures
- Tasks that assume environment state without stating it

For the Artemis pipeline of ~60 specs: **spec quality is the primary failure variable, not model capability.** A well-linted spec handed to Flash will likely execute correctly. An ambiguous spec handed to Flash will produce plausible-looking but logically incorrect code — syntactically valid, semantically wrong — which is the worst failure mode because it is hard to detect without running tests.

**Recommended approach:** Run the spec-lint checklist before every handoff. Use Pro only for specs that have > 3 files, > 2 logical phases, or touch a shared abstraction. Use Flash for everything else.

---

_Research conducted: 2026-06-11. Sources: web search + aggregator data. All DeepSeek benchmark numbers are self-reported unless noted otherwise. No independent SWE-bench verification for V4 exists as of this date._
