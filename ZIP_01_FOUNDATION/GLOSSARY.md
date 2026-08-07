# Glossary

Shared vocabulary for the Deal Intelligence System. Every definition below is
derived from an existing document in this repository, and the source is cited
so it can be verified. Where a term is used inconsistently across packages,
that is recorded as an open point rather than silently resolved.

---

## Core Domain Terms

### Deal
A candidate purchase opportunity created when a listing satisfies the
configurable business rules of the rule engine
(`ZIP_05/DEAL_DETECTOR.md`, `ZIP_05/RULE_ENGINE.md`).

A deal has an immutable identifier (`ZIP_03/CONSTRAINTS.md`) and moves through
a lifecycle recorded in `ZIP_03/DEAL_HISTORY.md`:

```
DETECTED -> NOTIFIED -> INTERESTED -> REVALIDATED -> ORDERED | EXPIRED
```

> **Inconsistency on record:** `ZIP_02/STATE_DIAGRAMS.md` gives the deal
> lifecycle as `NEW -> SCORED -> NOTIFIED -> INTERESTED -> REVALIDATED ->
> ORDERED | EXPIRED`. The two differ in the first state name (`NEW` vs
> `DETECTED`) and in whether `SCORED` is a distinct state. See open question
> Q3.

### Listing
A marketplace-specific offer for a product. Listings carry a unique
marketplace listing ID (`ZIP_03/CONSTRAINTS.md`) and are stored in the
`listings` table (`ZIP_03/TABLES.md`). A listing is related to exactly one
marketplace and one product, and is the entity from which deals are derived
(`ZIP_03/RELATIONSHIPS.md`).

> **Inconsistency on record:** `ZIP_03/ER_DIAGRAM.md` does not list Listing
> among its entities, although `ZIP_03/TABLES.md` and
> `ZIP_03/RELATIONSHIPS.md` both use it. See open question Q4.

### Canonical Product
The single normalized product schema that all marketplace data is converted
into, regardless of source (`ZIP_03/CANONICAL_PRODUCT_MODEL.md`,
`ZIP_04/COMMON_NORMALIZATION.md`). Listings are mapped onto canonical
products using brand, title, identifiers and attributes
(`ZIP_04/PRODUCT_MAPPING.md`).

The purpose of the canonical model is that downstream services remain
source-agnostic (`ZIP_04/DATA_SOURCE_STRATEGY.md`).

### Marketplace
A supported external commerce platform. The supported set is Amazon,
Flipkart, Myntra and Nykaa (`ZIP_04/AMAZON.md`, `ZIP_04/FLIPKART.md`,
`ZIP_04/MYNTRA.md`, `ZIP_04/NYKAA.md`).

Marketplace identity is immutable across the deal and order lifecycle
(`ZIP_02/ARCHITECTURE_DECISIONS.md`, ADR-005), which is what makes
marketplace routing deterministic (`ZIP_07/MARKETPLACE_ROUTING.md`).

### Price Snapshot
An immutable record of a listing price at a point in time. Prices are stored
as snapshots rather than overwritten, tracking `first_seen`, `last_seen` and
`lowest_price` (`ZIP_03/PRICE_HISTORY_DESIGN.md`, `ZIP_05/PRICE_TRACKER.md`).
Snapshots are the input to historical analysis
(`ZIP_05/HISTORICAL_PRICE_ANALYSIS.md`).

### Account
A marketplace account used to execute purchases. Accounts carry per-account
limits, cooldowns and availability, and are subject to allocation constraints
(`ZIP_07/ACCOUNT_ALLOCATION.md`). Accounts are stored in the `accounts` table
(`ZIP_03/TABLES.md`).

### Account Health
The tracked operational condition of an account: login status, verification
needs, recent failures, cooldowns and temporary disablement
(`ZIP_07/ACCOUNT_HEALTH.md`). Health score is one of the inputs to allocation
(`ZIP_07/ACCOUNT_ALLOCATION.md`).

### Order
The record of a planned and executed purchase. Orders progress through
`REQUESTED -> PLANNED -> EXECUTING -> SUCCESS | FAILED`
(`ZIP_02/STATE_DIAGRAMS.md`). Orders and their line items are stored in the
`orders` and `order_items` tables (`ZIP_03/TABLES.md`).

### Revalidation
The mandatory live refresh of a listing before a purchase proceeds. When a
user expresses interest, the system refreshes the live listing before asking
for quantity; if the price changed or the deal expired, the user is notified
with updated status instead (`ZIP_05/REVALIDATION_FLOW.md`,
`ZIP_06/REVALIDATION_FLOW.md`).

The governing rule is that cached notification data is never used for
purchase decisions (`ZIP_06/LIVE_PRICE_REFRESH.md`,
`ZIP_05/CACHE_STRATEGY.md`). Revalidation before purchase is ADR-004
(`ZIP_02/ARCHITECTURE_DECISIONS.md`).

---

## Service Terms

### Connector
The per-marketplace ingestion component. One connector per marketplace is
ADR-002 (`ZIP_01/DECISION_LOG.md`). Every connector implements the same
interface: `fetch_products()`, `fetch_listing()`, `refresh_listing()`,
`normalize()` (`ZIP_04/CONNECTOR_INTERFACE.md`).

A connector abstracts the retrieval method, so that downstream services do
not know or care how data was obtained (`ZIP_04/DATA_SOURCE_STRATEGY.md`).
Browser automation, where used, sits behind an adapter and is kept separate
from connector logic (`ZIP_04/BROWSER_STRATEGY.md`).

### Scanner
The worker that periodically collects marketplace listings through connectors
and emits normalized products (`ZIP_05/SCANNER_ENGINE.md`). Scan frequency is
assigned by the scheduler, not by the scanner itself.

### Scheduler
The priority component that assigns scan frequency by marketplace, category
and product importance, with backoff (`ZIP_05/SCHEDULER.md`). Described in
`ZIP_02/SCHEDULER.md` as periodic scanning by priority tiers with retry and
backoff.

### Deal Engine
The service that detects and scores deals (`ZIP_02/SERVICE_RESPONSIBILITIES.md`).
It comprises the rule engine, deal detector, duplicate detection, price
tracker, historical price analysis, scoring and the notification engine (all
`ZIP_05`).

### Bot
The Telegram service that interacts with the user
(`ZIP_02/SERVICE_RESPONSIBILITIES.md`). It receives events from the Deal
Engine and publishes user actions to the event bus
(`ZIP_06/TELEGRAM_ARCHITECTURE.md`). It is the human-in-the-loop gate
required by `ZIP_01/PROJECT_PHILOSOPHY.md`.

### Planner
Short for Order Planner. Receives the purchase request, validates the deal,
and allocates the requested quantity across eligible accounts belonging to
the same marketplace (`ZIP_07/ORDER_PLANNER.md`). Its optimization objective
is to satisfy the requested quantity with the minimum number of accounts
while honoring platform constraints (`ZIP_07/OPTIMIZATION.md`).

### Purchase Agent
The marketplace-specific execution service that performs the checkout
workflow. One purchase agent per marketplace is ADR-003
(`ZIP_02/ARCHITECTURE_DECISIONS.md`). Each agent consumes only its own
marketplace's tasks (`ZIP_08/AMAZON_PURCHASE_AGENT.md` and siblings).

Execution pipeline: `Task -> Agent -> Login -> Validate Listing ->
Add Quantity -> Review -> Checkout -> Result Event`
(`ZIP_08/EXECUTION_PIPELINE.md`).

### Inference Service
The dedicated API that serves model scoring requests, with fallbacks
(`ZIP_09/INFERENCE_SERVICE.md`). Runs as its own FastAPI service
(`ZIP_10/FASTAPI.md`).

### API Gateway
The entry point exposing REST endpoints, authentication, rate limiting and
request routing (`ZIP_02/API_GATEWAY.md`). Synchronous APIs are reserved for
dashboard and admin use (`ZIP_02/SERVICE_COMMUNICATION.md`).

---

## Architecture Terms

### Event
A business fact published to the event bus. Event-driven architecture is
ADR-001 (`ZIP_01/DECISION_LOG.md`). All services communicate through
versioned event payloads and never call another service's database directly
(`ZIP_02/SERVICE_CONTRACTS.md`). Events are persisted for replay and auditing
(`ZIP_03/EVENT_STORE.md`) and stored in the `events` table
(`ZIP_03/TABLES.md`).

> **Inconsistency on record:** the event names in
> `ZIP_02/EVENT_DRIVEN_ARCHITECTURE.md`, `ZIP_05/EVENTS.md`,
> `ZIP_06/EVENTS.md` and `ZIP_07/EVENT_FLOW.md` do not agree. See open
> question Q2.

### Event Bus
The asynchronous transport carrying events between services, described as
Redis Streams or Kafka (`ZIP_02/SERVICE_COMMUNICATION.md`). Kafka is marked
optional for production scalability (`ZIP_02/KAFKA.md`, `ZIP_10/KAFKA.md`),
and Redis Streams is stated as acceptable for MVP (`ZIP_10/KAFKA.md`).

> **Undecided.** No document selects one. See open question Q1.

### Idempotent Consumer
A consumer that can process the same event more than once without changing
the outcome. Required by `ZIP_02/FAILURE_RECOVERY.md`.

### Dead Letter Queue (DLQ)
The destination for events that cannot be recovered, routed for manual
inspection (`ZIP_02/FAILURE_RECOVERY.md`, `ZIP_07/DEAD_LETTER_QUEUE.md`).

### Correlation ID
An identifier carried through logs to link related activity across services
(`ZIP_10/LOGGING.md`, `ZIP_04/COMMON_ERROR_HANDLING.md`). In the purchase
path it links a purchase task to the browser actions taken for it
(`ZIP_08/LOGGING.md`).

### Circuit Breaker
The protection applied alongside exponential backoff with jitter in connector
retries (`ZIP_04/COMMON_RETRY_STRATEGY.md`).

### Transient vs Permanent Error
The classification applied to connector failures, which determines whether an
operation is retried (`ZIP_04/COMMON_ERROR_HANDLING.md`). The same split
governs planning retries (`ZIP_07/RETRY_LOGIC.md`) and event handling
(`ZIP_02/FAILURE_RECOVERY.md`).

---

## Intelligence Terms

### Score
The ranking value assigned to a deal. Currently a hybrid: rule-based now,
machine-learned later (`ZIP_05/DEAL_SCORING.md`,
`ZIP_09/DEAL_SCORING_MODEL.md`). The stated composition is:

```
score = discount + history + seller + popularity + confidence
```

> **Incomplete.** The document gives the terms but no weights, no
> normalization and no output range. See open question Q7.

### Confidence
A component of the score (`ZIP_05/DEAL_SCORING.md`) and the basis of the
notification filter: only high-confidence deals are published
(`ZIP_05/NOTIFICATION_ENGINE.md`).

> **Incomplete.** No document defines how confidence is computed or what
> threshold counts as "high". See open question Q8.

### Rule Engine
The configurable filter that decides whether a listing qualifies. Its stated
inputs are approved brands, categories, minimum discount, seller thresholds
and exclusions (`ZIP_05/RULE_ENGINE.md`).

### Duplicate Detection
Deduplication by marketplace listing ID and canonical product mapping
(`ZIP_05/DUPLICATE_DETECTION.md`). The notification engine separately
prevents duplicate notifications (`ZIP_05/NOTIFICATION_ENGINE.md`).

### Deal Candidate
The output of the deal detector before scoring: created when the configurable
business rules are satisfied (`ZIP_05/DEAL_DETECTOR.md`).

---

## Process Terms

### ZIP
A numbered documentation package in this repository. ZIP_01 through ZIP_12,
read in the order given by `ZIP_01/ROADMAP.md` and the per-package
`NEXT_ZIP.md` chain. See `ZIP_12/DEPENDENCY_GRAPH.md`.

### CURRENT_STATE
The project memory file recording completed work, active module, blockers and
next action (`ZIP_12/CURRENT_STATE.md`). Each ZIP also carries a
`CURRENT_STATE.json` recording the completed ZIP number and next phase. It is
the first thing read on boot (`ZIP_12/BOOT_SEQUENCE.md`) and on session
recovery (`ZIP_12/SESSION_RECOVERY.md`).

### ADR
Architecture Decision Record. Indexed in `ZIP_01/DECISION_LOG.md` (ADR-001,
ADR-002) and `ZIP_02/ARCHITECTURE_DECISIONS.md` (ADR-003, ADR-004, ADR-005).

> **Incomplete.** All five ADRs are recorded as one-line titles with no
> context, alternatives or consequences. See open question Q5.

### Human-in-the-Loop
The principle that no purchase happens without human approval
(`ZIP_01/PROJECT_PHILOSOPHY.md`, `ZIP_01/BUSINESS_REQUIREMENTS.md`,
`ZIP_02/SYSTEM_DESIGN.md`). Enforced at the Bot confirmation step
(`ZIP_06/ORDER_CONFIRMATION.md`) and guarded again at execution time, where
agents require upstream confirmation before acting
(`ZIP_08/SAFETY_GUARDS.md`).
