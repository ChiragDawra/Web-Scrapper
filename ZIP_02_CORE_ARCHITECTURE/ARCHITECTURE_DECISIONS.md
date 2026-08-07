# Architecture Decision Records

Canonical ADR register. ADR-001 and ADR-002 are indexed in
`ZIP_01/DECISION_LOG.md` and recorded in full there. ADR-003 onward are
recorded here.

Every ADR uses the same structure:

- Context
- Decision
- Alternatives Considered
- Consequences
- Future Improvements

> **On the Alternatives sections.** The original discussions that produced
> ADR-001 through ADR-005 are not recorded anywhere in this repository. The
> alternatives listed below are **engineering alternatives considered during
> architecture finalization**, reconstructed from the technical shape of each
> decision. They are not a historical record of what was debated, and no
> business motivation has been attributed to anyone.

---

## ADR-003: One Purchase Agent Per Marketplace

### Context

Four marketplaces are supported: Amazon, Flipkart, Myntra and Nykaa
(`ZIP_04`). Checkout is executed through browser automation
(`ZIP_08/PLAYWRIGHT_ARCHITECTURE.md`), and each marketplace has a different
checkout flow, different login and verification behaviour, and different UI
that changes independently of the others.

Purchase execution is the highest-risk operation in the system. It spends
money, it holds authenticated sessions, and it cannot be retried blindly
(`ZIP_08/SAFETY_GUARDS.md`).

### Decision

Each marketplace gets its own purchase agent service. Each agent consumes
only its own marketplace's queue and knows nothing about the others.

### Alternatives Considered

*Engineering alternatives, per the note above.*

1. **One agent with per-marketplace strategy classes.** Fewer services to
   deploy and one place for shared pipeline logic. Rejected: a UI change on
   one marketplace would force redeployment of the code path executing
   purchases on all four, and a crash loop in one flow would stall the
   others.
2. **One agent per account rather than per marketplace.** Maximum isolation.
   Rejected: account count is dynamic and unbounded, making it a scaling
   unit rather than a deployment unit. Isolation at the account level is
   achieved instead through one browser context per account
   (`ZIP_08/PLAYWRIGHT_ARCHITECTURE.md`).

### Consequences

- Four services to build, deploy, monitor and keep current with UI drift.
- Shared pipeline logic must be factored deliberately or it will be copied
  four times. The pipeline shape is common
  (`ZIP_08/EXECUTION_PIPELINE.md`); only the selectors and flows differ.
- Routing becomes trivial and deterministic, which is what ADR-005 depends
  on.
- Failure in one marketplace cannot affect purchases on another.

### Future Improvements

- Extract the common pipeline stages into a shared library once the second
  agent is built and the real variation is visible.
- Per-agent health metrics so UI drift on one marketplace surfaces as an
  isolated alert (`ZIP_10/MONITORING.md`).

---

## ADR-004: Deal Revalidation Before Purchase

### Context

A deal is detected during a scan, scored, and notified. The user may act on
the notification minutes or hours later. Prices change, stock runs out, and
offers end. Acting on notification data risks buying at a price the user
never approved, or buying something no longer available.

The system is explicitly human-in-the-loop
(`ZIP_01/PROJECT_PHILOSOPHY.md`), which only means something if what the
human approves is what actually gets bought.

### Decision

The live listing is refreshed before quantity is collected. If the price
changed or the deal expired, the user is shown updated status instead of
being moved forward. Cached notification data is never used for a purchase
decision.

Revalidation is event-driven and owned by the Revalidation Service (ADR-008).

### Alternatives Considered

*Engineering alternatives, per the note above.*

1. **Trust the notification and validate at checkout only.** One fewer round
   trip and a faster path from tap to purchase. Rejected: the user would
   approve a price that the agent might not honour, breaking the meaning of
   the approval.
2. **Short TTL on notifications instead of revalidation.** Simpler — expire
   the card after a few minutes. Rejected: it narrows the window without
   closing it, and it degrades usability for a user who is not watching
   Telegram continuously.
3. **Revalidate at every state transition.** Maximum freshness. Rejected as
   redundant: the purchase agent independently validates the listing before
   checkout (`ZIP_08/EXECUTION_PIPELINE.md`), so the system already
   validates twice.

### Consequences

- Every Interested tap costs a live marketplace request, on the user's
  latency path.
- The Bot needs a `REVALIDATING` state and the user experiences a wait
  (`ZIP_06/STATES.md`).
- A failed revalidation is an expiry trigger, connecting this ADR to the deal
  lifecycle (`ZIP_02/STATE_DIAGRAMS.md`).
- Two independent validations exist: this one, and the agent's pre-checkout
  check. Both are intentional.

### Future Improvements

- Define a price-change tolerance so that a trivial movement does not force a
  new deal card (currently unspecified, Q48).
- Define a `REVALIDATING` timeout (currently unspecified, Q24).

---

## ADR-005: Platform Preserved Through Lifecycle

### Context

A canonical Product may have Listings on several marketplaces
(`ZIP_03/ER_DIAGRAM.md`). A deal is derived from one specific listing on one
specific marketplace. Accounts, sessions, cookies and checkout flows are all
marketplace-specific and are never shared
(`ZIP_08/SESSION_PERSISTENCE.md`).

If marketplace identity were mutable or inferred late, an order could be
routed to an agent that has no account, no session and no matching listing.

### Decision

Marketplace identity is fixed at detection and is immutable through
detection, scoring, notification, revalidation, planning and execution. An
Amazon deal routes only to the Amazon Purchase Agent, and the same holds for
every other marketplace (`ZIP_07/MARKETPLACE_ROUTING.md`).

### Alternatives Considered

*Engineering alternatives, per the note above.*

1. **Resolve the cheapest marketplace at purchase time.** Would let the
   system buy the same product wherever it is cheapest at execution.
   Rejected: the user approved a specific listing at a specific price on a
   specific platform, so substituting the platform substitutes the approval.
2. **Allow marketplace reassignment when the original goes out of stock.**
   Improves fulfilment rate. Rejected for the same reason, and because
   account allocation is already marketplace-scoped
   (`ZIP_07/ACCOUNT_ALLOCATION.md`).

### Consequences

- Routing is deterministic and requires no lookup.
- Allocation never has to consider cross-marketplace accounts.
- If a deal's marketplace goes out of stock, the deal expires. There is no
  fallback to another marketplace, by design.
- Cross-marketplace price comparison remains possible at the Product level
  but never leaks into the order path.

### Future Improvements

- Surfacing "the same product is cheaper on another marketplace" as a
  *separate new deal* rather than as a substitution would preserve this ADR
  while recovering some of the lost value.

---

## ADR-006: Redis Streams As The Canonical Event Bus

### Context

The architecture is event-driven (ADR-001) and every service communicates
through versioned event payloads (`SERVICE_CONTRACTS.md`). Earlier drafts
described the bus as "Redis Streams or Kafka" and left both open, which meant
no consumer could be designed, because the two differ in ordering, consumer
groups, retention and replay.

Redis is already required for caching, distributed locks, queues and session
state (`REDIS.md`, `ZIP_03/REDIS_SCHEMA.md`), so it is present regardless.

### Decision

Redis Streams is the canonical event bus. Kafka is not part of the MVP.

Migration to Kafka occurs only when at least one of the following is true:

1. More than 100,000 deal events per day.
2. Multiple independent consumers require long-term replay.
3. Horizontal scaling across multiple servers.
4. Event retention requirements exceed what Redis Streams can provide.

### Alternatives Considered

*Engineering alternatives, per the note above.*

1. **Kafka from day one.** Stronger retention, replay and partitioning, and
   no migration later. Rejected for the MVP: it adds an operational
   component with real cost before any of its advantages are needed.
2. **Keep both supported behind an abstraction.** Rejected: an abstraction
   over two buses with different delivery semantics either leaks or forces
   the weaker guarantees on both.
3. **PostgreSQL as a queue.** One fewer component, since PostgreSQL is
   already the primary store. Rejected: it couples event throughput to the
   transactional database.

### Consequences

- One less production component to operate for the MVP.
- Replay depth is bounded by Redis Streams retention, which is why the Event
  Store Consumer persisting to PostgreSQL (ADR-010) is not optional.
- Redis becomes a single point of failure for cache, locks, sessions and now
  events.
- A migration to Kafka is a known future project rather than an emergency,
  with four explicit triggers to watch.

### Future Improvements

- Instrument the four migration triggers so the threshold is observed rather
  than guessed (`ZIP_10/MONITORING.md`).
- Keep consumer code free of Redis-specific assumptions where it is cheap to
  do so.

---

## ADR-007: Dedicated Account Service

### Context

Earlier drafts left account storage, health scoring, cooldowns, limits and
rotation implicitly inside the Order Planner
(`ZIP_07/ACCOUNT_HEALTH.md`). That gave the Planner two unrelated jobs:
deciding how to split a quantity, and managing the operational state of
credentials.

Account state also changes from outside planning — a purchase agent
encountering a CAPTCHA or a verification prompt changes account health with
no planning event involved.

### Decision

A dedicated Account Service owns marketplace accounts: storage, health
tracking, cooldowns, purchase limits, rotation, and exposing availability.

The Order Planner is responsible only for allocation and planning. It reads
availability through `ACCOUNT_ALLOCATION_REQUEST` /
`ACCOUNT_ALLOCATION_RESPONSE` and never reads the Account Service database
(ADR-009).

### Alternatives Considered

*Engineering alternatives, per the note above.*

1. **Keep accounts in the Planner.** One fewer service. Rejected: purchase
   agents also mutate account health, so the Planner would either own state
   it does not observe or expose write paths to agents.
2. **Give each purchase agent its own account store.** Locality with the
   sessions that use them. Rejected: allocation needs a global view of
   availability across accounts before any agent is involved.

### Consequences

- One more service to build and deploy.
- Allocation now requires a request/response round trip, adding latency and a
  timeout case to the planning path (Q38).
- Account health has a single writer, so scoring cannot drift between
  services.
- Purchase agents report outcomes as events and never write account state
  directly.

### Future Improvements

- Attach explicit score effects to the three recovery paths, which currently
  have triggers but no deltas (Q41).

---

## ADR-008: Dedicated Revalidation Service

### Context

ADR-004 requires a live listing refresh before quantity collection. Earlier
drafts had the Bot calling the marketplace connector itself
(`ZIP_06/LIVE_PRICE_REFRESH.md`), which conflicted with
`SERVICE_COMMUNICATION.md`, where synchronous calls are reserved for
dashboard and admin.

### Decision

A dedicated Revalidation Service owns the revalidation path. It consumes
`USER_INTERESTED`, publishes `DEAL_REVALIDATION_REQUEST`, obtains the latest
listing from the marketplace connector, compares it against stored data, and
publishes `DEAL_REVALIDATED`.

The Deal Engine remains responsible only for discovery and scoring. The Bot
waits for an event and never calls a connector.

### Alternatives Considered

*Engineering alternatives, per the note above.*

1. **Bot calls the connector synchronously.** Simplest and lowest latency.
   Rejected: it violates the communication rule and couples the Bot to
   connector availability on the user's latency path.
2. **Deal Engine performs revalidation.** No new service, and the Deal Engine
   already talks to connectors through the scanner. Rejected: it mixes
   discovery with per-user transactional work on a latency-sensitive path.

### Consequences

- One more service to build and deploy.
- The Bot gains a genuinely asynchronous wait, making the `REVALIDATING`
  state and its missing timeout a real concern (Q24).
- Comparison logic lives in one place rather than being duplicated between
  the Bot and the purchase agents.
- `SERVICE_COMMUNICATION.md` holds without exception on this path.

### Future Improvements

- Define the price-change tolerance that decides "changed" versus
  "unchanged" (Q48).

---

## ADR-009: Event-Driven Service Boundaries Without Shared Database Reads

### Context

`SERVICE_CONTRACTS.md` states that no service reads another service's
database. Introducing the Account Service (ADR-007) created the first case
where one service needs data that another owns on a synchronous-feeling path.

### Decision

The rule holds without exception. Cross-service reads are request/response
event pairs. The Planner-to-Account path uses
`ACCOUNT_ALLOCATION_REQUEST` and `ACCOUNT_ALLOCATION_RESPONSE`. No
synchronous API exception is granted.

### Alternatives Considered

*Engineering alternatives, per the note above.*

1. **A synchronous internal API for reads only.** Simpler and lower latency.
   Rejected: read exceptions tend to accumulate until the event bus is
   decorative.
2. **A shared read model that both services query.** Rejected: it reintroduces
   a shared database under another name.

### Consequences

- Every cross-service read costs a round trip and needs a timeout policy.
- Service boundaries stay enforceable rather than advisory.
- The request/response pair is not in the thirteen-event canonical catalog,
  which is currently unresolved (Q35).

### Future Improvements

- Decide whether request/response pairs form a second, separately governed
  channel or belong in the business event catalog (Q35).

---

## ADR-010: Event Store Consumer As Sole Writer

### Context

Business events must be persisted for replay and auditing
(`ZIP_03/EVENT_STORE.md`). Redis Streams retention is bounded (ADR-006), so
durable history cannot live on the bus alone.

### Decision

Every service publishes its own events. No business service writes to the
event database. A dedicated Event Store Consumer subscribes to Redis Streams
and persists each event into the `events` table.

```
Redis Streams -> Event Store Consumer -> events table
```

### Alternatives Considered

*Engineering alternatives, per the note above.*

1. **Each service writes its own events.** No extra component. Rejected: it
   gives every service a write path into a shared table and makes the audit
   trail only as reliable as the least careful service.
2. **Dual-write from producers.** Rejected: publishing and persisting in two
   places without a transaction produces divergence.

### Consequences

- A single writer means one place to enforce format and one place to fail.
- The consumer is a bottleneck and a single point of failure for auditability
  and must be monitored accordingly.
- Consumers must be idempotent, since replay from the store is now possible
  (`FAILURE_RECOVERY.md`).

### Future Improvements

- Define the `events` table columns, which do not yet exist (Q18).

---

## ADR-011: UUID Primary Keys, Marketplace IDs As External References

### Context

Entities are identified internally while also carrying marketplace-assigned
identifiers. `POSTGRESQL_SCHEMA.md` requires UUID primary keys and
`CONSTRAINTS.md` requires unique marketplace listing IDs, and the
relationship between the two was previously unstated.

### Decision

Every internal entity uses an immutable UUID as its primary key.
Marketplace-specific identifiers are stored as unique external reference
columns. **Marketplace identifiers are never used as primary keys.**

Entities carrying UUIDs: Product, Listing, Deal, Order, PurchaseTask,
UserInterest, TelegramUser.

Raw Telegram chat IDs are likewise never used as keys; `user_interests`
references `telegram_user_id`.

### Alternatives Considered

*Engineering alternatives, per the note above.*

1. **Natural keys from marketplaces.** No synthetic key needed. Rejected:
   marketplace identifiers are outside our control, can be reused or
   reformatted, and differ in shape per marketplace.
2. **Integer surrogate keys.** Smaller and faster to index. Rejected:
   sequential keys are guessable and awkward to generate across services
   without coordination.

### Consequences

- Wider keys and larger indexes than integer alternatives.
- IDs can be generated anywhere without coordination, which suits
  event-driven services.
- Marketplace identifiers remain queryable through unique constraints
  without becoming structural.
- Deal IDs are immutable as `CONSTRAINTS.md` already required.

### Future Improvements

- Whether Brand, Marketplace, OrderItem, PriceHistory, Account and Event also
  take UUIDs is still unstated (Q29).

---

## ADR-012: Inventory Limited To Purchase Tracking In The MVP

### Context

`ZIP_07/INVENTORY.md` described an optional local ledger of purchased and
sold units. Resale tracking implies a sales channel, and no document in the
repository describes one.

### Decision

Inventory is in scope and owned by a dedicated Inventory Service. In the MVP
it tracks purchases only. Profit and resale are Phase 2. During the MVP,
resale information is entered manually through the Admin Dashboard.

### Alternatives Considered

*Engineering alternatives, per the note above.*

1. **Full inventory including automated resale from day one.** Rejected: no
   sales channel exists to integrate against.
2. **No inventory in the MVP.** Rejected: purchases already produce the data,
   and discarding it removes the basis for later profit analysis
   (`ZIP_09/PROFIT_PREDICTION.md`).

### Consequences

- `ZIP_09/PROFIT_PREDICTION.md` has no realised-profit input during the MVP,
  so it cannot be trained or evaluated yet.
- The Admin Dashboard becomes a required surface, though it is absent from
  the official service list (Q42).
- Inventory tables and entities do not yet exist (Q31).

### Future Improvements

- Integrate external sales channels in a later version.

---

## ADR Index

| ADR | Decision | Recorded in |
|---|---|---|
| ADR-001 | Event-driven architecture | `ZIP_01/DECISION_LOG.md` |
| ADR-002 | One connector per marketplace | `ZIP_01/DECISION_LOG.md` |
| ADR-003 | One purchase agent per marketplace | this file |
| ADR-004 | Deal revalidation before purchase | this file |
| ADR-005 | Platform preserved through lifecycle | this file |
| ADR-006 | Redis Streams as the canonical event bus | this file |
| ADR-007 | Dedicated Account Service | this file |
| ADR-008 | Dedicated Revalidation Service | this file |
| ADR-009 | Event-driven boundaries, no shared database reads | this file |
| ADR-010 | Event Store Consumer as sole writer | this file |
| ADR-011 | UUID primary keys, marketplace IDs as external references | this file |
| ADR-012 | Inventory limited to purchase tracking in the MVP | this file |
