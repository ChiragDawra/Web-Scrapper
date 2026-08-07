# Service Interfaces

Method-level contract each service must implement, independent of
language/framework. "Handles" = subscribes to the named event and must
produce the named side effects; "Emits" = publishes onto the bus. Table
ownership per `DATABASE_SCHEMA.md` "Table ownership" section; a service may
only read/write tables listed there for it.

---

## 1. Marketplace Connector (one deployable per marketplace)

**Handles:** none (source of ingestion, runs on a schedule/poll).

**Emits:** `LISTING_DISCOVERED` (`EVENT_SCHEMAS.md` §2).

**Must implement:**
```
normalize(raw_marketplace_response) -> CanonicalProduct
```
`normalize()` is the sole place marketplace-specific parsing lives — every
downstream service consumes only `CanonicalProduct`
(`CANONICAL_MODELS.md`). On `CONN_PARSE_FAILED`, logs and skips the item;
does not emit a partial/malformed `LISTING_DISCOVERED`.

Owns no tables.

---

## 2. Deal Engine

**Handles:** `LISTING_DISCOVERED`, `USER_INTERESTED`.

**Emits:** `DEAL_SCORED`.

**Must implement:**
```
score(product: CanonicalProduct) -> ScoredDeal | null
```
Returns `null` (no event emitted) if the listing doesn't clear the minimum
discount/score threshold — silent skip, not an error.

```
resolveBrand(brand_name: string) -> brand_id
```
Case-insensitive exact match against `brands`; creates a `STANDARD`-tier row
on miss (`CANONICAL_MODELS.md` "Brand resolution").

Owns: `brands`, `marketplaces`, `products`, `listings`, `price_history`,
`deals`. Dedup rule: at most one open (non-terminal) `deals` row per
`listing_id` (`DATABASE_SCHEMA.md` §6).

---

## 3. Revalidation Service

**Handles:** `DEAL_REVALIDATION_REQUEST`.

**Emits:** `DEAL_REVALIDATED`.

**Must implement:**
```
revalidate(listing_id: UUID) -> RevalidationResult
```
Fetches current price/stock live from the marketplace (via the relevant
Connector's read path, not a cached `listings` row) and computes `changed`
per the 2%-delta / stock-flip guard (`STATE_TRANSITIONS.md` §1). Must
respond within 30s or the Bot times out and treats it as changed
(`REVAL_TIMEOUT`) — the service should not bother emitting late.

Owns no tables (stateless).

---

## 4. Telegram Bot

**Handles:** `DEAL_SCORED`, `DEAL_REVALIDATED`, `PURCHASE_COMPLETED`,
`PURCHASE_FAILED`.

**Emits:** `USER_INTERESTED`, `DEAL_REVALIDATION_REQUEST`,
`PURCHASE_REQUESTED`.

**Must implement:**
```
handleCallback(telegram_user_id, callback_data) -> void
```
Looks up `bot_conversations` by `telegram_user_id` (PK), applies the guard
in `STATE_TRANSITIONS.md` §4 (rejects a second interaction while
`state != IDLE`), and drives the conversation state machine.

```
sweepTimeouts() -> void
```
Scheduled every 60s; compares `state_entered_at` against the fixed
thresholds (10 min for `AWAITING_QUANTITY`, 5 min for
`AWAITING_CONFIRMATION`) and reverts to `IDLE` per §4.

Owns: `telegram_users`, `user_interests`, `bot_conversations`,
`bot_messages`, `bot_audit_log`.

---

## 5. Order Planner

**Handles:** `PURCHASE_REQUESTED`, `ACCOUNT_ALLOCATION_RESPONSE`,
`PURCHASE_COMPLETED`, `PURCHASE_FAILED`.

**Emits:** `ACCOUNT_ALLOCATION_REQUEST`, `PURCHASE_TASK_CREATED`.

**Must implement:**
```
plan(order_id, requested_quantity, marketplace) -> void
```
Requests allocation; on `AllocationPlan` with `allocations.length == 0`,
transitions the order to `PLANNING_FAILED` (`PLAN_NO_ACCOUNTS`). Otherwise
proceeds to `PLANNED` even if `fully_satisfied == false`
(`STATE_TRANSITIONS.md` §2 partial-allocation guard) and emits one
`PURCHASE_TASK_CREATED` per allocation line.

```
reconcile(order_id) -> void
```
Invoked on each `PURCHASE_COMPLETED`/`PURCHASE_FAILED` for that order's
tasks; once all `order_items` for the order are terminal, computes
`fulfilled_quantity` and sets final `order_status`
(`COMPLETED`/`PARTIAL`/`FAILED`) per §2. `total_amount` is fixed at
`PLANNED` and never recalculated here.

Owns: `orders`, `order_items`, `purchase_tasks`.

---

## 6. Account Service

**Handles:** `ACCOUNT_ALLOCATION_REQUEST`, `PURCHASE_COMPLETED`,
`PURCHASE_FAILED`.

**Emits:** `ACCOUNT_ALLOCATION_RESPONSE`, `ACCOUNT_HEALTH_CHANGED`.

**Must implement:**
```
allocate(marketplace, requested_quantity) -> AllocationPlan
```
Query excludes any account with
`status IN ('COOLDOWN','SUSPENDED','BANNED','DISABLED_MANUAL')`
(`STATE_TRANSITIONS.md` §3 guard) and respects `daily_spend_cap -
daily_spend_used` per account. Must respond within 10s (Planner's
`PLAN_ALLOCATION_TIMEOUT` budget).

```
applyHealthDelta(account_id, event_type, reason) -> void
```
Applies the fixed deltas table in `STATE_TRANSITIONS.md` §3 and performs any
resulting status transition (e.g. `health_score` hits 0 -> `BANNED`),
emitting `ACCOUNT_HEALTH_CHANGED` on every change, not just band crossings.

```
resetDailySpend() -> void
```
Scheduled job, 00:00 IST, sets `daily_spend_used = 0` for all accounts.

Owns: `accounts`.

---

## 7. Purchase Agent (worker pool, one task at a time per worker)

**Handles:** `PURCHASE_TASK_CREATED`.

**Emits:** `PURCHASE_COMPLETED`, `PURCHASE_FAILED`.

**Must implement:**
```
execute(purchase_task: PURCHASE_TASK_CREATED payload) -> PurchaseOutcome
```
Runs checkout automation for the given `account_id`/`listing_id`. Aborts
with `PURCH_PRICE_MISMATCH` if the live checkout price exceeds `max_price`.
Retries per `STATE_TRANSITIONS.md` §5 (exponential backoff, base 2s,
multiplier 2, up to 3 attempts for infra-level errors before
`DEAD_LETTERED`; business-level failures — price mismatch, out of stock —
go straight to `FAILED`, no retry).

Owns no tables; all state changes go through `purchase_tasks` via events
consumed by Order Planner (Purchase Agent does not write `purchase_tasks`
directly — Order Planner is the owner).

---

## 8. Inventory Service

**Handles:** `PURCHASE_COMPLETED`.

**Emits:** none (MVP).

**Must implement:**
```
recordAcquisition(purchase_task_id, listing_id, quantity, purchase_price) -> void
```
Creates one `inventory_items` row per successful `PURCHASE_COMPLETED`.
Idempotent on `purchase_task_id` (dedup via `processed_events`, not a
unique constraint on this table — `EVENT_SCHEMAS.md` §1).

Owns: `inventory_items`.

---

## 9. Event Store Consumer

**Handles:** every event type (subscribes to all streams).

**Emits:** none.

**Must implement:**
```
persist(envelope) -> void
```
Sole writer to `events` (ADR-010); validates the envelope + payload against
its JSON Schema before insert, rejecting with `SYS_EVENT_SCHEMA_INVALID` on
mismatch — this is the enforcement point for `EVENT_SCHEMAS.md`, not a
per-producer client-side check alone.

Owns: `events`.

---

## 10. API Gateway

**Handles:** none (HTTP-only, no event subscriptions).

**Emits:** none directly — delegates all state-changing operations to
events published by the calling client (e.g. Bot emits `PURCHASE_REQUESTED`
itself; the Gateway never emits on a client's behalf).

**Must implement:** the full route table in `API_CONTRACTS.md`, reading
only from each service's owned tables via read-replica or direct query
(read-only exception to ADR-009 — the Gateway is explicitly allowed
cross-boundary reads for query endpoints, but never writes).

Owns no tables.

---

## 11. ML Service

**Handles:** none synchronously — batch job reads `events` table directly
(the one sanctioned exception to "consume events, don't read tables",
since `events` is an intentionally shared append-only log, not
service-private state).

**Emits:** none (MVP; Phase 2 may emit re-scoring suggestions).

**Must implement:**
```
exportTrainingData(date_range) -> TrainingFeatureRowDTO[]
```
See `DTOS.md` §5.

Owns no tables.
