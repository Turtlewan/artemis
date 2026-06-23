# Codex-on-ChatGPT-subscription: intra-GPT model tiering — research

- **Date:** 2026-06-23
- **For:** Artemis M9 Task Executor (ADR-022 cloud-reasoner path)
- **Question:** Can the Codex-CLI-on-ChatGPT-subscription path select among GPT model tiers programmatically (cheap "mini" vs full model), or does intra-GPT tiering require the metered OpenAI Platform API for the cheaper calls?

---

## Bottom line

**Yes — intra-GPT tiering works *entirely inside* the ChatGPT subscription, programmatically.** The Codex CLI exposes multiple GPT tiers when signed in with a ChatGPT plan (Plus/Pro), and the model is user-selectable per invocation via `--model` / `-m`, via `config.toml`, via named `--profile`s, and via the in-session `/model` command. A genuine cheaper tier — **`gpt-5.4-mini`** — is available on subscription sign-in, and selecting it **directly stretches the same subscription quota** (mini carries a much larger per-window message allowance than the flagship). **No metered api.openai.com calls are required to do tiering.** The hybrid (subscription strong-model + metered API cheap-model) is therefore a *fallback*, not a necessity.

**Recommendation for M9:** Implement intra-GPT tiering as `--model` selection inside the single Codex-subscription path. Map the task-tier → model in `roles.toml` / a Codex `--profile`:
- **Hard reasoning** → `gpt-5.5` (or `gpt-5.4` as the workhorse).
- **Easy/mechanical steps + subagents** → `gpt-5.4-mini`.
- (Optional) **near-instant iteration** → `gpt-5.3-codex-spark` (Pro-only research preview).

This stays under the per-task token budget *and* the 5h/weekly caps without introducing a second billing path. Keep the metered-API rung (already H1 rung 2 conceptually) as the documented fallback only.

---

## (1) Models the Codex CLI exposes + is the model user-selectable on a ChatGPT subscription?

**Selectable: yes.** Methods (all work on ChatGPT sign-in):
- CLI flag: `codex -m gpt-5.4` or `codex --model gpt-5.4 "…"` (works with `codex exec` too).
- Config: a `model = "…"` entry in `config.toml` for a persistent default.
- Profiles: `codex --profile ci-pipeline "…"` — named, workflow-specific routing.
- In-session: `/model` to switch mid-thread.
- IDE: model selector under the input box.

**Models exposed on ChatGPT sign-in (Plus/Pro):**

| Model | Role (OpenAI's framing) | Subscription | API key |
|---|---|---|---|
| `gpt-5.5` | Newest frontier — complex coding, computer use, knowledge work, research | ✅ | ❌ *(per OpenAI docs — see conflict note)* |
| `gpt-5.4` | Flagship workhorse, strong coding + tool/computer use | ✅ | ✅ |
| `gpt-5.4-mini` | **Fast, lower-cost mini** for lighter tasks / subagents | ✅ | ✅ |
| `gpt-5.3-codex` | Proven coding specialist (deprecating) | ✅ | ✅ |
| `gpt-5.3-codex-spark` | Research preview, ~1,000+ tok/s real-time iteration | ✅ (Pro) | ✅ (Pro) |

- *Confidence: High · recency: mid-2026 (developers.openai.com/codex/models + May-2026 routing analysis).*
- OpenAI's own guidance for ChatGPT-authenticated sessions: **don't pin a model name** — let Codex default to the current recommended model. For Artemis we *do* want to pin, because tiering is the whole point; pinning is supported.

## (2) Is the subscription Codex backend single-model or multi-tier?

**Multi-tier.** The subscription is not locked to one model — all five tiers above are reachable on a ChatGPT plan, and `gpt-5.4-mini` is a real economy tier (not just a cosmetic alias). `gpt-5.5` is the notable one that is **subscription-gated** — per OpenAI's models doc it is available on ChatGPT sign-in but *not* via API-key auth ("It is **not** available via API-key authentication at this time"). So the subscription is, if anything, the *only* path to the strongest tier.

- *Confidence: High (multi-tier) · recency: mid-2026.*

**Conflict to flag (Confidence: Medium):** OpenAI's official Codex models doc and the danielvaughan routing analysis both say `gpt-5.5` is **not** available via API key. Some third-party pricing aggregators (aipricing.guru) *do* list a `gpt-5.5` API price ($5/1M in, $30/1M out). Treat the official OpenAI doc as authoritative — assume `gpt-5.5` is subscription-only until the owner confirms otherwise on their account; the aggregator may be speculative or front-running an unreleased API SKU. This does not affect the M9 recommendation (tiering happens inside the subscription regardless).

## (3) Rate-limit / quota implications of tiering on the subscription

Codex on a ChatGPT plan uses a **5-hour rolling window + weekly cap**, shared across local CLI messages and cloud tasks. Crucially, **the message allowance is per-model**, so a cheaper model buys *far more* turns inside the same plan — switching to mini is the documented way to make limits "last longer."

Indicative **Plus** allowances (local messages per 5h window, mid-2026 — ranges because OpenAI scales by load):

| Model | Messages / 5h (Plus) |
|---|---|
| `gpt-5.5` | ~15–80 |
| `gpt-5.4` | ~20–100 |
| `gpt-5.4-mini` | ~60–350 |

- **Pro ($100)** ≈ 5× Plus; the higher Pro ($200) ≈ 20× headroom (consistent with ADR-022's 5×/20× figures).
- The CLI/IDE surfaces remaining budget directly, e.g. `Rate Limits Remaining: 5h 96%, Weekly 94%` — Artemis's executor can read this to drive tier-down decisions.
- **Caveat (Confidence: Medium · recency: very fresh):** an open Codex issue (#28879, ~June 16 2026) reports the per-token rate-limit *cost* of `gpt-5.5` on Plus jumping ~10–20×, draining the 5h budget in 2–3 prompts. Whether a transient incident or a permanent re-weighting, it reinforces ADR-022's stance: **the cheap-tier + local-trigger discipline is load-bearing**, and the pluggable fallback must be real. Reserving full `gpt-5.5` for genuinely-hard steps (exactly the M9 design) is the correct hedge.

*Net: tiering on the subscription is not just possible — it is the intended quota-management lever. Routing easy steps to `gpt-5.4-mini` multiplies effective throughput ~4× under the same flat subscription cost.*

- *Confidence: High (mechanism + direction) · Medium (exact numbers, which OpenAI tunes) · recency: mid-2026.*

## (4) If subscription tiering were impossible — the cleanest hybrid + cost shape

It is *not* impossible, so this is the **fallback rung only** (aligns with ADR-022 H1 rung 2). Shape if ever needed:
- **Strong model** → keep on the Codex subscription (`gpt-5.5` / `gpt-5.4`), flat cost.
- **Cheap model** → metered api.openai.com `gpt-5.4-mini`: **$0.75 / 1M input, $4.50 / 1M output** (90% cached-input discount on 5.x; Batch/Flex −50% for non-urgent). `gpt-5.4` API = $2.50 / $15.00; `gpt-5.5` API ≈ $5 / $30 *if* it becomes API-available.
- **Cost shape:** a mechanical step at ~2k in / 1k out on `gpt-5.4-mini` ≈ $0.0015 + $0.0045 ≈ **$0.006/call** (well under a cent). For Artemis's volume this is marginal — but it adds a *second billing path, second auth, second failure mode* for zero capability gain over in-subscription mini. **Only adopt if** the subscription's mini allowance is exhausted or the undocumented backend degrades.

- *Confidence: High (prices) · recency: mid-2026.*

## (5) Confidence + recency summary

| Finding | Confidence | Recency |
|---|---|---|
| Model is programmatically selectable on subscription (`-m`/config/profile/`/model`) | **High** | mid-2026 |
| `gpt-5.4-mini` is a real cheaper tier on subscription sign-in | **High** | mid-2026 |
| Subscription is multi-tier (5 models), not single-model | **High** | mid-2026 |
| Cheaper model directly stretches the *same* subscription quota (per-model allowances) | **High** | mid-2026 |
| `gpt-5.5` is subscription-only / not API-key available | **Medium** (official docs say yes; one aggregator disputes) | mid-2026 |
| Exact 5h/weekly message numbers | **Medium** (OpenAI tunes by load) | mid-2026 |
| `gpt-5.5` Plus rate-cost spike (#28879) | **Medium** (possibly transient) | ~16 Jun 2026 |
| Metered API fallback prices | **High** | mid-2026 |

---

## Sources

- [Models – Codex | OpenAI Developers](https://developers.openai.com/codex/models)
- [Changelog – Codex | OpenAI Developers](https://developers.openai.com/codex/changelog)
- [Using Codex with your ChatGPT plan | OpenAI Help Center](https://help.openai.com/en/articles/11369540-using-codex-with-your-chatgpt-plan)
- [Codex rate card | OpenAI Help Center](https://help.openai.com/en/articles/20001106-codex-rate-card)
- [Codex CLI Model Routing in May 2026 (gpt-5.5 / 5.4 / Spark decision framework)](https://codex.danielvaughan.com/2026/05/07/codex-cli-model-routing-may-2026-gpt55-gpt54-spark-decision-framework/)
- [The Codex Subscription API: Programmatic Access to GPT-5.5 Through Your ChatGPT Plan](https://codex.danielvaughan.com/2026/04/24/codex-subscription-api-programmatic-access-gpt-5-5-chatgpt-plan/)
- [How to Use GPT-5.5 Today via Your Codex Subscription](https://www.jdhodges.com/blog/how-to-use-gpt-5-5-today-at-the-cli-via-your-existing-codex-subscription/)
- [OpenAI Pro $100 tier — 5X Codex usage vs Plus | VentureBeat](https://venturebeat.com/orchestration/openai-introduces-chatgpt-pro-usd100-tier-with-5x-usage-limits-for-codex)
- [Codex Usage Limits: 5-Hour Quota, Weekly Limits, Credits | knightli.com](https://knightli.com/en/2026/04/15/codex-usage-limits-five-hour-weekly-credits/)
- [Codex (gpt-5.5, Plus) rate-limit cost spike — Issue #28879](https://github.com/openai/codex/issues/28879)
- [GPT-5.4 Mini API Pricing 2026 | pricepertoken](https://pricepertoken.com/pricing-page/model/openai-gpt-5.4-mini)
- [OpenAI API Pricing 2026 | aipricing.guru](https://www.aipricing.guru/openai-pricing/)
- [Pricing | OpenAI API](https://developers.openai.com/api/docs/pricing)
