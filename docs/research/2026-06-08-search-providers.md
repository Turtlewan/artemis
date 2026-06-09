# Web Search APIs for Artemis Deep-Research Engine — 2026 Landscape

_Research date: 2026-06-08_

## Context & evaluation frame

Artemis is a privacy-conscious, locally-hosted personal assistant. The deep-research engine
sends **non-sensitive** queries (derived from the assistant's own knowledge gaps) to a search
provider to obtain candidate result URLs, then fetches + reads those pages locally under a
quarantined LLM. We need a **DEFAULT** provider + a **FALLBACK**, behind a swappable port
(adapter interface). Single-box deployment (one Mac Mini).

Because the fetch/read step is already local + quarantined, the search provider's job is narrow:
**return relevant, fresh candidate URLs (plus optional snippets) cheaply, over a simple REST call,
without logging/training on our queries.** Providers that *also* return clean page content in one
call are a bonus (they can collapse the fetch step for the cheap mode), but content extraction is
not the primary selection axis — local fetch already covers it.

---

## Provider-by-provider assessment

### 1. Brave Search API  ⭐ (recommended DEFAULT)

| Axis | Assessment |
|---|---|
| **Quality/fit** | Independent proprietary index (~35B pages — not reselling Google/Bing). Keyword/web search with snippets; strong freshness; returns title + URL + description snippet (not full clean content by default, though an "Answers" endpoint adds AI synthesis). Good general-purpose agentic relevance. |
| **Privacy** | **Best-in-class.** Only major search API offering true **Zero Data Retention (ZDR)**. Does **not** train its LLMs on queries. Queries retained max 90 days for billing/troubleshooting only (ZDR plans waive even that). Brave's position: query data is not personal data under GDPR. Independent of Big Tech. Jurisdiction: US-incorporated, privacy-first posture. |
| **Pricing (2026)** | **Free tier was removed early 2026.** New users now get **$5/month in credits** (~1,000 queries) then metered billing on a saved card. Search plan **$5 / 1,000 queries** (~$0.003–0.005/query depending on endpoint). 50 req/s default. Answers plan $4/1K + token fees. |
| **Integration** | Simple REST + API key header. Clean JSON. Widely supported, well-documented. Low effort. |
| **Self-host** | No. |

Caveat: the loss of the standing free tier means even light use bills a card past ~1K queries/mo.
For Artemis's expected low personal query volume this is a few dollars/month at most.

### 2. Tavily  ⭐ (recommended FALLBACK / agentic upgrade)

| Axis | Assessment |
|---|---|
| **Quality/fit** | **Purpose-built for LLM/agent research.** Returns LLM-ready cleaned snippets/content, optional direct "answer," relevance-scored results. `search` + `extract` endpoints — **combines search + content extraction**. Basic vs advanced depth. Strong agentic-research fit out of the box. |
| **Privacy** | **Zero data retention** (zero-day retention of search terms), **SOC 2 Type II**, built-in prompt-injection / data-leakage AI security layer. GDPR objection path. Jurisdiction: US; **acquired by Nebius Group (Feb 2026, $275M)** — data policies & ZDR commitments stated unchanged post-acquisition (monitor this). |
| **Pricing (2026)** | **1,000 free credits/month, no credit card.** Basic search = 1 credit, advanced = 2 credits. Extract = 1 credit / 5 successful URLs (basic). PAYG **$0.008/credit** (~$0.005 at volume). Paid tiers from $30/mo (4,000 credits). |
| **Integration** | Very simple REST; official Python/JS SDKs; first-class LangChain/agent integrations. Lowest-friction agentic shape of the set. |
| **Self-host** | No. |

### 3. Exa (formerly Metaphor)

| Axis | Assessment |
|---|---|
| **Quality/fit** | **Neural / embeddings-first semantic search** — best when queries are conceptual/"find me pages like this" rather than keyword. `auto` blends neural + keyword. Search-with-contents bundles text + highlights for top 10 results (**search + content in one call**). Deep / deep-reasoning tiers add query expansion. Excellent for semantic discovery; weaker for simple navigational/keyword lookups. |
| **Privacy** | US; standard SaaS posture. Not marketed as ZDR; less privacy-forward than Brave/Tavily. Acceptable given non-sensitive queries. |
| **Pricing (2026)** | 1,000 free requests/mo. Search+contents **$7 / 1,000** (10 results, contents bundled free). +$1/1K extra results. Contents endpoint $1/1K pages. Deep $12/1K, deep-reasoning $15/1K. |
| **Integration** | Clean REST + official SDKs; MCP server available. Low effort. |
| **Self-host** | No. |

Strong candidate for a *semantic* research mode upgrade, but pricier per query than Brave and less
of a drop-in keyword default.

### 4. Jina (s.jina.ai + Reader)

| Axis | Assessment |
|---|---|
| **Quality/fit** | `s.jina.ai/?q=` returns top ~5 results **with clean LLM-friendly content already extracted** (best single-call search+content of the set). `r.jina.ai` Reader extracts any URL to clean markdown — directly useful for Artemis's **fetch step** regardless of which search provider is chosen. Result depth shallow (top 5). |
| **Privacy** | **Elastic acquired Jina (Oct 2025).** Reader/OSS models still available; expect tighter Elasticsearch integration over 12 months. Privacy posture not ZDR-marketed. |
| **Pricing (2026)** | Token-based. 10M free tokens per new key. Free: 100 RPM / 100K TPM / 2 concurrent. Paid from ~$20/mo for more tokens + QPS. |
| **Integration** | **Trivially simple** — it's a URL prefix, no SDK needed. Excellent for the local fetch/extract step. |
| **Self-host** | Reader is open-source (self-hostable extraction), but the search side relies on upstream engines. |

**Most relevant to the fetch step**, see "search+content in one call" note below.

### 5. SearXNG (self-hosted metasearch)

| Axis | Assessment |
|---|---|
| **Quality/fit** | Aggregates 70+ upstream engines (Google, Bing, Brave, Mojeek, Qwant, Wikipedia, etc.). JSON API (`?format=json`) off by default — enable in `settings.yml`. Returns links + snippets, **no clean full content** (you fetch locally anyway — fine for Artemis). Quality depends on enabled upstreams. |
| **Privacy** | **Maximum — you own the box.** No third party sees queries; no logging/training by design. This is the privacy ceiling. |
| **Pricing** | Free software. Cost = your hardware + ops. |
| **Integration** | REST/JSON once enabled; no official SDK but trivial. |
| **Self-host** | **Yes — the point of it.** On a single Mac Mini: lightweight (it proxies, doesn't crawl; ~512MB RAM sufficient). **BUT** requires Redis/Valkey for the limiter, and the real operational tax is **upstream rate-limiting / bot-detection**: a single home IP hitting Google/Bing through SearXNG gets throttled or banned within a few queries/minute unless you spread load across many upstreams and accept flakiness. Maintenance burden: upstream engines break their scrapers periodically → silent quality degradation requiring babysitting. |

### 6. Google Programmable Search / Custom Search JSON API

| Axis | Assessment |
|---|---|
| **Status** | **DEPRECATED.** No new signups as of 2026; **full shutdown Jan 1, 2027.** Google steers to Vertex AI Search (full GCP setup, enterprise pricing). **Disqualified for a new build.** |
| **Pricing** | 100 free queries/day; $5/1K thereafter; hard cap 10K/day. Moot given deprecation. |

### 7. Bing Web Search API

| Axis | Assessment |
|---|---|
| **Status** | **RETIRED — endpoints return HTTP 410 Gone since Aug 11, 2025.** New resource creation disabled Feb 2025. Replacement is "Grounding with Bing Search" inside Azure AI Agents — no raw SERP JSON, requires full Azure Agents framework, 40–483% more expensive. **Disqualified.** |

### 8. Perplexity (Sonar API)

| Axis | Assessment |
|---|---|
| **Quality/fit** | Returns **cited answers** (LLM-synthesized) with live web search, not a clean candidate-URL list. This is the *opposite* shape from what Artemis wants — Artemis does its own reading under a quarantined LLM; paying Perplexity to also synthesize is redundant cost and cedes reasoning to a 3rd party. Citations give URLs but the model is answer-first. |
| **Privacy** | Configurable retention only on Enterprise Max; standard tiers less controllable. US. |
| **Pricing (2026)** | Sonar $1/1M in+out tokens; Sonar Pro $3 in / $15 out per 1M; **plus $5–$14 per 1,000 requests**. Per-query cost higher and less predictable than Brave/Tavily. |
| **Integration** | OpenAI-compatible chat shape. |
| **Self-host** | No. |

Poor fit: answer-engine, not a search/URL provider. Skip for this role.

### 9. You.com API

| Axis | Assessment |
|---|---|
| **Quality/fit** | Search + Contents + Research APIs. Search returns unified web+news structured results (LLM-optimized). Contents API fetches URLs → HTML/Markdown (**search + extraction available, separate calls**). Research API does multi-search synthesis (#1 on DeepSearchQA, per their marketing). Solid agentic fit. |
| **Privacy** | US; standard SaaS, not ZDR-marketed. |
| **Pricing (2026)** | Search **$5/1,000** (eff. Mar 2026); Contents $1/1,000 pages. **$100 complimentary credits** for new accounts (generous onboarding). |
| **Integration** | REST, `llms.txt` docs. Low effort. |
| **Self-host** | No. |

Comparable to Brave on price/shape but weaker privacy story; a reasonable secondary fallback.

### 10. Kagi Search API

| Axis | Assessment |
|---|---|
| **Quality/fit** | High-quality, ad-free, privacy-respecting results. Search API + FastGPT (LLM answers) + Enrichment APIs (Teclis web / TinyGem news indexes). Premium relevance. |
| **Privacy** | **Excellent** — Kagi's whole brand is privacy / no-tracking / no-ad. Strong cultural fit with Artemis. |
| **Pricing (2026)** | **Expensive: $15–$25 / 1,000 queries** for Search API (no published flat free tier; some endpoints in private beta). Enrichment API cheaper at $2/1K. |
| **Integration** | Simple REST + key. Some endpoints beta/limited availability. |
| **Self-host** | No. |

Best privacy ethos after self-hosting, but 3–5× Brave's price and patchy availability. A
premium/values-aligned alternative, not the cost-effective default.

### Strong 2026 entrant noted: Linkup

| Axis | Assessment |
|---|---|
| **Quality/fit** | LLM/agent-optimized; **#1 on OpenAI SimpleQA factuality**. Standard (fast facts) + Deep (chain-of-thought) modes; source-grounded answers. |
| **Privacy** | **EU-based, GDPR-from-day-one** — notable jurisdiction differentiator. |
| **Pricing (2026)** | €5/1,000 standard (€0.005/search), €50/1,000 deep. Free: 1,000 standard + 100 deep/mo. |
| **Integration** | REST/SDK, marketed as a Bing-API replacement. |
| **Self-host** | No. |

Credible Brave/Tavily competitor; EU jurisdiction may matter if that's preferred over US providers.

---

## Recommendations

### (1) DEFAULT (cheap/standard mode): **Brave Search API**
- Independent index (not reselling Google/Bing — resilient + genuinely different results).
- **True Zero Data Retention + no training on queries** — the strongest privacy guarantee of any
  hosted option, aligning with Artemis's privacy-conscious design even though queries are non-sensitive.
- Cheapest credible per-query price ($5/1K ≈ $0.003–0.005). Dead-simple REST. Returns the
  exact shape Artemis needs: relevant candidate URLs + snippets, leaving reading to the local
  quarantined LLM.
- Trade-off: the free tier is gone (2026) — light use bills a card past ~1K queries/mo, but that's
  cents-to-a-few-dollars at personal scale.

### (2) FALLBACK / upgrade: **Tavily**
- **1,000 free credits/month, no credit card** — a genuine zero-cost fallback that covers most
  personal volume outright.
- Zero data retention + SOC 2 Type II + built-in prompt-injection defense (a real plus given
  Artemis fetches untrusted pages).
- **search + extract in one provider** lets the fallback path optionally collapse search+fetch for
  the cheap mode. Best agentic ergonomics + SDKs of the set.
- Watch item: Nebius acquisition (Feb 2026) — re-verify ZDR commitments periodically.

Both sit cleanly behind one swappable port: `search(query) -> [{title, url, snippet}]`, with Tavily
optionally exposing `extract(url) -> content`.

(Exa is the right **semantic** upgrade if a future mode needs concept-similarity discovery rather
than keyword search. Kagi/Linkup are values-aligned premium alternatives — Linkup if EU jurisdiction
is preferred.)

### (3) Self-hosted SearXNG — worth it on a single box?
**Not as the default; keep it as an optional privacy-maximalist backend.** It gives the absolute
privacy ceiling (nothing leaves your machine to a search vendor), and it's lightweight to run on a
Mac Mini. **But** on a single home IP the upstream engines (Google/Bing/etc.) rate-limit and
bot-flag SearXNG aggressively — you get a few queries/minute before throttling/bans, requiring
Redis/Valkey + many spread-out upstreams + ongoing babysitting as upstream scrapers break.
For a low-volume personal assistant where the queries are explicitly **non-sensitive**, the
operational tax and flaky reliability outweigh the marginal privacy gain over Brave's ZDR. Verdict:
**support it behind the port for users who want it, but don't make it the default.**

### (4) Provider(s) that combine search + content-extraction in one call
Relevant because Artemis has a separate local fetch step that this could collapse for the cheap mode:
- **Jina `s.jina.ai`** — returns top-5 results *with* clean LLM-ready content already extracted;
  trivial URL-prefix integration. Best single-call search+content. (And `r.jina.ai` Reader is a
  strong standalone extractor for the fetch step regardless of search choice.)
- **Tavily** — `search` returns cleaned snippets/content + optional answer; `extract` endpoint for
  full page content. One vendor, agent-friendly.
- **Exa** — search-with-contents bundles text + highlights for the top 10 results free.
- **You.com** — Search + separate Contents API (HTML/Markdown).

For Artemis, keep search and fetch as **separate ports** (the local quarantined fetch is a security
boundary worth preserving), but Tavily's combined shape is a convenient fallback, and Jina Reader is
worth adopting for the local extraction step itself.

---

## Sources

- Brave: https://brave.com/blog/search-api-zero-data-retention/ ; https://brave.com/search/api/ ; https://api-dashboard.search.brave.com/documentation/pricing ; https://www.implicator.ai/brave-drops-free-search-api-tier-puts-all-developers-on-metered-billing/ ; https://brave.com/learn/best-search-api-2026/
- Tavily: https://docs.tavily.com/documentation/api-credits ; https://www.tavily.com/privacy ; https://trust.tavily.com/ ; https://nolist.ai/item/tavily (Nebius acquisition)
- Exa: https://exa.ai/pricing ; https://docs.exa.ai/reference/search ; https://www.morphllm.com/exa-search-api
- Jina: https://jina.ai/reader/ ; https://www.xpay.sh/saas-pricing/jina-reader/ ; https://serp.fast/tools/jina-ai (Elastic acquisition)
- SearXNG: https://docs.searxng.org/admin/searx.limiter.html ; https://searxng.org/ ; https://stackharbor.com/en/knowledge-base/searxng-llm-grounding-deploy/
- Google CSE: https://developers.google.com/custom-search/v1/overview ; https://blog.expertrec.com/google-custom-search-json-api-simplified/
- Bing retirement: https://learn.microsoft.com/en-us/lifecycle/announcements/bing-search-api-retirement ; https://ppc.land/microsoft-ends-bing-search-apis-on-august-11-alternative-costs-40-483-more/
- Perplexity: https://docs.perplexity.ai/docs/getting-started/pricing ; https://www.cloudzero.com/blog/perplexity-api-pricing/
- You.com: https://you.com/docs/search/overview ; https://you.com/pricing
- Kagi: https://help.kagi.com/kagi/api/overview.html ; https://costbench.com/software/ai-search-apis/kagi-search-api/ ; https://help.kagi.com/kagi/api/enrich.html
- Linkup: https://www.linkup.so/blog/what-s-the-best-alternative-to-the-bing-search-api ; https://awesomeagents.ai/pricing/search-api-pricing/
- Roundups: https://www.marktechpost.com/2026/05/04/top-search-and-fetch-apis-for-building-ai-agents-in-2026/ ; https://www.firecrawl.dev/blog/best-web-search-apis
