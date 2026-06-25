# Research: Safely Bringing Automation Live — Observe-First Go-Live Patterns

**Date:** 2026-06-25
**Agent:** apex-research (Phase-2 Retrieval)
**Topic:** Shadow mode / dry-run / observe-before-act patterns; canary graduation; audit logging; HITL graduation; dry-run pitfalls
**Confidence key:** [HIGH] = multiple corroborating sources | [MED] = single credible source | [LOW] = snippet-only or inferred

---

## Executive Orientation

This document surveys five bodies of practice relevant to a reactions engine that logs "WOULD do X" in `observe` mode before flipping to `live`. The research covers: (1) shadow/dry-run patterns as used in IaC, ML, and AI agent deployment; (2) canary / progressive rollout of side-effecting automation; (3) what to audit-log during break-in; (4) human-in-the-loop graduation (always-ask → auto-with-notice → silent-auto); (5) known failure modes of dry-run that cause observed-vs-live divergence.

---

## Section 1: Shadow Mode / Dry-Run / "What-If" / Plan-vs-Apply Patterns

### 1.1 Core Pattern Definition

Shadow mode runs the new system on production inputs without executing side effects. The canonical description: the agent "sees real work, produces real outputs, and touches none of the live controls."
[AgentForge Hub, HIGH] https://www.agentforgehub.com/posts/shadow-mode-for-ai-agents

The pattern spans infrastructure and application layers:

| Tool | Mechanism | What is suppressed |
|------|-----------|-------------------|
| Terraform | `plan` | All remote write operations |
| Kubernetes | `--dry-run=client` | API server mutations |
| Ansible | `--check` | Host state changes |
| Adobe Journey Optimizer | Journey Dry Run | Channel actions (email/SMS/push), custom actions, wait activities |
| AI Agent shadow mode | Parallel execution, blocked writes | All ITSM mutations, any state change |

[HashiCorp Developer — terraform plan, HIGH] https://developer.hashicorp.com/terraform/cli/commands/plan
[Adobe Journey Optimizer Dry Run docs, HIGH] https://experienceleague.adobe.com/en/docs/journey-optimizer/using/orchestrate-journeys/create-journey/journey-dry-run
[danieljamesglover.com — Why every script needs a dry-run flag, HIGH] https://danieljamesglover.com/blog/2026-02-01-dry-run-engineering-practice/

### 1.2 Terraform plan / apply: The Canonical Plan-Before-Apply Model

Terraform popularised the plan-before-apply two-phase model. `terraform plan` reads current remote state and proposes a diff; `terraform apply` executes it. There is no `--dry-run` flag on `apply` — `plan` is the dry run. [HIGH]

**What plan can't simulate:**
- External changes that occur between plan and apply — the plan is a point-in-time snapshot. The docs warn explicitly: "other changes made to the target system in the meantime might cause the final effect of a configuration change to be different than what an earlier speculative plan indicated."
- Targeting drift: using `-target` to apply subsets is "not recommended for routine operations, since this can lead to undetected configuration drift."
- Refresh-disabled runs: `-refresh=false` trades speed for correctness, potentially producing an incomplete plan.

[HashiCorp Developer — terraform plan, HIGH] https://developer.hashicorp.com/terraform/cli/commands/plan
[Spacelift — Terraform Dry Run Explained, MED] https://spacelift.io/blog/terraform-dry-run

### 1.3 Shadow Mode in AI/ML Systems

For ML model deployment, shadow mode duplicates production requests to the candidate model while the live model continues to serve responses. Candidate responses are discarded; only logging occurs.

**Architecture components:**
- Request duplication at the application layer or API gateway
- Separate resource pools and concurrency caps to protect the primary path
- Consistent feature computation ensuring both models receive identical feature versions
- Structured logging: `request_id, timestamp, model_version, prediction, confidence, latency, feature_completeness, user_segment`

**Required isolation:** "Always suppress write side effects in the shadow environment before enabling mirrored traffic. Shadow testing only works safely if the shadow service has no write side effects that reach production."
[QA Decoded — Shadow Testing, HIGH] https://www.qadecoded.com/topics/shadow-testing
[DYCORA — Deployment and Shadow Mode Testing, HIGH] https://www.dycora.com/deployment-and-shadow-mode-testing-validating-a-new-model-on-live-traffic-without-user-impact/

### 1.4 Shadow Mode Specifically for AI Agents (ITSM / Service Desk Context, 2025–2026)

The current pattern for agentic systems: the agent performs full reasoning and decision-making, but "system writes are blocked at the API level — this is 'true shadow' rather than a suggestion-only feature."

**Per-decision logging required:**
- Input data
- Retrieved context
- Proposed action + confidence signals
- Baseline (human / existing automation) action
- Reviewer verdict

"If you cannot inspect a shadow disagreement in under two minutes, your rollout process is under-instrumented."
[AgentForge Hub, HIGH] https://www.agentforgehub.com/posts/shadow-mode-for-ai-agents
[ITSM Autopilot — Shadow mode AI rollout, HIGH] https://www.itsmautopilot.com/en/blog/shadow-mode-ai-rollout

### 1.5 Dark Launching (Traffic Mirroring) at Infrastructure Level

Dark launching is the infrastructure-level equivalent: an API gateway or service mesh (e.g. Istio) mirrors 100% of incoming requests to the shadow service at the network level rather than the application layer. "A copy of real user traffic is sent to the dark-released service without exposing responses to users."

**The no-side-effects principle:** shadow service must use "separate data stores, sandboxed environments, or read-only access to databases, preventing the shadow version from modifying any state that could affect the live service."

Netflix uses this pattern to test new microservices under production traffic before public release.
[Medium — Dark Releases in DevOps, MED] https://medium.com/@ismailkovvuru/dark-releases-in-devops-the-hidden-power-move-for-safer-smarter-deployments-584aa94561f3
[Gravitee — Traffic Shadowing & Dark Launch in API Gateways, MED] https://www.gravitee.io/blog/implementing-traffic-shadowing-dark-launch-api-gateway

### 1.6 The "Would-Do" Logging Pattern (Neal Lathia)

A well-documented ML deployment practice: the system executes fully but "return[s] a default value _as if_ they were off." Logs capture what decisions the system would have made. This enables answering "what if this system had been on?" against production data without acting on results. Graduation happens when "precision and recall values for the classifiers based on the live data from production" meet confidence thresholds — "confidently turn them on, or know that we needed to do more work."
[Neal Lathia — Shadow mode deployments, HIGH] https://nlathia.github.io/2020/07/Shadow-mode-deployments.html

### 1.7 Adobe Journey Optimizer: Production-Grade Dry Run Design

AJO's Journey Dry Run is notable because it runs against real production profile data while suppressing external outputs. Key design choices:

- `stepEvents` tagged with `inDryRun=true` + `dryRunID` — distinguishes would-do from did-do in the same event stream
- Channel actions (email, SMS, push) suppressed; routing and branch logic runs normally
- Wait activities and external data sources disabled by default (configurable)
- Reporting accessible only while Dry Run is active (14-day maximum duration)
- Business rules not triggered during dry run — important divergence from live

[Adobe Journey Optimizer Dry Run docs, HIGH] https://experienceleague.adobe.com/en/docs/journey-optimizer/using/orchestrate-journeys/create-journey/journey-dry-run

---

## Section 2: Canary / Progressive Rollout / Feature-Flagging of Side-Effecting Automation

### 2.1 The Canary Pattern

A canary release introduces new behavior to a small subset of traffic or users before full rollout. For side-effecting automation, the canary period validates that the automation produces correct real-world effects before expanding scope.

**Standard graduation stages:**
1. 0% — deploy code/config, flag off (dark deployment)
2. Internal teams only (email domain targeting)
3. Beta / trusted users
4. 1–5% traffic
5. 25% → 50%
6. 100%

With hold periods between each stage for metric validation.
[ConfigCat — Canary Release with Feature Flags, HIGH] https://configcat.com/blog/how-to-implement-a-canary-release-with-feature-flags/
[Harness — Canary Releases and Feature Flags Explained, HIGH] https://www.harness.io/blog/canary-release-feature-flags

### 2.2 Feature Flags as the Decoupling Mechanism

"A deploy moves code to production; a release exposes a behavior to users — flags decouple the two."

This is the core mechanism for observe → partial → full progression:
- Flag `OFF` → code present, no behavior (dark)
- Flag `OBSERVE` (or shadow mode toggle) → behavior runs, outputs logged, no external actions
- Flag `LIVE` + targeting rules → real actions taken for targeted population
- Flag fully `ON` → full rollout

Feature flags also serve as instant kill switches: "Feature flags act as a kill switch, letting you disable the feature instantly without redeploying."
[LaunchDarkly — What are Feature Flags?, HIGH] https://launchdarkly.com/blog/what-are-feature-flags/
[Unleash — Canary release vs kill switches, HIGH] https://www.getunleash.io/blog/canary-release-vs-kill-switch

### 2.3 Kill Switches

A kill switch is "an immediate mechanism to disable or revert a feature or entire application version when critical issues are detected." Unlike a canary rollback (which reroutes traffic), a kill switch disables the behavior in-place without redeployment.

**Automation for kill switches:** "If any guardrail exceeds the threshold for five minutes, an automated action flips the kill switch and scales down the new service; after a stable hour, the ramp proceeds to the next percentage."
[Unleash — Canary release vs kill switches, HIGH] https://www.getunleash.io/blog/canary-release-vs-kill-switch
[DigitalApplied — Feature Flag Rollout Strategies 2026, MED] https://www.digitalapplied.com/blog/feature-flag-rollout-strategies-2026-engineering-playbook

### 2.4 Observe → Partial → Full: Side-Effect-Specific Considerations

For side-effecting automation, the standard canary approach requires additional safety gates:

**Exclusion targeting alongside percentage-based rollout:** protect "high-value customers, sensitive markets, or users who rely heavily on stability" from early automation phases.

**Automation-specific metrics to gate on:**
- False positive action rate (taking incorrect action): target < 2%
- Action accuracy by category (not global average): one bad category at 60% is hidden in a 95% average
- Escalation rate (actions the automation correctly deferred to humans)

**Post-rollout shadow maintenance:** "run shadow mode where the agent processes a percentage of decisions (1% of routine decisions) in parallel with humans, providing ongoing validation that the agent hasn't drifted."
[ITSM Autopilot — Shadow mode AI rollout, HIGH] https://www.itsmautopilot.com/en/blog/shadow-mode-ai-rollout
[Brightlume AI — Shadow Mode Rollouts for AI Agents, HIGH] https://brightlume.ai/blog/shadow-mode-rollouts-ai-agents-pilot-production

---

## Section 3: Audit / Observability During a Break-In Period

### 3.1 What to Log So a Human Can Trust the Automation

**Minimum per-decision log record:**
- `request_id` / decision ID
- Timestamp (microsecond precision)
- Input data / trigger context
- Retrieved context used for reasoning (provenance)
- Proposed action + confidence signal
- Baseline action (what a human or prior system would/did do)
- Reviewer verdict (if human reviewed)
- Outcome once executed (for post-hoc would-do vs did-do)

"Every agent action — every enrichment, every prioritization, every correlation — needs to be logged with full provenance: what data was used, which model reasoned, what confidence threshold triggered the action."
[Security Audit Logging for AI Agents — Dev Journal, MED] https://devjournal0.wordpress.com/2026/05/24/security-audit-logging-for-ai-agents-making-what-your-agent-did-provable/
[ITSM Autopilot — Shadow mode AI rollout, HIGH] https://www.itsmautopilot.com/en/blog/shadow-mode-ai-rollout

### 3.2 Tagging Would-Do vs Did-Do in the Same Event Stream

Adobe Journey Optimizer's pattern is instructive: tag events with `inDryRun=true` and a `dryRunID` field so observe-mode events flow into the same observability pipeline as live events but are distinguishable. This enables:
- Side-by-side comparison without a separate data store
- Replay analysis ("if this had been live, how many actions would have fired?")
- Drift detection (would-do distribution shifting post-rollout)

[Adobe Journey Optimizer Dry Run docs, HIGH] https://experienceleague.adobe.com/en/docs/journey-optimizer/using/orchestrate-journeys/create-journey/journey-dry-run

### 3.3 Agent Identity and Auditability

"Your agent needs a distinct identity (separate API keys, service accounts, audit log entries). Every action must be traceable to the agent, not to a human user."
[ITSM Autopilot — Shadow mode AI rollout, HIGH] https://www.itsmautopilot.com/en/blog/shadow-mode-ai-rollout

Additional governance:
- Time-bound credentials (hours, not days) to limit blast radius if compromised
- Explicit tool registry approval per external system
- Log what happened, not the data involved: "capture resource IDs, action types, and outcomes, but never PII"

[Brightlume AI — Shadow Mode Rollouts for AI Agents, HIGH] https://brightlume.ai/blog/shadow-mode-rollouts-ai-agents-pilot-production

### 3.4 Immutability and Centralization

For break-in period logs used as evidence of trustworthiness:
- Write-Once, Read-Many (WORM) storage to prevent modification after write
- Forward logs immediately to a centralized secure log server
- Hashing and digital signatures for tamper-evident trails
- Retention: 90 days decision logs; 7-year audit summaries (ITSM/regulated context)

[HubiFi — Immutable Audit Trails, MED] https://www.hubifi.com/blog/immutable-audit-log-basics
[Brightlume AI — Shadow Mode Rollouts for AI Agents, HIGH] https://brightlume.ai/blog/shadow-mode-rollouts-ai-agents-pilot-production

### 3.5 Readiness Gates: When to Flip to Live

Common multi-criteria gate structure (do NOT use global averages alone):

| Metric | Typical threshold | Notes |
|--------|------------------|-------|
| Agreement / accuracy rate | ≥ 85% overall, but validated per category | A 95% average with one bad category at 60% hides a risk source |
| False positive action rate | < 2% | |
| Critical errors in last N decisions | Zero | Typically last 500 decisions |
| Confidence score correlation | ≥ 0.70 | Confidence must predict correctness |
| Sample size | 5,000–10,000 decisions minimum | Before declaring readiness |
| Stakeholder sign-off | Required | Three-party: operational lead, IT leadership, compliance |

[Brightlume AI — Shadow Mode Rollouts for AI Agents, HIGH] https://brightlume.ai/blog/shadow-mode-rollouts-ai-agents-pilot-production
[ITSM Autopilot — Shadow mode AI rollout, HIGH] https://www.itsmautopilot.com/en/blog/shadow-mode-ai-rollout

---

## Section 4: Human-in-the-Loop Graduation (Always-Ask → Auto-with-Notice → Silent-Auto)

### 4.1 Three Canonical Oversight Models

The Redis / HITL literature (April 2026) defines three architectural models:

| Model | Human role | Execution model | When appropriate |
|-------|-----------|-----------------|-----------------|
| **HITL** (Human-in-the-loop) | Makes the decision; AI recommends | Synchronous interrupt-and-resume; pauses until human acts | High-risk, irreversible actions |
| **HOTL** (Human-on-the-loop) | Monitors and retains veto power | Asynchronous; AI acts, human can override | Lower-risk supervised tasks |
| **HOOTL** (Human-out-of-the-loop) | Sets boundaries at design time | Fully autonomous within pre-defined scope | Most production AI teams avoid this for high-risk tasks |

"Training can reduce the rate of inference-time failures, but it can't eliminate them."
[Redis — AI Human in the Loop: Production Oversight Patterns, HIGH] https://redis.io/blog/ai-human-in-the-loop/

### 4.2 The Graduation Progression

The standard HITL → HOTL → HOOTL graduation:

1. **Observe (shadow):** agent runs, logs would-do, takes no action. Pure audit.
2. **Suggest (HITL):** agent proposes action; human approves each one (single-click approval). "100% for high-stakes."
3. **Auto with notice (HOTL):** agent acts; human receives notification and can override within a window.
4. **Sampled review (HOTL):** agent acts; a percentage of decisions are sampled for retrospective human review (e.g. 10%).
5. **Silent auto (HOOTL):** agent acts autonomously within pre-defined scope; anomaly detection triggers human review.

"Most enterprise organizations should start with HITL and graduate to HOTL as they build confidence, data quality, and monitoring infrastructure."
[Synvestable — Human-in-the-Loop AI: Enterprise Oversight Design Patterns, MED] https://www.synvestable.com/human-in-the-loop.html
[Elementum AI — Human-in-the-Loop Agentic AI, MED] https://www.elementum.ai/blog/human-in-the-loop-agentic-ai

### 4.3 Confidence-Based Routing (Not a Simple Threshold)

The Redis article (2026) warns: "model confidence scores are an unreliable signal on their own. A model can produce a high confidence score on an incorrect prediction." Production architectures should use two distinct signals:
- **Trust score:** aggregate of multiple signals into a single reliability indicator
- **Risk score:** flags specific problem categories regardless of overall confidence

Routing decisions:
- High confidence + low risk → auto-execute (HOTL or HOOTL)
- Medium confidence or medium risk → quick human verification
- Low confidence or high risk or novel pattern → full human review (HITL)

"High Confidence (>95%): The system might auto-process the item, simply notifying the human."
[Redis — AI Human in the Loop: Production Oversight Patterns, HIGH] https://redis.io/blog/ai-human-in-the-loop/
[Mindee — Human-in-the-Loop in document automation, MED] https://www.mindee.com/blog/what-is-human-in-the-loop-automation

### 4.4 Synchronous Pause-Resume for HITL

HITL requires durable state persistence: "the checkpoint (the serialized snapshot of the agent's working memory, conversation history, tool results, and intermediate artifacts) is the collaboration surface and the pause mechanism."

Without durable state: "there's no reliable pausing point and no state for a human to inspect or modify."

This is the infrastructure gap most implementations underestimate: human review windows are open-ended; standard request-response models aren't designed for this.
[Redis — AI Human in the Loop: Production Oversight Patterns, HIGH] https://redis.io/blog/ai-human-in-the-loop/

### 4.5 Regulatory Direction

The EU AI Act (Article 12) requires automatic logging built into high-risk AI systems at design time; Article 26 requires deployers to retain those logs. NIST AI RMF names HITL as a common risk management strategy.

"Human oversight is moving from best practice to compliance requirement."
[Redis — AI Human in the Loop: Production Oversight Patterns, HIGH] https://redis.io/blog/ai-human-in-the-loop/

---

## Section 5: Pitfalls of Dry-Run / Observe Mode — Divergence from Live Behavior

### 5.1 The Phantom State Paradox (Multi-Step Agent Failure)

The most critical divergence pitfall for agentic systems: "when mocking writes at Level 3 [state-isolated sandbox], if an agent tries to read an ID of a record it just 'created,' the read fails because the data doesn't exist, causing the agent to crash. You cannot just mock writes for multi-step agents; you need an ephemeral shadow database state (like a branched Postgres instance) that lives only for the duration of that shadow request."

**Implication:** a reactions engine that runs multi-step rule chains (e.g. create a sub-reaction, then check its existence) cannot safely use simple write-suppression for observe mode. Each observe-mode run needs either: (a) an ephemeral in-memory state store for that evaluation run, or (b) a real database branch.
[DEV Community — 7 Levels of AI Shadow Modes, HIGH] https://dev.to/kowshik_jallipalli_a7e0a5/the-7-levels-of-ai-shadow-modes-and-why-staging-is-a-comfortable-lie-543p

### 5.2 Sandbox vs. Production Behavioral Divergence

Research on AI agent evaluation: "A meaningful fraction of candidates that appear acceptable in sandbox evaluation exhibit regression or policy-sensitive divergence in shadow mode, differing from the active version in governance-relevant ways such as higher retry frequency under real observation timing and more aggressive action proposals near policy boundaries."

"Sandbox evaluation is effective at detecting policy-sensitive drift and timeout stalls but entirely misses retry instability."

Different testing layers catch different failures — sandbox and shadow are complementary, not substitutes.
[DEV Community — 7 Levels of AI Shadow Modes, HIGH] https://dev.to/kowshik_jallipalli_a7e0a5/the-7-levels-of-ai-shadow-modes-and-why-staging-is-a-comfortable-lie-543p

### 5.3 Data Drift and Feature Degradation

ML-specific but broadly applicable: the observed-mode distribution of inputs will diverge from the live distribution over time due to:
- **Data drift:** production inputs diverge from distributions seen during observe-mode testing
- **Feature degradation:** real-time data pipelines exhibit delays, nulls, or inconsistencies not present in shadow testing
- **Latency mismatches:** accuracy in observe mode doesn't guarantee meeting live SLAs under real load
- **Edge case frequency:** rare values appear far more often in live production than in shadow sample

[DYCORA — Shadow Mode Testing, HIGH] https://www.dycora.com/deployment-and-shadow-mode-testing-validating-a-new-model-on-live-traffic-without-user-impact/

### 5.4 Training-Production Gap ("Benchmark Inflation")

AI agents often score 10–20 percentage points lower on real customer/staff/process data than on generic benchmark datasets. "This gap is the most common source of shadow-to-live disappointment."
[ITSM Autopilot — Shadow mode AI rollout, HIGH] https://www.itsmautopilot.com/en/blog/shadow-mode-ai-rollout

### 5.5 Terraform plan/apply: Point-in-Time Staleness

The plan-to-apply window is a known divergence source: another process can mutate infrastructure state after `plan` runs but before `apply` executes. The docs say to "always re-check the final non-speculative plan before applying." This is the IaC version of observe-mode staleness: the observed state is a snapshot, not a live mirror.
[HashiCorp Developer — terraform plan, HIGH] https://developer.hashicorp.com/terraform/cli/commands/plan

### 5.6 Adobe Journey Optimizer: Explicit Dry-Run Suppressions That Create Divergence

AJO's dry run explicitly creates known divergences from live:
- Business rules not triggered (e.g. frequency capping, suppression lists)
- Custom action responses set to null (downstream logic that depends on API responses will behave differently)
- Jump-to-journey actions not executed (cross-journey trigger chains missing)

These are by design — the lesson is that any observe mode must explicitly document which side effects are suppressed, because logic that depends on those effects will produce different branch results than live.
[Adobe Journey Optimizer Dry Run docs, HIGH] https://experienceleague.adobe.com/en/docs/journey-optimizer/using/orchestrate-journeys/create-journey/journey-dry-run

### 5.7 The "Permanent Purgatory" Anti-Pattern

Observed failure mode in enterprise shadow deployments: indefinite shadow mode that "becomes permanent purgatory" — teams lose confidence in results due to:
- No human actively reviewing logs
- Relying on aggregate metrics instead of examining individual disagreements
- No defined exit criteria established before starting

"Shadow mode without active reviewers is indistinguishable from shadow mode that has been forgotten."
[AgentForge Hub, HIGH] https://www.agentforgehub.com/posts/shadow-mode-for-ai-agents

### 5.8 Cost Explosion from Full Traffic Mirroring (Token Bankruptcy)

For LLM-based agents, mirroring 100% of traffic to a shadow agent doubles inference costs. The mitigation: "intelligent sampling using a cheap classifier model at ingress to mirror only edge-case intents."
[DEV Community — 7 Levels of AI Shadow Modes, HIGH] https://dev.to/kowshik_jallipalli_a7e0a5/the-7-levels-of-ai-shadow-modes-and-why-staging-is-a-comfortable-lie-543p

### 5.9 The Sycophantic Judge Pitfall

When using LLM-as-judge to compare observe-mode vs live outputs: LLM judges harbor verbosity bias, potentially promoting degraded models with longer responses as "better." Mitigation: "mix deterministic assertions with LLM evaluation for promotion decisions."
[DEV Community — 7 Levels of AI Shadow Modes, HIGH] https://dev.to/kowshik_jallipalli_a7e0a5/the-7-levels-of-ai-shadow-modes-and-why-staging-is-a-comfortable-lie-543p

---

## Section 6: Cross-Cutting Patterns and Trade-Off Summary

### 6.1 Dry-Run Design Principle: Inverted Safety Default

"Make dry-run the default for destructive scripts, requiring explicit `--execute` flags to make changes. This inverts the safety model — accidents require extra effort."

Applied to a reactions engine: the engine's mode flag default should be `observe`; switching to `live` requires explicit configuration, not the other way round.
[danieljamesglover.com — Why every script needs a dry-run flag, HIGH] https://danieljamesglover.com/blog/2026-02-01-dry-run-engineering-practice/

### 6.2 Implementation Forcing Function: Logging Forces Observability

"Implementing dry-run forces you to think about what your script actually does, improving logging quality and observability. The descriptions written for preview mode become production audit trails."

The observe-mode log schema becomes the permanent audit schema — design it for the live phase, not just the break-in period.
[danieljamesglover.com — Why every script needs a dry-run flag, HIGH] https://danieljamesglover.com/blog/2026-02-01-dry-run-engineering-practice/

### 6.3 Comparative Pattern Trade-Offs

| Pattern | Fidelity to live | Cost | Side-effect safety | Best for |
|---------|-----------------|------|--------------------|----------|
| Simple write-suppression | Medium (phantom state risk for multi-step) | Low | High if single-step only | Single-step, stateless rules |
| Ephemeral DB branch | High | Medium | High | Multi-step stateful rules |
| Network-level dark launch | Very high (full production path) | High (doubles infra cost) | Requires careful isolation | Complex distributed systems |
| Feature flag (OBSERVE tier) | High (same code path) | Low | High if flag gates all writes | Rules engines with flag support |
| Canary (1% live) | Exact | Production cost × 1% | None (real actions taken) | After observe phase, for final validation |

### 6.4 Observed-vs-Live Divergence Sources: Checklist

- [ ] Multi-step state dependencies (phantom state paradox)
- [ ] External API responses assumed non-null in observe mode
- [ ] Business rules / frequency caps not applied in observe mode
- [ ] Cross-entity trigger chains not followed in observe mode
- [ ] Point-in-time staleness (observe-mode state captured before live flip)
- [ ] Load-dependent behavior (latency, retry, queue depth differences under full traffic)
- [ ] Data drift (input distribution shifts between observe period and live period)
- [ ] Sampling bias (observe mode samples may not represent tail/edge cases)

---

## Sources Cited

| # | Title | URL | Tier |
|---|-------|-----|------|
| 1 | AgentForge Hub — Shadow Mode for AI Agents | https://www.agentforgehub.com/posts/shadow-mode-for-ai-agents | HIGH |
| 2 | Brightlume AI — Shadow Mode Rollouts for AI Agents | https://brightlume.ai/blog/shadow-mode-rollouts-ai-agents-pilot-production | HIGH |
| 3 | ITSM Autopilot — Shadow mode AI rollout | https://www.itsmautopilot.com/en/blog/shadow-mode-ai-rollout | HIGH |
| 4 | Neal Lathia — Shadow mode deployments | https://nlathia.github.io/2020/07/Shadow-mode-deployments.html | HIGH |
| 5 | DEV Community — 7 Levels of AI Shadow Modes | https://dev.to/kowshik_jallipalli_a7e0a5/the-7-levels-of-ai-shadow-modes-and-why-staging-is-a-comfortable-lie-543p | HIGH |
| 6 | HashiCorp Developer — terraform plan | https://developer.hashicorp.com/terraform/cli/commands/plan | HIGH |
| 7 | Spacelift — Terraform Dry Run Explained | https://spacelift.io/blog/terraform-dry-run | MED |
| 8 | DYCORA — Shadow Mode Testing | https://www.dycora.com/deployment-and-shadow-mode-testing-validating-a-new-model-on-live-traffic-without-user-impact/ | HIGH |
| 9 | QA Decoded — Shadow Testing | https://www.qadecoded.com/topics/shadow-testing | HIGH |
| 10 | danieljamesglover.com — Why every script needs a dry-run flag | https://danieljamesglover.com/blog/2026-02-01-dry-run-engineering-practice/ | HIGH |
| 11 | Adobe Journey Optimizer — Journey Dry Run | https://experienceleague.adobe.com/en/docs/journey-optimizer/using/orchestrate-journeys/create-journey/journey-dry-run | HIGH |
| 12 | ConfigCat — Canary Release with Feature Flags | https://configcat.com/blog/how-to-implement-a-canary-release-with-feature-flags/ | HIGH |
| 13 | Harness — Canary Releases and Feature Flags | https://www.harness.io/blog/canary-release-feature-flags | HIGH |
| 14 | Unleash — Canary release vs kill switches | https://www.getunleash.io/blog/canary-release-vs-kill-switch | HIGH |
| 15 | LaunchDarkly — What are Feature Flags? | https://launchdarkly.com/blog/what-are-feature-flags/ | HIGH |
| 16 | DigitalApplied — Feature Flag Rollout Strategies 2026 | https://www.digitalapplied.com/blog/feature-flag-rollout-strategies-2026-engineering-playbook | MED |
| 17 | Redis — AI Human in the Loop: Production Oversight Patterns | https://redis.io/blog/ai-human-in-the-loop/ | HIGH |
| 18 | Synvestable — HITL Enterprise Oversight Design Patterns | https://www.synvestable.com/human-in-the-loop.html | MED |
| 19 | Elementum AI — Human-in-the-Loop Agentic AI | https://www.elementum.ai/blog/human-in-the-loop-agentic-ai | MED |
| 20 | Mindee — HITL in document automation | https://www.mindee.com/blog/what-is-human-in-the-loop-automation | MED |
| 21 | Medium — Dark Releases in DevOps | https://medium.com/@ismailkovvuru/dark-releases-in-devops-the-hidden-power-move-for-safer-smarter-deployments-584aa94561f3 | MED |
| 22 | Gravitee — Traffic Shadowing & Dark Launch in API Gateways | https://www.gravitee.io/blog/implementing-traffic-shadowing-dark-launch-api-gateway | MED |
| 23 | Security Audit Logging for AI Agents — Dev Journal | https://devjournal0.wordpress.com/2026/05/24/security-audit-logging-for-ai-agents-making-what-your-agent-did-provable/ | MED |
| 24 | HubiFi — Immutable Audit Trails | https://www.hubifi.com/blog/immutable-audit-log-basics | MED |
| 25 | VentureBeat — Shadow mode, drift alerts and audit logs (429 — snippet only) | https://venturebeat.com/orchestration/shadow-mode-drift-alerts-and-audit-logs-inside-the-modern-audit-loop | NEEDS-DOMAIN: venturebeat.com — paywalled — snippet used |

---

_Research completed 2026-06-25. Agent: apex-research. Cite-or-drop policy applied. No final recommendation made._
