# Research: Event Payload Contract — what should a domain event carry?

**Date:** 2026-06-25
**Confidence:** MEDIUM (one Tier-1 primary fetched — CloudEvents spec; the canonical pattern sources — Fowler, EIP, microservices.io, Microsoft/AWS/Confluent docs — sit on WebFetch-denied domains and are cited from WebSearch snippets only)
**Re-research after:** 2027-06-25 (general architecture patterns — 1 year)

> **Context:** an event-driven reactions engine emits an `EMAIL_INGESTED` event consumed by multiple
> reaction handlers. The live decision: should the event carry **(A)** the derived/extracted DATA
> fields inline, or **(B)** only IDs + a reference, with handlers fetching the data themselves?
> This doc presents the option space + trade-offs with citations. **It does not recommend** — the
> decision is made downstream.

---

## Summary

Three canonical payload contracts map directly onto the A/B question: **Event Notification** (thin —
ID + "it happened", handlers fetch everything), **Event-Carried State Transfer / ECST** (fat — the
event carries the full derived state inline, option A), and **Claim-Check** (event carries a
*reference* to a stored payload, handlers retrieve on demand — a middle path that is option B done as
a deliberate pattern). The axes that separate them are: runtime coupling to the source, schema
coupling, data freshness, consumer autonomy, broker/payload cost, and — critical for this engine —
**how sensitive or untrusted-derived content is handled.** Two findings bear hardest on `EMAIL_INGESTED`:
(1) strong, repeated guidance to keep PII and untrusted/LLM-extracted content **out of fan-out event
payloads** (data minimization, "Forgettable Payload", crypto-shredding, OWASP LLM01 indirect-injection
fan-out propagation); and (2) a clear dedup-field convention — a per-event `id` whose `(source, id)`
pair is the dedup key, with `idempotency_key` as a distinct business-operation token.

---

## Key findings

### Pattern definitions (the A vs B option space)

- **Event Notification (thin):** event signals only that something happened — entity/event type + ID;
  consumers call back to the source for detail. Canonical Fowler example: `CustomerAddressChanged`
  carries the customer ID, not the new address. [COMMUNITY — Fowler GOTO 2017 notes:
  https://gist.github.com/xpepper/36beda855540b0c1dde6c4c417dafec9] [NEEDS-DOMAIN: martinfowler.com —
  https://martinfowler.com/articles/201701-event-driven.html — primary Fowler taxonomy]
- Thin events have **low schema coupling but high runtime coupling** — the consumer cannot function if
  the source is down. [COMMUNITY — codeopinion.com snippet:
  https://codeopinion.com/thin-vs-fat-integration-events/]
- Fan-out amplifies the callback cost: "when an event is consumed by nine consumers, that's nine
  incoming calls to the producer ... in quick succession"; catch-up requires rate-limiting that
  "slows down consumers considerably." [VERIFIED — Medium/Geek Culture, Oskar uit de Bos:
  https://medium.com/geekculture/the-event-notification-pattern-a62d48519107]

- **Event-Carried State Transfer / ECST (fat — option A):** the event carries the full derived state;
  consumers maintain a local replica and do not call back for routine operations. [COMMUNITY — Fowler
  notes (above); Max Zalota, Medium:
  https://medium.com/@max.zalota/event-carried-state-transfer-reference-architecture-26ef49186c44]
- ECST gives **high consumer autonomy / low runtime coupling** (works when source is down) but adds
  **schema coupling** (consumers parse the full entity; breaking schema changes hit all subscribers)
  and is **eventually consistent** (replicas can be stale). [COMMUNITY — Zalota (above); Deloitte
  Engineering snippet: https://deloitte-engineering.github.io/2021/the-event-carried-state-transfer-pattern/]
- ECST anti-pattern: "Exposing database entities directly as events couples consumers to your
  implementation" — fix is explicit public event schemas separate from internal models. [VERIFIED —
  oneuptime.com: https://oneuptime.com/blog/post/2026-01-30-event-schema-design/view]
- ECST-specific risks: out-of-order delivery corrupts replicas (needs sequence guards); poison-pill
  malformed-state events halt consumers; every subscriber stores its own copy. [COMMUNITY — Zalota / Deloitte (above)]

- **Claim-Check (reference — option B as a pattern):** producer stores the payload in an external
  store (blob/object/db), emits a lightweight event carrying only a reference "ticket"; consumers
  retrieve on demand. Luggage-check analogy is canonical. [COMMUNITY — David Mosyan, Medium:
  https://medium.com/@dmosyan/claim-check-design-pattern-603dc1f3796d; EIP "Store-in-Library"
  snippet] [NEEDS-DOMAIN: enterpriseintegrationpatterns.com —
  https://www.enterpriseintegrationpatterns.com/patterns/messaging/StoreInLibrary.html — primary EIP
  definition (Hohpe & Woolf)] [NEEDS-DOMAIN: learn.microsoft.com —
  https://learn.microsoft.com/en-us/azure/architecture/patterns/claim-check — Azure canonical, with size limits]

### Thin vs fat — versioning, coupling, cost

- **Adding optional fields is safe; renaming/removing/type-changing is a breaking change** that
  requires a new event version/identity. The more fields a fat event carries, the larger the
  breaking-change surface. [VERIFIED — theburningmonk.com (2025):
  https://theburningmonk.com/2025/04/event-versioning-strategies-for-event-driven-architectures/]
  [NEEDS-DOMAIN: codeopinion.com — https://codeopinion.com/event-versioning-guidelines/ — "must create a new version"]
- Recommended evolution rule: "Always add new fields, never remove/rename existing fields, and never
  change the data type." [VERIFIED — theburningmonk.com (above)]
- A new event version "must be convertible from the old version. If not, it is not a new version ...
  but rather a new event" — incompatible fat-event evolution forces all consumers onto a new type.
  [VERIFIED — valerii-udodov.com: https://valerii-udodov.com/posts/event-sourcing/events-versioning/]
- **Fan-out amplifies the blast radius:** backward compat in fan-out needs publishers emitting
  multiple versions simultaneously (risk: v1 succeeds, v2 fails, "not possible to roll back the v1
  event"), or separate topics ("topic sprawl"), or an out-of-band translation consumer. [VERIFIED —
  theburningmonk.com (above)]
- **Payload bloat is a real cost at frequency:** "Including full state ... can increase the payload
  size for each event, increasing costs and load on the system, especially for frequent events."
  [VERIFIED — oneuptime.com (above)]. Schema registries mitigate by passing a schema ID rather than
  the full schema per message. [VERIFIED — oneuptime/Confluent; NEEDS-DOMAIN: docs.confluent.io —
  https://docs.confluent.io/platform/current/schema-registry/index.html]
- **Semantic coupling persists even with fat events:** if a producer removes fields, consumers with
  logic built on those fields break. [VERIFIED — towardsdatascience.com:
  https://towardsdatascience.com/event-driven-architecture-and-semantic-coupling-7cd5c2f2fc99/]
- **Dual-write / derived-data consistency:** fat events carrying derived values risk publishing a
  stale derivation if the source changes between DB commit and event publish; canonical mitigation is
  the **Outbox Pattern** (atomic DB-write + event-emit). [ASSUMED — derived from general pattern]
  [NEEDS-DOMAIN: martinfowler.com — https://martinfowler.com/articles/patterns-of-distributed-systems/outbox.html;
  microservices.io — https://microservices.io/patterns/data/transactional-outbox.html]

### Sensitive / untrusted-derived content in payloads (highest relevance to `EMAIL_INGESTED`)

- **Hard rule: never put PII in topic/stream names**, and broadly avoid PII in event payloads unless
  strictly necessary. Use indirect references (IDs not names/contact info). [VERIFIED — event-driven.io:
  https://event-driven.io/en/gdpr_in_event_driven_architecture/; EventSourcingDB docs:
  https://docs.eventsourcingdb.io/best-practices/gdpr-compliance/]
- **Legal basis:** GDPR Art. 5(1)(c) + Art. 25 — data "limited to what is necessary," applied
  **per-consumer** (each downstream consumer is a separate processing purpose; you cannot push more
  fields than each consumer's purpose requires). [VERIFIED — sesamedisk.com:
  https://sesamedisk.com/operationalizing-gdpr-article-25/; legiscope snippet]
- **Immutable log vs right-to-erasure (Art. 17)** conflict — "law to be forgotten and immutable data
  sounds like fire and water." Two named mitigations:
  - **Forgettable Payload** — replace PII in the event with a URN/reference to a *mutable* external
    store; erase by deleting from the store; the log keeps only an opaque pointer. [VERIFIED — Mathias
    Verraes (2019): https://verraes.net/2019/05/eventsourcing-patterns-forgettable-payloads/;
    event-driven.io (above)] — **this is structurally the Claim-Check / option B.**
  - **Crypto-shredding** — encrypt PII with a per-entity key; on erasure destroy the key, leaving
    ciphertext that is indistinguishable from noise. Per-entity key isolation mandatory; keys live in
    an external KMS, never co-resident with data. EDPB-recognized. [VERIFIED — event-driven.io (above);
    Medium/brentrobinson5:
    https://medium.com/@brentrobinson5/crypto-shredding-how-it-can-solve-modern-data-retention-challenges-da874b01745b]
- **Data-temperature model:** only "hot" (transactional, decision-making) data belongs in write-model
  event streams; warm/cold (analytics, archive) does not. "Avoid treating the event store as a
  general-purpose datastore." [VERIFIED — event-driven.io; EventSourcingDB docs (above)]
- **Untrusted content + fan-out is a structural injection risk:** "Event-driven code increases exposure
  to injection ... at triggers such as message queues and cloud events." Defense = **schema validation
  at the producer** before the event touches the bus (a registry closes it at source rather than each
  consumer re-implementing checks). [COMMUNITY — bluepes.com:
  https://bluepes.com/blog/event-driven-architecture-security] OWASP treats all untrusted data as a
  potential attack payload. [NEEDS-DOMAIN: owasp.org — https://owasp.org/www-community/Injection_Theory]
- **SSRF via payload:** untrusted URLs carried in events and dereferenced asynchronously by consumers
  bypass perimeter controls; message queues create implicit cross-segment paths. [COMMUNITY — SSRF
  guide: https://medium.com/@okanyildiz1994/mastering-ssrf-vulnerabilities-an-ultra-extensive-guide-to-understanding-and-mitigating-43aa09a8df08]
- **AI/LLM-extracted content must not be fanned out before validation** — OWASP **LLM01:2025**
  (indirect prompt injection) is the #1 LLM risk three years running: "external content data may alter
  the behavior of the model in unintended ways." If AI-extracted content is placed in an event and
  fanned out before validation, **the injected instruction propagates to every subscriber.** Mitigation:
  label untrusted content explicitly (delimiters/quarantine) and gate it before promoting to trusted
  state. [COMMUNITY — OWASP LLM01 via indusface:
  https://www.indusface.com/learning/owasp-llm-prompt-injection/] [NEEDS-DOMAIN: genai.owasp.org —
  https://genai.owasp.org/llmrisk/llm01-prompt-injection/ — primary OWASP source]
- "If unsafe information is extracted through managed flows, developers have limited opportunity to
  inspect, reject, quarantine, or reroute candidate data before it becomes durable state." [COMMUNITY —
  Microsoft Foundry / techcommunity:
  https://techcommunity.microsoft.com/blog/azure-ai-foundry-blog/defending-your-memory-in-microsoft-foundry-agent-service-against-memory-poisonin/4529638]

### Claim-Check specifics — when the extra fetch is worth it

- **Use when:** payload exceeds broker size limits (Kafka default `message.max.bytes` = 1 MB; Azure
  Event Grid 1 MB; Service Bus standard 256 KB / premium 100 MB); payload is sensitive and needs ACLs
  stricter than the bus; not all consumers need the full payload (routing steps act on the ticket
  alone); different consumers need different slices; storage is cheaper than broker throughput; GDPR
  erasure (delete the blob → log pointer becomes harmless). [COMMUNITY — Mosyan; scalablethread:
  https://newsletter.scalablethread.com/p/what-is-the-claim-check-pattern-in] [NEEDS-DOMAIN:
  confluent.io — https://developer.confluent.io/patterns/event-processing/claim-check/]
- **What goes in the event:** reference ID/URI, integrity hint (hash/ETag), size, content-type,
  schema/version id, dedup token, small routing metadata. **Never** a long-lived pre-signed URL (leaks
  durable access into logs) — use short-TTL signed URLs generated at read time, or have consumers
  derive the URL from the key. [COMMUNITY — Rahul K, Medium:
  https://medium.com/@27.rahul.k/kafka-handling-large-messages-and-message-compaction-594fb8bd1279]
- **Write order:** upload to store first, get ETag, *then* produce the event — guarantees the
  reference is valid when consumed. [COMMUNITY — same source]
- **Trade-offs:** +1 store RTT per consuming fetch (~10–100 ms); store unavailability blocks all
  consumer processing; orphaned-blob risk if cleanup fails (mitigate with lifecycle expiry as a safety
  net); TTL must exceed max consumer lag + any replay window. Not ideal for ultra-low-latency
  pipelines. [COMMUNITY — Mosyan; scalablethread; Aslan:
  https://medium.com/@murataslan1/taming-large-payloads-in-microservices-the-claim-check-pattern-ab56f6cda638]
- **Reference implementations:** `irori-ab/claim-check-interceptors` (Kafka producer/consumer
  interceptors, Azure Blob backend, configurable byte threshold ~1 MB default) [COMMUNITY —
  https://github.com/irori-ab/claim-check-interceptors]; Azure SDK Service Bus `Sample10_ClaimCheck`
  (empty body + `blob-name` application property → BlobClient download) [VERIFIED —
  https://raw.githubusercontent.com/Azure/azure-sdk-for-net/main/sdk/servicebus/Azure.Messaging.ServiceBus/samples/Sample10_ClaimCheck.md].

### Idempotency / dedup field placement

- **CloudEvents (Tier-1, fetched):** `id` is REQUIRED, unique within producer scope; the **dedup key
  is the composite `(source, id)`** — "Consumers MAY assume that Events with identical `source` and
  `id` are duplicates"; a retried duplicate MAY reuse the same `id`. CloudEvents does **not** define
  `correlation_id` / `causation_id` / `idempotency_key` — those are **extension attributes**. [VERIFIED
  — https://raw.githubusercontent.com/cloudevents/spec/main/cloudevents/spec.md]
- **Field distinctions:** `event_id` identifies *this event instance*; `correlation_id` is shared
  across all events in one business transaction; `causation_id` = the `event_id` of the immediately
  preceding event; `idempotency_key` is a client-supplied token identifying a *logical business
  operation* (constant across retries). Key point: **`event_id` ≠ `idempotency_key`** — one identifies
  the record, the other the business intent. [COMMUNITY — Greg Young via Arkency:
  https://blog.arkency.com/correlation-id-and-causation-id-in-evented-systems/; RailsEventStore:
  https://railseventstore.org/docs/core-concepts/correlation-causation]
- **Placement convention:** HTTP layer → `Idempotency-Key` **header** (IETF draft, RECOMMENDED UUID).
  [VERIFIED — https://datatracker.ietf.org/doc/draft-ietf-httpapi-idempotency-key-header/] Event
  envelopes → a dedicated **`metadata` sub-object** structurally separate from the domain `data` body.
  [COMMUNITY — Arkency (above)] Kafka → header **or** payload, both valid; the requirement is that the
  producer sets it. [COMMUNITY — Conduktor: https://www.conduktor.io/blog/building-idempotent-consumers]
- **Producer vs consumer dedup (Kafka):** `enable.idempotence=true` only prevents *broker-level*
  duplicates from producer retries — "Consumer-side duplicates are your problem." Consumer dedup needs
  a stored-key check (client UUID, composite business key, or `topic-partition-offset` — the last
  requires no payload field but is fragile across rebalances). [COMMUNITY — Conduktor (above)]
- **Outbox interaction:** the outbox row `Id` is the dedup key for the relay worker and propagates to
  the broker message; the **Inbox** pattern is the consumer-side complement (record received message
  IDs before processing). Outbox guarantees at-least-once → consumer must still dedup on `event_id`.
  [COMMUNITY — event-driven.io:
  https://event-driven.io/en/outbox_inbox_patterns_and_delivery_guarantees_explained/; theburningmonk.com]
- **AWS:** EventBridge is at-least-once and does **not** dedup on its envelope `id`; the AWS-native
  mechanism is SQS FIFO `MessageDeduplicationId`, extracted from the event **payload `detail`**
  via JSONPath — i.e. AWS pushes the dedup key into the body. [VERIFIED via AWS CDK GitHub:
  https://github.com/aws/aws-cdk/issues/36498] [NEEDS-DOMAIN: docs.aws.amazon.com — EventBridge /
  SNS FIFO dedup docs]
- **Temporal:** Workflow ID is itself an idempotency key (duplicate ID rejected by server;
  `WorkflowIdReusePolicy` controls completed-workflow reuse). Pattern: use the event's `event_id` (or
  a payload-derived business key) as the `WorkflowId` → one event = one workflow execution; activity
  idempotency keys use `WorkflowRunId + ActivityId`. [COMMUNITY — Medium/Augereau:
  https://medium.com/@ps.augereau/idempotence-in-temporal-io-a-look-into-technical-architectures-11d20a0fc860]
  [NEEDS-DOMAIN: temporal.io — https://temporal.io/blog/idempotency-and-durable-execution]

---

## Options comparison

| Axis | (A) ECST — fat / inline data | Claim-Check — reference (deliberate B) | Event Notification — thin / ID-only (basic B) |
|------|------------------------------|----------------------------------------|-----------------------------------------------|
| Payload size | Full entity state | Tiny (reference + hints) | Minimal (ID + type) |
| Source/store calls at consume | None | Yes — to store (not source) | Yes — to source (required) |
| Runtime coupling | Low (to source) | Medium (to store) | High (to source) |
| Schema coupling | High (full entity contract) | Low–Medium (key/ref format) | Low |
| Data freshness | Eventually consistent | Current at fetch (store TTL) | Current at fetch |
| Consumer autonomy | High (local replica) | Medium | Low |
| Broker size pressure | High | None | None |
| Sensitive/PII handling | Worst — PII fans out to all subscribers; erasure hard | Best — payload behind store ACLs; erasure = delete blob (Forgettable Payload) | Good — no data in event, but every consumer must call source |
| Untrusted/LLM-derived content | Worst — injected content propagates to every handler | Good — content stays in store, gated/validated before retrieval | Good — content not in event |
| Versioning blast radius (fan-out) | Largest (every field is a contract surface) | Small (event = thin ref) | Smallest |
| Extra latency | None | +1 store RTT per fetch | +1 source RTT per fetch |
| Best for | Resilience / autonomous local joins; non-sensitive small payloads | Large or **sensitive/untrusted** payloads; subset-consuming handlers; GDPR erasure | Frequently-changing data where staleness is harmful; simplest contract |

**Hybrid worth noting:** events commonly carry a **thin trusted envelope inline** (IDs, type,
timestamps, dedup `id`, small non-sensitive routing hints / classification flags) **plus a reference**
to sensitive/untrusted derived content held in a store — i.e. notification-style for safe metadata,
claim-check for the risky body. Multiple sources converge on this split (Forgettable Payload +
data-temperature + "explicit public event schema separate from internal model").

---

## Assumptions / gaps

- **Primary canonical sources not directly fetched** (WebFetch domain wall): Fowler "Many Meanings of
  Event-Driven Architecture", EIP Claim-Check/Store-in-Library (Hohpe & Woolf), microservices.io
  Outbox, Microsoft Azure Architecture Center Claim-Check, Confluent pattern pages, OWASP LLM01 primary,
  AWS EventBridge/SNS dedup docs, Temporal idempotency post. All cited from WebSearch snippets +
  allowed-domain mirrors. See the NEEDS-DOMAIN registry below — authorize these domains to upgrade the
  affected claims from [COMMUNITY] to [VERIFIED].
- **One Tier-1 primary was fetched** — the CloudEvents spec (raw.githubusercontent.com) — grounding the
  `(source, id)` dedup-key finding at [VERIFIED].
- **The dual-write / derived-data staleness point is [ASSUMED]** (general-pattern inference); the
  Outbox primary sources were not fetchable.
- No source was found giving a quantitative threshold for "when fat-event payload bloat actually costs
  money" beyond "frequent events" — that is workload-specific and needs hands-on measurement for
  `EMAIL_INGESTED` volume.

---

## NEEDS-DOMAIN registry (authorize to upgrade [COMMUNITY] → [VERIFIED])

| Host | URL | Why |
|------|-----|-----|
| martinfowler.com | https://martinfowler.com/articles/201701-event-driven.html | Primary Notification + ECST taxonomy |
| martinfowler.com | https://martinfowler.com/articles/patterns-of-distributed-systems/outbox.html | Canonical dual-write / Outbox |
| microservices.io | https://microservices.io/patterns/data/transactional-outbox.html | Canonical Outbox |
| enterpriseintegrationpatterns.com | https://www.enterpriseintegrationpatterns.com/patterns/messaging/StoreInLibrary.html | Primary Claim-Check (Hohpe & Woolf) |
| learn.microsoft.com | https://learn.microsoft.com/en-us/azure/architecture/patterns/claim-check | Azure Claim-Check + size limits |
| confluent.io | https://developer.confluent.io/patterns/event-processing/claim-check/ | Confluent Kafka Claim-Check |
| docs.confluent.io | https://docs.confluent.io/platform/current/schema-registry/index.html | Schema registry payload optimization |
| genai.owasp.org | https://genai.owasp.org/llmrisk/llm01-prompt-injection/ | OWASP LLM01:2025 primary |
| owasp.org | https://owasp.org/www-community/Injection_Theory | Untrusted-data-is-attack principle |
| codeopinion.com | https://codeopinion.com/event-versioning-guidelines/ | Event versioning / double-publish |
| verraes.net | https://verraes.net/2019/05/eventsourcing-patterns-forgettable-payloads/ | Forgettable Payload primary |
| docs.aws.amazon.com | https://docs.aws.amazon.com/sns/latest/dg/SNSMessageDeduplication.html | SNS/EventBridge FIFO dedup |
| temporal.io | https://temporal.io/blog/idempotency-and-durable-execution | Temporal idempotency primary |
| cloudevents.io | https://cloudevents.io | CloudEvents extension catalogue (correlation/causation) |

---

## Sources (fetched / snippet-confirmed)

- CloudEvents spec — https://raw.githubusercontent.com/cloudevents/spec/main/cloudevents/spec.md **[Tier 1, fetched]**
- Azure SDK Service Bus claim-check sample — https://raw.githubusercontent.com/Azure/azure-sdk-for-net/main/sdk/servicebus/Azure.Messaging.ServiceBus/samples/Sample10_ClaimCheck.md **[fetched]**
- Fowler GOTO 2017 notes — https://gist.github.com/xpepper/36beda855540b0c1dde6c4c417dafec9
- ECST reference architecture (Zalota) — https://medium.com/@max.zalota/event-carried-state-transfer-reference-architecture-26ef49186c44
- Event Notification pattern (uit de Bos) — https://medium.com/geekculture/the-event-notification-pattern-a62d48519107
- Thin vs fat integration events — https://codeopinion.com/thin-vs-fat-integration-events/
- Event versioning strategies — https://theburningmonk.com/2025/04/event-versioning-strategies-for-event-driven-architectures/
- Events versioning (Udodov) — https://valerii-udodov.com/posts/event-sourcing/events-versioning/
- Event schema design — https://oneuptime.com/blog/post/2026-01-30-event-schema-design/view
- EDA & semantic coupling — https://towardsdatascience.com/event-driven-architecture-and-semantic-coupling-7cd5c2f2fc99/
- GDPR in event-driven architecture — https://event-driven.io/en/gdpr_in_event_driven_architecture/
- Forgettable Payloads (Verraes) — https://verraes.net/2019/05/eventsourcing-patterns-forgettable-payloads/
- Crypto-shredding (Robinson) — https://medium.com/@brentrobinson5/crypto-shredding-how-it-can-solve-modern-data-retention-challenges-da874b01745b
- EventSourcingDB GDPR best practices — https://docs.eventsourcingdb.io/best-practices/gdpr-compliance/
- GDPR Article 25 operationalization — https://sesamedisk.com/operationalizing-gdpr-article-25/
- EDA security — https://bluepes.com/blog/event-driven-architecture-security
- OWASP LLM01 analysis — https://www.indusface.com/learning/owasp-llm-prompt-injection/
- Microsoft Foundry memory-poisoning defense — https://techcommunity.microsoft.com/blog/azure-ai-foundry-blog/defending-your-memory-in-microsoft-foundry-agent-service-against-memory-poisonin/4529638
- Claim-check design pattern (Mosyan) — https://medium.com/@dmosyan/claim-check-design-pattern-603dc1f3796d
- Claim-check large payloads (Aslan) — https://medium.com/@murataslan1/taming-large-payloads-in-microservices-the-claim-check-pattern-ab56f6cda638
- What is the claim-check pattern (scalablethread) — https://newsletter.scalablethread.com/p/what-is-the-claim-check-pattern-in
- Kafka large messages (Rahul K) — https://medium.com/@27.rahul.k/kafka-handling-large-messages-and-message-compaction-594fb8bd1279
- irori-ab/claim-check-interceptors — https://github.com/irori-ab/claim-check-interceptors
- Correlation/causation in evented systems (Arkency) — https://blog.arkency.com/correlation-id-and-causation-id-in-evented-systems/
- RailsEventStore correlation/causation — https://railseventstore.org/docs/core-concepts/correlation-causation
- Idempotency-Key HTTP header (IETF) — https://datatracker.ietf.org/doc/draft-ietf-httpapi-idempotency-key-header/
- Building idempotent consumers (Conduktor) — https://www.conduktor.io/blog/building-idempotent-consumers
- Outbox/Inbox & delivery guarantees — https://event-driven.io/en/outbox_inbox_patterns_and_delivery_guarantees_explained/
- AWS CDK EventBridge → SQS FIFO dedup — https://github.com/aws/aws-cdk/issues/36498
- Idempotence in Temporal.io (Augereau) — https://medium.com/@ps.augereau/idempotence-in-temporal-io-a-look-into-technical-architectures-11d20a0fc860
