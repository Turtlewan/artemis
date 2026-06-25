# Idempotency & Deduplication in Event-Driven Dispatch

**Research date:** 2026-06-25
**Topic:** Validates a built design — a reaction dispatcher using a keyed SQLite ledger with atomic `INSERT OR IGNORE` (try_claim) for at-most-once firing of stateless rules, and a read-compare-then-write `state_hash` for stateful rules.
**Scope:** At-least/at-most/exactly-once semantics; dedup tables / inbox pattern; outbox/inbox; TOCTOU / atomic claim; stateful dedup; retry + DLQ interplay.
**Agent:** apex-research (Phase-2 RETRIEVAL — findings only, no recommendation)

---

## Tier Key

| Tag | Meaning |
|-----|---------|
| `[T1]` | Primary source / official docs / peer-reviewed |
| `[T2]` | High-quality practitioner post / well-cited reference implementation |
| `[T3]` | Derived / secondary / snippet-only |

---

## 1. Delivery Semantics: What Is Actually Achievable

### 1.1 The Three Semantics

**At-most-once:** A message is delivered zero or one times. Preferred where loss is acceptable and duplicate side effects are catastrophic. Achieved by not retrying on failure. No extra infrastructure required, but no durability guarantee. `[T2]` [ByteByteGo — At most once, at least once, exactly once](https://blog.bytebytego.com/p/at-most-once-at-least-once-exactly)

**At-least-once:** The message is guaranteed to be delivered but may be delivered more than once. Default posture of most brokers (Kafka, RabbitMQ, SQS). Requires idempotent consumers or explicit dedup to avoid double side-effects. `[T2]` [Estuary — What is Exactly-Once Delivery and Why It's So Hard to Achieve](https://estuary.dev/blog/exactly-once-delivery/)

**Exactly-once:** The message is processed precisely once. The most difficult semantic to achieve. Requires distributed coordination and is often not achievable across heterogeneous systems. `[T2]` [Estuary]: "you can't guarantee both consistency and availability if there's even one faulty node" (FLP theorem).

### 1.2 "Effectively-Once" via Idempotent Consumers

Current practice converges on a pragmatic middle ground: combine at-least-once delivery with idempotent processing logic. `[T2]` [Estuary]: "If your logic is idempotent, even at-least-once delivery becomes much safer to work with." This is sometimes called **effectively-once** — duplicates arrive but produce no additional effect.

`[T1]` [Temporal — What is idempotency?](https://temporal.io/blog/idempotency-and-durable-execution): "Idempotency does not give you exactly-once semantics — it gives you deterministic convergence under retries."

`[T2]` [Confluent — Exactly-once semantics in Kafka](https://www.confluent.io/blog/exactly-once-semantics-are-possible-heres-how-apache-kafka-does-it/): Kafka achieves exactly-once *within the Kafka cluster* via idempotent producers (sequence numbering) and transactional APIs (atomic multi-partition write + offset commit). Beyond the Kafka boundary, the responsibility shifts to the consumer.

`[T2]` [Extending Kafka EOS to External Systems](https://medium.com/@raviatadobe/extending-kafkas-exactly-once-semantics-to-external-systems-c395267935bd): "Kafka's EOS stops at the boundary of the Kafka cluster — beyond that, it's up to us to design for idempotency or consistency."

### 1.3 Single-Consumer vs Multi-Consumer Note

For **single-consumer / single sequential drain** (e.g., one SQLite-backed dispatcher running one goroutine/thread), the at-least-once / idempotency boundary is dramatically simpler: there is no concurrent consumer race. The dedup ledger must still guard against *retry* duplicate fires (e.g., a crash after an effect but before a commit), but row-level lock contention and cross-consumer races do not apply. This is the most common note across sources:

`[T2]` [arxiv 2512.16146](https://arxiv.org/pdf/2512.16146): "Single-consumer dedup is simpler, using local state or simple caches. Multi-consumer scenarios require shared state repositories (databases, caches) to track processed messages across instances, significantly increasing complexity."

---

## 2. Idempotency Keys, Dedup Tables, and the Inbox Pattern

### 2.1 Idempotency Key Design

An **idempotency key** is a client-generated or system-generated unique token per logical operation. The server records the key and the result of the first request; subsequent requests with the same key return the cached result without re-executing. `[T2]` [NxtBanking — Idempotency Keys in Payment API Design](https://nxtbanking.com/idempotency-keys-payment-api-design/)

**Composite key scoping.** `[T2]` [brandur.org — Implementing Stripe-like Idempotency Keys in Postgres](https://brandur.org/idempotency-keys): Keys should be scoped per `(user_id, idempotency_key)` — "it's possible to have the same idempotency key for different requests as long as it's across different user accounts." More generally: scope by `(source, environment, operation_type, logical_id)` to prevent false dedup across callers. `[T2]` [Hooklistener — Webhook Idempotency and Deduplication](https://www.hooklistener.com/learn/webhook-idempotency-and-deduplication): "Prefix the key with the source: `stripe:evt_1OxYzA...` rather than the bare ID. If you run multiple environments against shared infrastructure, scope by environment too."

**Parameter validation.** `[T2]` [brandur.org]: The idempotency layer compares incoming parameters to those of the original request and errors if they're not the same — this prevents accidental key reuse across different operations.

### 2.2 Dedup Table / Processed-Message Ledger

The **dedup table** (or "processed-message ledger") records message IDs that have been seen. On each inbound message:
1. Attempt to insert the ID with a unique constraint.
2. If insert succeeds → this consumer owns it, proceed.
3. If insert fails (constraint violation) → duplicate, discard.

The key requirement: **the insert and the business side-effect must be in the same transaction**, or the insert must succeed *before* the side-effect occurs. `[T2]` [theburningmonk.com — Inbox & Outbox patterns](https://theburningmonk.com/2026/05/inbox-outbox-patterns-for-reliable-event-processing/): "write the inbox item and business change in the same transaction" — if the inbox insert succeeds and the business change is committed separately, a crash between the two leaves the system in an inconsistent state.

Critical ordering hazard: `[T2]` [theburningmonk.com]: "If step 1 succeeds [inbox insert] and step 3 fails [business update], future retries will see the inbox item and skip processing, even though the business action never happened." — Writing the dedup record first without also committing the side-effect creates a **phantom claim**: the key is spent but the action never landed.

### 2.3 TTL and Dedup Window

Dedup tables grow indefinitely without a cleanup policy. Options: `[T2]` [Milan Jovanovic — Implementing the Inbox Pattern](https://www.milanjovanovic.tech/blog/implementing-the-inbox-pattern-for-reliable-message-consumption): "The inbox table grows indefinitely" — recommended approaches are deleting processed messages after a retention period, or time-partitioned tables where old partitions are dropped.

**TTL sizing.** `[T2]` [Hooklistener]: "A TTL of the retry window plus a safety margin (say, 7 days for Stripe, 72 hours for Shopify) bounds your storage while covering every automatic retry." `[T2]` [brandur.org]: Stripe itself prunes idempotency keys after ~24 hours — sized to the maximum retry window. Keys pruned before the retry window closes allow a replay to re-execute as if it were a new request.

**Note:** For a single-consumer sequential dispatcher with no external broker retries, the relevant window is the maximum time between a crash and a recovery drain — likely seconds to minutes, not hours.

### 2.4 Kafka's Built-In Dedup

`[T1]` [Confluent Kafka delivery semantics](https://docs.confluent.io/kafka/design/delivery-semantics.html): Kafka's idempotent producer assigns each message a Producer ID + sequence number. The broker deduplicates within a single producer session. Transactional writes extend this atomically across partitions. This is broker-internal dedup only; downstream consumers still need their own ledger.

`[T2]` [DevTechTools — Kafka Idempotency Patterns](https://devtechtools.org/en/blog/kafka-idempotency-deduplication-patterns-event-driven-architectures): Consumer-side patterns include: (a) unique constraint on message ID in a processing table, (b) Redis `SET NX` with TTL, (c) Flink/Spark stateful operators with in-memory dedup state and periodic checkpointing.

### 2.5 Temporal's Dedup Approach

`[T1]` [Temporal docs — Handling Messages](https://docs.temporal.io/handling-messages): "For Updates, Temporal handles this for you on the server, by deduplicating according to the Update ID." Update ID defaults to UUID; can be set manually. Server-side dedup is per workflow-run only — across `Continue-As-New` boundaries, dedup must be implemented in workflow code.

Signals have no server-side dedup: "use a custom idempotency key that you send as part of your own signal inputs."

`[T1]` [Temporal — idempotency-and-durable-execution](https://temporal.io/blog/idempotency-and-durable-execution): The pattern for Activity idempotency is `workflowRunId + '-' + activityId` as a constant key across retries, inserted into a unique-constrained `operations` table. Activities are retried at-least-once; the idempotency key + unique constraint together produce effectively-once effect.

---

## 3. The Outbox / Inbox Pattern

### 3.1 The Dual-Write Problem

Without the outbox pattern, emitting an event and persisting a database change are two separate writes. A crash between them creates inconsistency. `[T2]` [Confluent — Transactional Outbox Pattern](https://developer.confluent.io/courses/microservices/the-transactional-outbox-pattern/): "the outbox pattern ensures the delivery of a database change and the publishing of a message within a single atomic unit by strictly avoiding two-phase commits."

### 3.2 Outbox (Reliable Emit)

Write both business record and outbox event in a single DB transaction. A background relay process reads the outbox and publishes to the broker. The relay guarantees at-least-once delivery to the broker — it may publish the same event twice on crash/restart. `[T2]` [Conduktor — Outbox Pattern](https://www.conduktor.io/glossary/outbox-pattern-for-reliable-event-publishing): "the outbox pattern provides at-least-once delivery, network issues or reprocessing scenarios can cause duplicates. Consumers must handle duplicate event delivery gracefully."

Relay implementation variants: polling the outbox table, or CDC (e.g., Debezium) streaming table changes. `[T2]` [Extending Kafka EOS](https://medium.com/@raviatadobe/extending-kafkas-exactly-once-semantics-to-external-systems-c395267935bd)

### 3.3 Inbox (Reliable Consume + Dedup)

The consumer writes the incoming event ID into an inbox table before processing. The inbox item is the dedup token: `[T2]` [theburningmonk.com]: "The consumer stores the incoming event ID in an Inbox table, and the inbox item then acts as a deduplication key." The inbox insert uses `ON CONFLICT DO NOTHING` (or equivalent). Only one inbox insert will win under concurrent delivery of the same event.

`[T2]` [Milan Jovanovic]: Implementation uses `"ON CONFLICT (id) DO NOTHING"` on insertion. For concurrent processors, `"FOR UPDATE SKIP LOCKED"` allows horizontal scaling without contention between workers picking up different messages.

The inbox pattern alone guarantees at-most-once *processing* only if the inbox insert and business side-effect are atomic (same transaction). Otherwise it only guarantees dedup-on-consume with a window where both could fail. `[T2]` [event-driven.io — Outbox/Inbox explained](https://event-driven.io/en/outbox_inbox_patterns_and_delivery_guarantees_explained/)

### 3.4 Combined Outbox + Inbox = Strongest Guarantee

`[T2]` [Extending Kafka EOS]: "coupling the Idempotent Consumer with the Transactional Outbox (and CDC) provides the strongest guarantee that no duplicate processing will occur." Incoming duplicates are filtered (inbox); outgoing events are captured atomically with business logic (outbox); no duplicates cascade downstream.

**Single-consumer note:** The outbox/inbox combination is designed for distributed multi-service pipelines. For a single-process embedded dispatcher draining a local event queue, the outbox side is less applicable (there is no external broker publish step); the inbox-equivalent (the try_claim ledger) still applies for crash recovery.

---

## 4. TOCTOU / Race Conditions in Dedup

### 4.1 The Read-Compare-Then-Write Hazard

The naive pattern:
```
SELECT EXISTS(id FROM ledger WHERE key = ?)   -- check
if not exists:
    INSERT INTO ledger(key) VALUES (?)         -- claim
    execute_side_effect()
```

This is a **TOCTOU** (Time-of-Check-to-Time-of-Use) race. Two concurrent consumers can both pass the `SELECT` check before either commits the `INSERT`. Both then execute the side-effect. `[T2]` [Hooklistener]: "Two concurrent deliveries of the same event can BOTH reach this line, because neither saw the other's uncommitted insert."

### 4.2 Atomic Claim: INSERT OR IGNORE / ON CONFLICT DO NOTHING

The correct pattern eliminates the check-then-act gap:

```sql
INSERT OR IGNORE INTO ledger(key) VALUES (?);
-- returns rows_affected: 1 = claim won, 0 = duplicate
```

This is atomic: the database enforces the unique constraint as part of the insert. At most one concurrent writer wins. `[T2]` [Milan Jovanovic]: uses `ON CONFLICT (id) DO NOTHING` — this "is doing the heavy lifting" for idempotent consumption.

`[T2]` [brandur.org]: "A `UNIQUE` constraint in the database guarantees that only one request can succeed" when multiple requests attempt simultaneous operations.

### 4.3 SQLite-Specific Behavior

SQLite does not support `SELECT ... FOR UPDATE` (row-level locking). Its locking model is coarser: `[T3]` [SQLite Forum / search results]: SQLite's `BEGIN IMMEDIATE` grabs the write lock up front, preventing the second writer from starting work it would discard.

For a **single-writer** SQLite dispatcher (one thread/goroutine draining):
- `INSERT OR IGNORE` within a `BEGIN IMMEDIATE` transaction is fully atomic against *other connections*, and trivially safe for a single sequential drain with no concurrent consumers.
- The TOCTOU concern only applies if multiple connections (or threads with WAL mode) are racing. WAL mode allows concurrent readers but still serializes writers. A single dispatcher process with one write connection has no inter-process race.

`[T3]` [Delft Stack — SQLite INSERT OR IGNORE](https://www.delftstack.com/howto/sqlite/sqlite-insert-or-ignore/): "Using transactions with INSERT OR IGNORE not only improves performance but also ensures that your database operations are atomic."

**Multi-consumer note:** If the SQLite-backed dispatcher were ever scaled to multiple concurrent writer connections (e.g., multi-process), the TOCTOU hazard would reappear. The `INSERT OR IGNORE` pattern itself remains correct (unique constraint enforces exclusivity), but the losing writer must check `rows_affected` to know it lost the claim — it should not assume success.

### 4.4 PostgreSQL Equivalent

PostgreSQL uses `INSERT ... ON CONFLICT DO NOTHING` with a `RETURNING` clause. If `RETURNING` yields no rows, the key already existed. For recovery scenarios requiring the prior response, follow with `SELECT ... FOR UPDATE` to read the stored result. `[T2]` [brandur.org]

### 4.5 State-Machine Approach for In-Flight Keys

`[T2]` [brandur.org]: For long-running operations (multiple DB phases), the idempotency record tracks a state machine: `started → phase_1_complete → phase_2_complete → finished`. Each recovery point picks up where the last successful phase left off. This prevents partial re-execution without requiring the entire operation to be fully atomic.

---

## 5. Stateful / Windowed Dedup: Re-Fire-as-Update Semantics

### 5.1 The Problem

Pure key-based dedup (INSERT OR IGNORE on a message ID) only blocks exact replay of a previously-seen ID. It does not distinguish between:
- **True duplicate:** same event, same payload, same intended effect — should be blocked.
- **Re-fire with new state:** same logical entity/rule, but state has changed since the last fire — should be allowed and may need to update rather than skip.

This is the core challenge for **stateful rules** that re-evaluate when underlying data changes, vs stateless rules that execute once per event.

### 5.2 Content Hash / State Hash Pattern

The established pattern for "fire-on-change" rules:

```
last_hash = SELECT state_hash FROM ledger WHERE rule_id = ? AND entity_id = ?
current_hash = hash(current_input_state)
if current_hash == last_hash:
    skip  -- same state as last fire, true duplicate
else:
    execute_effect()
    UPDATE ledger SET state_hash = current_hash WHERE ...
```

`[T3]` [arxiv — Event Deduplication using multiple stages](https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/12210497): State structures based on digest hashes track the active set of events; false positives depend on hash collision probability based on digest size and table size.

`[T2]` [GitHub Baileys discussion](https://github.com/WhiskeySockets/Baileys/issues/2415): In production systems, "events frequently fire multiple times with different status values, with the same event experiencing status updates (e.g., offer → ringing → reject) that require deduplication to prevent duplicate system messages" — pure key dedup would block these legitimate state-change re-fires.

`[T2]` [Stateless vs Stateful Rule Engine — nected.ai](https://www.nected.ai/us/blog-us/stateless-vs-stateful-rule-engine): "Stateful engines rely on algorithms (like Rete) to constantly re-evaluate the rule graph every time a new fact enters working memory" — the stateful rule itself is fired by state change, not by event ID.

### 5.3 TOCTOU Concern in Read-Compare-Then-Write

The state hash pattern is a **read-compare-then-write** (RCTW):
1. Read `last_hash`
2. Compare with `current_hash`
3. Write new `state_hash` if changed

This is technically a TOCTOU hazard if multiple writers race on the same `(rule_id, entity_id)` key. The safer atomic form:

```sql
-- Optimistic concurrency:
UPDATE ledger SET state_hash = ?, fired_at = NOW()
WHERE rule_id = ? AND entity_id = ? AND state_hash = <old_hash>
-- rows_affected = 0 → someone else already updated → re-read and retry or skip
```

Or for a single sequential consumer, the RCTW is safe because no concurrent writer exists. `[T3]` [inferred from single-consumer note in §1.3 + general TOCTOU literature]

### 5.4 Windowed Dedup in Stream Processing

For stream processors (Spark, Flink, RisingWave), windowed dedup groups events within a time window and applies dedup logic within each window. `[T2]` [RisingWave — Effective Deduplication](https://risingwave.com/blog/effective-deduplication-of-events-in-batch-and-stream-processing/): "Window-based methods use time windows to group events and identify duplicates within each window. For example, a sliding window can capture events over a specific period."

Watermarking defines how late events are handled — events arriving after the watermark may be dropped or treated as new. `[T2]` [Spark stateful stream dedup](https://lilmonk.medium.com/spark-stateful-stream-deduplication-5252e040e98f): For IoT/sensor streams, state tracks the last-seen timestamp per key and discards events with timestamps ≤ the stored value.

**Applicability:** Windowed stream dedup is designed for high-throughput, distributed stream processors. For an embedded single-process dispatcher over a local SQLite ledger, the relevant pattern is the state hash RCTW above, not a time-window operator.

---

## 6. Retry, Backoff, Dead-Letter, and the Idempotency Interplay

### 6.1 Retry Is the Source of Most Duplicates

At-least-once delivery creates duplicates through two mechanisms:
- **Broker re-delivery:** The broker did not receive an acknowledgment and re-sent the message.
- **Consumer retry:** The consumer received, partially processed, failed, and retried.

Both produce a second delivery of the same message. If the consumer is idempotent, the second delivery has no additional effect.

### 6.2 Retry Strategy: Exponential Backoff + Jitter

`[T2]` [Background Jobs and Queues — digitalapplied.com](https://www.digitalapplied.com/blog/background-job-queue-patterns-2026-engineering-reference): "retry quickly for a short window, then back off, and eventually stop retrying automatically, using exponential backoff with jitter... backoff reduces pressure and jitter prevents synchronized retry storms. A common starting point is 5–8 attempts with backoff (for example: 5s, 15s, 45s, 2m, 5m, 10m, 30m) plus jitter, then send to DLQ."

The idempotency key must survive the full retry window — the dedup TTL must be at least as long as the maximum backoff horizon.

### 6.3 DLQ Replay and Double-Fire Risk

When a message is moved to a dead-letter queue and later replayed (manually or automatically), it re-enters the consumer as a fresh delivery. If the dedup key is still within its TTL window, the idempotency ledger will block the re-execution. If the TTL has expired, the message is processed as new.

`[T2]` [Hooklistener]: "manual replays occurring months later will bypass an expired key, necessitating additional safeguards beyond door-level deduplication" — specifically, idempotent side effects at the business logic level (e.g., upserts, conditional writes, check-then-act on domain state).

`[T2]` [Milan Jovanovic]: Failed messages in the inbox remain with error annotations. A "max retry count" threshold should trigger dead-lettering "to prevent infinite retry loops." Critically, a message that is dead-lettered after partial processing may leave the dedup record in a claimed-but-incomplete state. The system must distinguish:
- `status = PROCESSING` (claimed, in flight, may be retried)
- `status = DONE` (claimed, completed)
- `status = DEAD` (claimed, permanently failed)

### 6.4 Idempotency Key Must Propagate Downstream

`[T2]` [Hooklistener]: "If the webhook triggers a payment or an email through another API, forward your event ID as that API's idempotency key so the whole chain dedupes consistently." A dispatcher that fires a side-effect (e.g., sends a notification, mutates external state) must pass its own idempotency token to the downstream call, otherwise the downstream call may fire twice even if the dispatcher's dedup ledger fires only once.

### 6.5 Temporal's Activity Retry Model

`[T1]` [Temporal — idempotency-and-durable-execution](https://temporal.io/blog/idempotency-and-durable-execution): Activities retry at-least-once by default. Temporal marks an Activity as completed in its event history once it succeeds; on workflow replay, completed Activities are skipped without re-execution. The Activity may have partially executed multiple times before final success — the idempotency key (`workflowRunId + activityId`) prevents the external side-effect from applying twice.

For DLQ-equivalent in Temporal: Temporal has no built-in DLQ but supports `maximumAttempts` + timeout; beyond that the workflow must handle the failure explicitly.

---

## 7. Cross-Cutting Trade-Off Summary

| Pattern | SINGLE-consumer safe? | MULTI-consumer safe? | Guarantees | Trade-offs |
|---|---|---|---|---|
| `INSERT OR IGNORE` (atomic try_claim) | Yes — trivially | Yes — DB unique constraint serializes | At-most-once fire | Dedup table grows; TTL cleanup needed |
| SELECT-then-INSERT (naive check) | Yes (single thread) | **No** — TOCTOU race | Unsafe for concurrent consumers | Simple code; wrong under concurrency |
| `ON CONFLICT DO NOTHING` + same-txn side-effect | Yes | Yes | Effectively-once (dedup + atomicity) | Requires transactional DB; effect must be in same txn |
| State-hash RCTW | Yes (single sequential) | Risky — optimistic CAS needed | Fire-on-change re-fire semantics | Extra read per event; hash collision risk (negligible with SHA-2+) |
| Outbox + Inbox combined | Yes | Yes | Strongest end-to-end; no cascade duplication | Higher complexity; background relay process |
| Temporal workflow ID dedup | N/A (orchestration level) | Yes | Per-run exactly-once for workflow | Only within Temporal; not portable to arbitrary dispatchers |
| Windowed stream dedup (Flink/Spark state) | Yes (single partition) | Yes (partitioned by key) | Dedup within time window; late events dropped or re-processed | State store overhead; watermark configuration needed |

---

## 8. Sources

| # | Source | URL | Tier |
|---|--------|-----|------|
| 1 | ByteByteGo — At most once, at least once, exactly once | https://blog.bytebytego.com/p/at-most-once-at-least-once-exactly | T2 |
| 2 | Estuary — What is Exactly-Once Delivery | https://estuary.dev/blog/exactly-once-delivery/ | T2 |
| 3 | Confluent — Exactly-Once Semantics in Kafka | https://www.confluent.io/blog/exactly-once-semantics-are-possible-heres-how-apache-kafka-does-it/ | T2 |
| 4 | Confluent — Kafka Delivery Semantics (official docs) | https://docs.confluent.io/kafka/design/delivery-semantics.html | T1 |
| 5 | Temporal — What is Idempotency? | https://temporal.io/blog/idempotency-and-durable-execution | T1 |
| 6 | Temporal docs — Handling Messages (Update ID dedup) | https://docs.temporal.io/handling-messages | T1 |
| 7 | brandur.org — Implementing Stripe-like Idempotency Keys in Postgres | https://brandur.org/idempotency-keys | T2 |
| 8 | Stripe API Docs — Idempotent Requests | https://docs.stripe.com/api/idempotent_requests | T1 |
| 9 | Hooklistener — Webhook Idempotency and Deduplication | https://www.hooklistener.com/learn/webhook-idempotency-and-deduplication | T2 |
| 10 | Milan Jovanovic — Implementing the Inbox Pattern | https://www.milanjovanovic.tech/blog/implementing-the-inbox-pattern-for-reliable-message-consumption | T2 |
| 11 | theburningmonk — Inbox & Outbox patterns | https://theburningmonk.com/2026/05/inbox-outbox-patterns-for-reliable-event-processing/ | T2 |
| 12 | event-driven.io — Outbox/Inbox patterns explained | https://event-driven.io/en/outbox_inbox_patterns_and_delivery_guarantees_explained/ | T2 |
| 13 | Extending Kafka EOS to External Systems (Medium) | https://medium.com/@raviatadobe/extending-kafkas-exactly-once-semantics-to-external-systems-c395267935bd | T2 |
| 14 | Confluent — Transactional Outbox Pattern | https://developer.confluent.io/courses/microservices/the-transactional-outbox-pattern/ | T2 |
| 15 | arxiv 2512.16146 — Kafka Event-Streaming Design Patterns | https://arxiv.org/pdf/2512.16146 | T1 |
| 16 | arxiv — Event Deduplication using multiple stages | https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/12210497 | T1 |
| 17 | DevTechTools — Kafka Idempotency Deduplication Patterns | https://devtechtools.org/en/blog/kafka-idempotency-deduplication-patterns-event-driven-architectures | T2 |
| 18 | RisingWave — Effective Deduplication of Events | https://risingwave.com/blog/effective-deduplication-of-events-in-batch-and-stream-processing/ | T2 |
| 19 | Spark stateful stream deduplication (Medium) | https://lilmonk.medium.com/spark-stateful-stream-deduplication-5252e040e98f | T2 |
| 20 | GitHub Baileys — Event Deduplication Patterns discussion | https://github.com/WhiskeySockets/Baileys/issues/2415 | T3 |
| 21 | Nected.ai — Stateless vs Stateful Rule Engine | https://www.nected.ai/us/blog-us/stateless-vs-stateful-rule-engine | T2 |
| 22 | Background Jobs and Queues 2026 Reference | https://www.digitalapplied.com/blog/background-job-queue-patterns-2026-engineering-reference | T2 |
| 23 | Delft Stack — SQLite INSERT OR IGNORE | https://www.delftstack.com/howto/sqlite/sqlite-insert-or-ignore/ | T3 |
| 24 | NxtBanking — Idempotency Keys in Payment API Design | https://nxtbanking.com/idempotency-keys-payment-api-design/ | T2 |
| 25 | DEV.to — Inbox Pattern (actor-dev) | https://dev.to/actor-dev/inbox-pattern-51af | T3 |

---

*Research agent: apex-research Phase-2 RETRIEVAL. No recommendation is made; synthesis and design verdict are deferred to planning mode.*
