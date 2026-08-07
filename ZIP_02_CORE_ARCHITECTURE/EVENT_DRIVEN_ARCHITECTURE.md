# Event Driven Architecture

Event-driven architecture is ADR-001 (`ZIP_01/DECISION_LOG.md`).

This document holds the **canonical event catalog**. Where any other document
disagrees with the catalog below, this document wins and the other document
is to be corrected.

---

## 1. Event Bus

**Decision: Redis Streams is the canonical event bus. Kafka is not part of
the MVP.**

This supersedes the earlier "Redis Streams or Kafka" wording in
`SERVICE_COMMUNICATION.md`, `KAFKA.md` and `ZIP_10/KAFKA.md`.

Migration to Kafka is triggered only when one or more of the following
becomes true:

1. More than 100,000 deal events per day.
2. Multiple independent consumers require long-term replay.
3. Horizontal scaling across multiple servers.
4. Event retention requirements exceed what Redis Streams can provide.

Until at least one condition is met, Redis Streams remains the official
implementation.

---

## 2. Canonical Event Catalog

Thirteen events. No others exist. Any service publishing an event not on this
list is in violation of `SERVICE_CONTRACTS.md`.

### Deal events

| Event | Meaning |
|---|---|
| `DEAL_DETECTED` | A listing satisfied the rule engine and a deal candidate was created |
| `DEAL_SCORED` | The deal received its 0-100 score |
| `DEAL_NOTIFIED` | The deal passed the confidence threshold and was published to the user |
| `USER_INTERESTED` | The user tapped Interested |
| `DEAL_REVALIDATION_REQUEST` | The Revalidation Service asked for a live listing refresh |
| `DEAL_REVALIDATED` | A live listing refresh completed and was compared against stored data |
| `DEAL_EXPIRED` | The deal reached its terminal expired state |

### Purchase events

| Event | Meaning |
|---|---|
| `PURCHASE_REQUESTED` | The user confirmed quantity and approved the purchase |
| `ORDER_PLANNED` | The planner produced an allocation across accounts |
| `PURCHASE_TASK_CREATED` | A per-account executable task was queued |
| `PURCHASE_COMPLETED` | A purchase task finished successfully |
| `PURCHASE_FAILED` | A purchase task failed |
| `PURCHASE_CANCELLED` | The user cancelled before execution |

### Removed names

These appeared in earlier drafts and are no longer valid. They must not be
published, consumed, or referenced in code.

| Removed | Replacement | Previously appeared in |
|---|---|---|
| `DEAL_INTERESTED` | `USER_INTERESTED` | `ZIP_02` (this file, prior revision) |
| `PURCHASE_PLANNED` | `ORDER_PLANNED` | `ZIP_02` (this file, prior revision) |
| `DEAL_UPDATED` | none — event deleted | `ZIP_02` (this file, prior revision) |
| `DEAL_FOUND` | `DEAL_DETECTED` | `ZIP_02` (prior revision), `ZIP_05/EVENTS.md` |

`DEAL_SCORED` and `DEAL_NOTIFIED` are official, persisted events. They are
not internal steps.

### Revalidation is event-driven

The Bot does not call the connector. The official flow is:

```
USER_INTERESTED
      |
      v
DEAL_REVALIDATION_REQUEST      (Revalidation Service)
      |
      v
Marketplace Connector          (live listing fetch)
      |
      v
DEAL_REVALIDATED               (Revalidation Service)
      |
      v
Telegram Bot
```

This removes the earlier synchronous Bot-to-Connector call implied by
`ZIP_06/LIVE_PRICE_REFRESH.md`, and keeps `SERVICE_COMMUNICATION.md` intact:
synchronous APIs remain reserved for dashboard and admin.

> **Conflict on record.** `ZIP_02/SERVICE_RESPONSIBILITIES.md` section 5
> specifies that the Order Planner obtains account availability through
> `ACCOUNT_ALLOCATION_REQUEST` and `ACCOUNT_ALLOCATION_RESPONSE`. Those two
> names are not in the thirteen-event catalog above. Either the catalog is
> fifteen events, or those two are a separate request/response channel that
> is not part of the business event catalog. Not resolved here. See open
> question Q35.

---

## 3. Event Versioning

**Every event is versioned from day one.** This satisfies the requirement in
`SERVICE_CONTRACTS.md` that all services communicate through versioned event
payloads.

Naming form:

```
DEAL_NOTIFIED.v1
ORDER_PLANNED.v1
```

Every event in section 2 exists at `.v1` at project start.

> **Incomplete.** The version suffix form is decided, but the following are
> not yet specified: whether the version lives in the stream name or the
> payload, the compatibility policy for adding a field, and how long a
> superseded version stays supported. See open question Q14.

---

## 4. Correlation IDs

Every workflow receives a unique `correlation_id`, propagated across all
services for tracing and debugging.

This is the identifier already required by `ZIP_10/LOGGING.md`,
`ZIP_04/COMMON_ERROR_HANDLING.md` and `ZIP_08/LOGGING.md`. A single
correlation ID therefore links a scan, the deal it produced, the
notification, the user's approval, the allocation, and every browser action
taken by the purchase agents.

> **Incomplete.** The field name is decided. The generation point (which
> service mints it) and the propagation mechanism across Redis Streams are
> not yet specified. See open question Q15.

---

## 5. Producers and Consumers

Derived from the service documents. Cells marked *unstated* have no source
document and are listed in section 7.

| Event | Producer | Consumers |
|---|---|---|
| `DEAL_DETECTED` | Deal Engine — Deal Detector (`ZIP_05/DEAL_DETECTOR.md`) | Deal Engine — Scoring |
| `DEAL_SCORED` | Deal Engine — Scoring (`ZIP_05/DEAL_SCORING.md`) | Deal Engine — Notification Engine |
| `DEAL_NOTIFIED` | Deal Engine — Notification Engine (`ZIP_05/NOTIFICATION_ENGINE.md`) | Bot (`ZIP_06/EVENTS.md`) |
| `USER_INTERESTED` | Bot (`ZIP_06/EVENTS.md`) | Revalidation Service |
| `DEAL_REVALIDATION_REQUEST` | Revalidation Service | Marketplace Connectors |
| `DEAL_REVALIDATED` | Revalidation Service | Bot (`ZIP_06/REVALIDATION_FLOW.md`) |
| `DEAL_EXPIRED` | Deal Engine — Deal Lifecycle component | Bot, Revalidation Service, Inventory Service |
| `PURCHASE_REQUESTED` | Bot (`ZIP_06/QUANTITY_COLLECTION.md`) | Order Planner (`ZIP_07/ORDER_PLANNER.md`) |
| `ORDER_PLANNED` | Order Planner (`ZIP_07/EVENT_FLOW.md`) | Order History (`ZIP_07/ORDER_HISTORY.md`) |
| `PURCHASE_TASK_CREATED` | Order Planner (`ZIP_07/PURCHASE_QUEUE.md`) | The one Purchase Agent for that marketplace (`ZIP_07/MARKETPLACE_ROUTING.md`) |
| `PURCHASE_COMPLETED` | Purchase Agent (`ZIP_08/EXECUTION_PIPELINE.md`) | Order History, Inventory Service, Account Service, AI dataset build (`ZIP_09/DATASET_DESIGN.md`) |
| `PURCHASE_FAILED` | Purchase Agent (`ZIP_08/EXECUTION_PIPELINE.md`) | Order History, Account Service |
| `PURCHASE_CANCELLED` | Bot (`ZIP_06/EVENTS.md`) | Order History |

**In addition, the Event Store Consumer subscribes to every event above** and
persists each one into the `events` table (`ZIP_03/EVENT_STORE.md`). No
business service writes to the event database directly.

```
Redis Streams
     |
     v
Event Store Consumer
     |
     v
events table
```

---

## 6. Delivery Guarantees and Failure Handling

From `FAILURE_RECOVERY.md`, binding on every consumer:

- Consumers are idempotent — processing the same event twice must not change
  the outcome.
- Transient failures are retried.
- Unrecoverable events are dead-lettered for manual inspection
  (`ZIP_07/DEAD_LETTER_QUEUE.md`).
- Partial failures are compensated.

> **Incomplete.** Idempotency is mandated but no idempotency key is defined
> for any consumer. Retry counts and backoff constants for event consumption
> are also unspecified. See open question Q17.

---

## 7. Open Points

1. ~~Revalidation producer unstated.~~ **Resolved:** the Revalidation
   Service owns `DEAL_REVALIDATION_REQUEST` and `DEAL_REVALIDATED`.
2. ~~Producer of `DEAL_EXPIRED` unstated.~~ **Resolved:** the Deal Lifecycle
   component inside the Deal Engine.
3. Event version placement and compatibility policy (Q14).
4. Correlation ID generation point and propagation mechanism (Q15).
5. Idempotency keys and consumer retry constants (Q17).
6. No payload schema exists for any of the thirteen events. Field lists,
   types and required/optional status are undefined (Q18). This is the
   largest remaining gap in this package.
7. `ACCOUNT_ALLOCATION_REQUEST` / `ACCOUNT_ALLOCATION_RESPONSE` sit outside
   the catalog (Q35, see section 2).
