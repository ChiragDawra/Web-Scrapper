# Service Responsibilities

Defines what each service owns, what it must not do, and where its
boundaries lie. Every statement is derived from an existing document in this
repository and cited. Where a responsibility is stated nowhere, it is listed
in section 9 as an open point rather than assigned by assumption.

The service list is taken from `SYSTEM_DESIGN.md`: Marketplace Connectors,
Deal Engine, Bot, Order Planner, Purchase Agents, AI Services,
Infrastructure. The API Gateway is defined separately in `API_GATEWAY.md`.

---

## Rules Binding Every Service

From `SERVICE_CONTRACTS.md`:

- Communicate only through versioned event payloads.
- Never call another service's internal database directly.

From `SERVICE_COMMUNICATION.md`:

- Inter-service traffic is asynchronous, over Redis Streams or Kafka.
- Synchronous APIs exist only for dashboard and admin use.

From `FAILURE_RECOVERY.md`:

- Retry transient failures.
- Dead-letter unrecoverable events.
- Be an idempotent consumer.
- Compensate for partial failures.

From `ZIP_10/LOGGING.md`: emit structured JSON logs carrying correlation IDs.

---

## 1. Marketplace Connectors

**Owns:** ingesting marketplace data.

Responsibilities:

- Implement the shared interface: `fetch_products()`, `fetch_listing()`,
  `refresh_listing()`, `normalize()` (`ZIP_04/CONNECTOR_INTERFACE.md`).
- Convert marketplace-specific fields into the canonical product model
  (`ZIP_04/COMMON_NORMALIZATION.md`, `ZIP_03/CANONICAL_PRODUCT_MODEL.md`).
- Map listings onto canonical products using brand, title, identifiers and
  attributes (`ZIP_04/PRODUCT_MAPPING.md`).
- Abstract the retrieval method so downstream services stay source-agnostic
  (`ZIP_04/DATA_SOURCE_STRATEGY.md`).
- Classify errors as transient or permanent and log correlation IDs
  (`ZIP_04/COMMON_ERROR_HANDLING.md`).
- Retry with exponential backoff, jitter and a circuit breaker
  (`ZIP_04/COMMON_RETRY_STRATEGY.md`).
- Serve live listing refreshes on demand for revalidation
  (`ZIP_06/LIVE_PRICE_REFRESH.md`).

Boundaries:

- One connector per marketplace; connectors are not shared
  (ADR-002, `ZIP_01/DECISION_LOG.md`).
- Browser automation sits behind an adapter, separate from connector logic
  (`ZIP_04/BROWSER_STRATEGY.md`).
- Connectors do not decide whether something is a deal. That is the Deal
  Engine's job (`ZIP_05/DEAL_DETECTOR.md`).
- Credentials are not embedded; secrets are stored securely
  (`ZIP_04/AUTHENTICATION.md`, `ZIP_10/SECRETS.md`).

Implementations: Amazon, Flipkart, Myntra, Nykaa (`ZIP_04/AMAZON.md`,
`ZIP_04/FLIPKART.md`, `ZIP_04/MYNTRA.md`, `ZIP_04/NYKAA.md`).

---

## 2. Scanner Engine and Scheduler

`SCHEDULER.md` in this package describes periodic scanning by priority tiers
with retry and backoff. `ZIP_05` splits the work in two.

**Scanner Engine owns:** periodic collection.

- Worker processes collect marketplace listings through connectors and emit
  normalized products (`ZIP_05/SCANNER_ENGINE.md`).

**Scheduler owns:** when scanning happens.

- Assigns scan frequency by marketplace, category and product importance,
  with backoff (`ZIP_05/SCHEDULER.md`).

Boundaries:

- The scanner does not choose its own frequency.
- The scanner does not evaluate business rules.

---

## 3. Deal Engine

**Owns:** detecting and scoring deals.

Responsibilities, each a component documented in `ZIP_05`:

| Component | Responsibility | Source |
|---|---|---|
| Rule Engine | Evaluate approved brands, categories, minimum discount, seller thresholds, exclusions | `RULE_ENGINE.md` |
| Deal Detector | Create deal candidates when rules are satisfied | `DEAL_DETECTOR.md` |
| Duplicate Detection | Deduplicate by marketplace listing ID and canonical product mapping | `DUPLICATE_DETECTION.md` |
| Price Tracker | Store immutable price snapshots, detect deltas and historical lows | `PRICE_TRACKER.md` |
| Historical Price Analysis | Compute lowest price, average price, discount history, volatility | `HISTORICAL_PRICE_ANALYSIS.md` |
| Deal Scoring | Produce the deal score, rules now and ML later | `DEAL_SCORING.md` |
| Notification Engine | Publish only high-confidence deals, suppress duplicates, include marketplace and deal ID | `NOTIFICATION_ENGINE.md` |
| Cache | Cache listing metadata and recent scans | `CACHE_STRATEGY.md` |

Boundaries:

- Never cache purchase decisions (`ZIP_05/CACHE_STRATEGY.md`).
- Does not talk to the user. Notification is published as an event; the Bot
  owns the conversation (`ZIP_06/TELEGRAM_ARCHITECTURE.md`).
- Does not allocate accounts or place orders.

---

## 4. Bot

**Owns:** user interaction and the human approval gate.

Responsibilities:

- Receive events from the Deal Engine and publish user actions to the event
  bus (`ZIP_06/TELEGRAM_ARCHITECTURE.md`).
- Render the deal card with platform, brand, product, current price, MRP,
  discount, deal ID and last verified time
  (`ZIP_06/MESSAGE_TEMPLATES.md`).
- Offer the inline buttons Interested, Ignore, Watch Later
  (`ZIP_06/BUTTONS.md`).
- On Interested, store deal ID and timestamp, then request a live refresh
  from the marketplace connector (`ZIP_06/INTERESTED_FLOW.md`).
- Collect quantity only after successful revalidation
  (`ZIP_06/BUTTONS.md`, `ZIP_06/REVALIDATION_FLOW.md`).
- Validate quantity against limits, then publish the purchase request
  (`ZIP_06/QUANTITY_COLLECTION.md`).
- Present platform, latest price, quantity and estimated total for final
  confirmation (`ZIP_06/ORDER_CONFIRMATION.md`).
- Maintain conversation state, message mapping, pending actions and an audit
  log (`ZIP_06/BOT_DATABASE.md`).
- Hold conversation state across `IDLE, DEAL_SENT, INTERESTED, REVALIDATING,
  WAITING_QUANTITY, CONFIRMING, COMPLETED, CANCELLED` (`ZIP_06/STATES.md`).

Boundaries:

- Never rely on cached notification data for purchases; always query the
  latest listing through the connector (`ZIP_06/LIVE_PRICE_REFRESH.md`).
- If the deal expired or changed, send an updated deal card instead of
  proceeding to quantity (`ZIP_06/REVALIDATION_FLOW.md`).
- Does not choose accounts, does not execute purchases.

---

## 5. Order Planner

**Owns:** turning an approved purchase request into executable tasks.

Responsibilities:

- Receive the purchase request, validate the deal, and allocate quantity
  across eligible accounts for the same marketplace
  (`ZIP_07/ORDER_PLANNER.md`).
- Respect per-account limits, cooldowns, availability and health score
  (`ZIP_07/ACCOUNT_ALLOCATION.md`).
- **Read** account availability and health from the Account Service. The
  Planner does not compute or update health; it consumes it (section 9).
- Satisfy the requested quantity using the minimum number of accounts while
  honoring platform constraints (`ZIP_07/OPTIMIZATION.md`).
- Publish planned purchase tasks to marketplace-specific queues
  (`ZIP_07/PURCHASE_QUEUE.md`).
- Persist planning decisions, execution status and audit trail
  (`ZIP_07/ORDER_HISTORY.md`).
- Retry transient planning failures without duplicating successful
  allocations (`ZIP_07/RETRY_LOGIC.md`).
- Route unrecoverable planning events to the dead letter queue for manual
  inspection (`ZIP_07/DEAD_LETTER_QUEUE.md`).

Boundaries:

- Platform is immutable. An Amazon deal routes only to the Amazon Purchase
  Agent, and the same for every other marketplace
  (`ZIP_07/MARKETPLACE_ROUTING.md`, ADR-005 in `ARCHITECTURE_DECISIONS.md`).
- Does not drive a browser or contact a marketplace.
- Does not own accounts. Storage, health, cooldowns, limits and rotation
  belong to the Account Service (section 9).
- Does not own inventory. That belongs to the Inventory Service
  (section 10).

The Planner's scope is allocation and planning only.

Known failure scenarios it must handle: insufficient accounts, limit
reached, expired deal after revalidation, queue failure, partial execution
(`ZIP_07/FAILURE_SCENARIOS.md`).

Optional: a local inventory ledger for purchased and sold units
(`ZIP_07/INVENTORY.md`).

---

## 6. Purchase Agents

**Owns:** marketplace-specific execution.

Responsibilities:

- Consume purchase tasks for one marketplace only
  (`ZIP_08/AMAZON_PURCHASE_AGENT.md`, `ZIP_08/FLIPKART_PURCHASE_AGENT.md`,
  `ZIP_08/MYNTRA_PURCHASE_AGENT.md`, `ZIP_08/NYKAA_PURCHASE_AGENT.md`).
- Execute the pipeline `Task -> Agent -> Login -> Validate Listing ->
  Add Quantity -> Review -> Checkout -> Result Event`
  (`ZIP_08/EXECUTION_PIPELINE.md`).
- Open the product URL and validate the listing before acting
  (`ZIP_08/AMAZON_PURCHASE_AGENT.md`).
- Maintain one browser context per account, with browser automation isolated
  from business logic (`ZIP_08/PLAYWRIGHT_ARCHITECTURE.md`).
- Isolate cookies by account, with rotation and invalidation
  (`ZIP_08/BROWSER_SESSIONS.md`, `ZIP_08/COOKIE_MANAGEMENT.md`).
- Encrypt session state, refresh when expired, never share sessions across
  marketplaces (`ZIP_08/SESSION_PERSISTENCE.md`).
- Recover from UI changes, navigation failures, network issues and
  interrupted execution (`ZIP_08/RECOVERY.md`).
- Emit structured logs with correlation IDs linking the purchase task to
  browser actions (`ZIP_08/LOGGING.md`).

Boundaries and guards, from `ZIP_08/SAFETY_GUARDS.md`:

- Require upstream confirmation before execution.
- Require latest deal validation before execution.
- Respect platform policies.
- Avoid unsafe retry loops.

One purchase agent per marketplace is ADR-003
(`ARCHITECTURE_DECISIONS.md`).

---

## 7. AI Services

**Owns:** analytics and future machine-learned ranking.

Responsibilities:

- Build training datasets from deals, user actions, orders and outcomes,
  with separate train, validation and test splits
  (`ZIP_09/DATASET_DESIGN.md`).
- Engineer features: discount, category, brand, seller, ratings, price
  history, volatility, seasonality, interaction history
  (`ZIP_09/FEATURE_ENGINEERING.md`).
- Run an offline training pipeline with scheduled retraining and model
  versioning (`ZIP_09/TRAINING_PIPELINE.md`).
- Track model versions, metadata, metrics and deployment state
  (`ZIP_09/MODEL_REGISTRY.md`).
- Serve scoring requests through a dedicated inference API with fallbacks
  (`ZIP_09/INFERENCE_SERVICE.md`).
- Evaluate with Precision@K, Recall@K, MAE for profit, RMSE for forecast,
  calibration and business KPIs (`ZIP_09/EVALUATION.md`).

Model surfaces: deal scoring (`ZIP_09/DEAL_SCORING_MODEL.md`), profit
prediction (`ZIP_09/PROFIT_PREDICTION.md`), demand prediction
(`ZIP_09/DEMAND_PREDICTION.md`), recommendations
(`ZIP_09/RECOMMENDATION_SYSTEM.md`).

Boundaries:

- No direct online weight updates in the MVP; feedback is collected after
  purchases for future retraining (`ZIP_09/ONLINE_LEARNING.md`).
- Phased delivery: rules, then analytics, then supervised models, then
  recommendations (`ZIP_09/ML_ROADMAP.md`).

---

## 8. API Gateway

**Owns:** external entry.

Responsibilities: expose REST endpoints, authentication, rate limiting and
request routing (`API_GATEWAY.md`).

Boundaries: synchronous APIs are for dashboard and admin only
(`SERVICE_COMMUNICATION.md`). Runs as its own FastAPI service
(`ZIP_10/FASTAPI.md`), behind Nginx for TLS termination, routing and rate
limiting (`ZIP_10/NGINX.md`).

---

## 9. Account Service

**Owns:** marketplace accounts and their operational condition.

Introduced to remove account management from the Order Planner. The Planner
allocates; the Account Service manages.

Responsibilities:

- Store marketplace accounts.
- Track account health.
- Manage cooldowns.
- Enforce purchase limits.
- Rotate accounts.
- Expose account availability to the Order Planner.

Health scoring model (see `STATE_DIAGRAMS.md` section 4 for the full state
machine):

| Event | Delta |
|---|---|
| Starting score | 100 |
| Login failure | −20 |
| CAPTCHA | −10 |
| Verification required | −40 |
| Successful purchase | +2 |
| Cooldown completed | +5 |

Levels: `> 80` HEALTHY, `50-80` WARNING, `< 50` DISABLED.

Consumes `PURCHASE_COMPLETED` and `PURCHASE_FAILED` to adjust scores
(`EVENT_DRIVEN_ARCHITECTURE.md` section 5).

Boundaries:

- Does not allocate. Allocation is the Planner's decision, taken from the
  availability this service exposes.
- Does not drive browsers. Session and cookie state belong to the Purchase
  Agents (`ZIP_08/SESSION_PERSISTENCE.md`).

> **Incomplete.** No document states the interface by which the Planner
> reads availability — event, synchronous API, or shared read model. Since
> `SERVICE_CONTRACTS.md` forbids reading another service's database, this
> needs an answer. See open question Q32.

---

## 10. Inventory Service

**Owns:** inventory. In scope, not optional. This supersedes the "optional"
wording in `ZIP_07/INVENTORY.md`.

Responsibilities:

- Purchase tracking
- Stock tracking
- Resale tracking
- Profit tracking

Consumes `PURCHASE_COMPLETED` (`EVENT_DRIVEN_ARCHITECTURE.md` section 5).

Boundaries:

- The Order Planner does not own inventory.

> **Incomplete.** No entities, tables or events exist for stock, resale or
> profit. Resale and profit imply a sales channel that appears in no
> document. `ZIP_09/PROFIT_PREDICTION.md` estimates resale margin but does
> not say where realised profit is recorded. See open questions Q31 and Q33.

---

## 11. Event Store Consumer

**Owns:** persisting events.

Responsibilities:

- Subscribe to Redis Streams.
- Persist every event into the `events` table
  (`ZIP_03/EVENT_STORE.md`).

```
Redis Streams -> Event Store Consumer -> events table
```

Boundaries:

- Every service publishes its own events, but **no business service writes
  directly into the event database.** This consumer is the only writer.
- It does not interpret, filter or transform events.

---

## 12. Unassigned Responsibilities

The following work is described somewhere in the repository but no document
states which service performs it. Recorded here rather than assigned.

1. **Deal expiry emission.** The three expiry triggers are defined
   (`STATE_DIAGRAMS.md` section 1), but no document names the service that
   emits `DEAL_EXPIRED`. The TTL trigger in particular implies a timer owner
   that does not exist in any service description. See open question Q16.
2. **Revalidation execution.** Revalidation is event-driven, but no document
   names the service that performs the live connector call and emits
   `DEAL_REVALIDATED`. See open question Q13.
3. **Scoring recomputation.** `SCORED` is a persisted state and prices change
   continuously. No document says whether a deal is rescored on price change
   or scored once. See open question Q34.
