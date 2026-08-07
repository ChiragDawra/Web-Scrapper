# Dependency Graph

Maps service dependencies and required reading order.

Every relationship below is derived from an existing document in this
repository. The source is cited so any claim can be verified. Nothing here
introduces architecture that is not already stated elsewhere.

---

## 1. Required Reading Order (ZIP chain)

Declared by the `NEXT_ZIP.md` file in each package. The chain is linear:
each ZIP has exactly one declared successor.

```
ZIP_01 FOUNDATION
  -> ZIP_02 CORE_ARCHITECTURE      (ZIP_01/NEXT_ZIP.md)
  -> ZIP_03 DATABASE               (ZIP_02/NEXT_ZIP.md)
  -> ZIP_04 MARKETPLACE_LAYER      (ZIP_03/NEXT_ZIP.md)
  -> ZIP_05 DEAL_INTELLIGENCE      (ZIP_04/NEXT_ZIP.md)
  -> ZIP_06 BOT_SYSTEM             (ZIP_05/NEXT_ZIP.md)
  -> ZIP_07 ORDER_SYSTEM           (ZIP_06/NEXT_ZIP.md)
  -> ZIP_08 PURCHASE_AGENTS        (ZIP_07/NEXT_ZIP.md)
  -> ZIP_09 AI_ML                  (ZIP_08/NEXT_ZIP.md)
  -> ZIP_10 INFRASTRUCTURE         (ZIP_09/NEXT_ZIP.md)
  -> ZIP_11 TESTING                (ZIP_10/NEXT_ZIP.md)
  -> ZIP_12 AI_ENGINEERING_SYSTEM  (ZIP_11/NEXT_ZIP.md)
```

### Minimum reading set before coding any module

`ZIP_12/ARCHITECTURE_REFERENCES.md` requires Foundation, Core Architecture,
Database, and the relevant module docs before writing code.
`ZIP_12/BOOT_SEQUENCE.md` places `CURRENT_STATE` first in that order:

```
1. CURRENT_STATE (ZIP_12/CURRENT_STATE.md, plus the per-ZIP CURRENT_STATE.json)
2. Architecture   (ZIP_02)
3. Target module docs
4. Plan -> 5. Code -> 6. Test -> 7. Update CURRENT_STATE
```

`ZIP_12/SESSION_RECOVERY.md` adds `CHANGELOG` to the resume path.

---

## 2. Runtime Service Dependency Graph

Node set from `ZIP_02/SYSTEM_DESIGN.md`:
Marketplace Connectors, Deal Engine, Bot, Order Planner, Purchase Agents,
AI Services, Infrastructure. API Gateway is defined in
`ZIP_02/API_GATEWAY.md`.

```
                  External Marketplaces
        Amazon | Flipkart | Myntra | Nykaa
                (ZIP_04/*.md, ZIP_08/*.md)
                  ^                  ^
          read    |                  |  checkout
                  |                  |
        +---------+---------+        |
        | Marketplace       |        |
        | Connectors (x4)   |        |
        | ZIP_04            |        |
        +----+---------^----+        |
             |         |             |
             |         | live refresh|
             v         |             |
        +----------+   |             |
        | Scanner  |   |             |
        | Engine + |   |             |
        | Scheduler|   |             |
        | ZIP_05   |   |             |
        +----+-----+   |             |
             |         |             |
             v         |             |
        +--------------+--------+    |
        | Deal Engine  ZIP_05   |    |
        +----+------------------+    |
             |                       |
             v                       |
        +-----------+                |
        | Bot ZIP_06| <---> User     |
        +----+------+                |
             |                       |
             v                       |
        +--------------+             |
        | Order Planner|             |
        | ZIP_07       |             |
        +----+---------+             |
             |                       |
             v                       |
        +----------------------+     |
        | Purchase Agents (x4) |-----+
        | ZIP_08               |
        +----+-----------------+
             |
             v
        +---------------+     +------------------+
        | Event Store / |---->| AI/ML Services   |
        | Order History |     | ZIP_09           |
        | ZIP_03,ZIP_07 |     +--------+---------+
        +---------------+              |
                                       | scores (future)
                                       v
                                  Deal Engine

Cross-cutting: API Gateway (ZIP_02/API_GATEWAY.md)
               PostgreSQL, Redis, Kafka (optional), Nginx, Docker (ZIP_10)
```

### Edge list with sources

| From | To | Nature | Source |
|---|---|---|---|
| Scheduler | Scanner Engine | assigns scan frequency by priority | `ZIP_05/SCHEDULER.md` |
| Scanner Engine | Connectors | collects listings through connectors | `ZIP_05/SCANNER_ENGINE.md` |
| Connectors | Marketplaces | retrieval, method abstracted | `ZIP_04/DATA_SOURCE_STRATEGY.md` |
| Scanner Engine | Deal Engine | emits normalized products | `ZIP_05/SCANNER_ENGINE.md` |
| Deal Engine | Bot | publishes notification for high-confidence deals | `ZIP_05/NOTIFICATION_ENGINE.md`, `ZIP_06/EVENTS.md` |
| Bot | Connectors | live listing refresh before quantity | `ZIP_06/LIVE_PRICE_REFRESH.md`, `ZIP_06/INTERESTED_FLOW.md` |
| Bot | Order Planner | publishes purchase request | `ZIP_06/QUANTITY_COLLECTION.md`, `ZIP_07/ORDER_PLANNER.md` |
| Order Planner | accounts data | allocation by limits, cooldowns, availability, health | `ZIP_07/ACCOUNT_ALLOCATION.md` |
| Order Planner | Purchase Queues | publishes planned tasks to per-marketplace queues | `ZIP_07/PURCHASE_QUEUE.md` |
| Purchase Queues | Purchase Agents | one agent consumes one marketplace only | `ZIP_07/MARKETPLACE_ROUTING.md`, `ZIP_08/*_PURCHASE_AGENT.md` |
| Purchase Agents | Marketplaces | executes checkout workflow | `ZIP_08/EXECUTION_PIPELINE.md` |
| Purchase Agents | Order History / Event Store | result events, audit trail | `ZIP_07/ORDER_HISTORY.md`, `ZIP_03/EVENT_STORE.md` |
| Order/Deal data | AI/ML | datasets from deals, user actions, orders, outcomes | `ZIP_09/DATASET_DESIGN.md` |
| AI/ML Inference | Deal Engine | ML ranking replaces rules over time | `ZIP_05/DEAL_SCORING.md`, `ZIP_09/DEAL_SCORING_MODEL.md` |

### Routing constraint

Platform identity is immutable across the lifecycle
(`ZIP_02/ARCHITECTURE_DECISIONS.md` ADR-005). An Amazon deal routes only to
the Amazon Purchase Agent, and the same holds for every other marketplace
(`ZIP_07/MARKETPLACE_ROUTING.md`). There is no cross-marketplace edge in the
purchase path.

---

## 3. Communication Dependency

`ZIP_02/SERVICE_COMMUNICATION.md`: services communicate through async events
on Redis Streams or Kafka. Synchronous APIs are reserved for dashboard and
admin use only.

`ZIP_02/SERVICE_CONTRACTS.md`: all services communicate through versioned
event payloads, and no service reads another service's database directly.
Therefore every runtime edge above is an event-bus edge unless it is a
dashboard or admin call.

**Resolved: Redis Streams is the canonical event bus. Kafka is not part of
the MVP.** Migration triggers are listed in
`ZIP_02/EVENT_DRIVEN_ARCHITECTURE.md` section 1.

Every runtime edge in section 2 is therefore a Redis Streams edge, except
dashboard and admin calls.

---

## 4. Infrastructure Dependency

From `ZIP_10`:

| Component | Depended on by | Source |
|---|---|---|
| PostgreSQL | all services needing persistence | `ZIP_10/POSTGRESQL.md`, `ZIP_03/POSTGRESQL_SCHEMA.md` |
| Redis | cache, queues, locks, session state | `ZIP_10/REDIS.md`, `ZIP_02/REDIS.md`, `ZIP_03/REDIS_SCHEMA.md` |
| Kafka (optional) | production event bus | `ZIP_10/KAFKA.md` |
| Nginx | reverse proxy, TLS, routing, rate limiting | `ZIP_10/NGINX.md` |
| Docker | per-service containers, multi-stage, health checks | `ZIP_10/DOCKER.md` |
| FastAPI | API Gateway, Deal Engine, Inference | `ZIP_10/FASTAPI.md` |
| Playwright | Purchase Agents only | `ZIP_08/PLAYWRIGHT_ARCHITECTURE.md` |
| Alembic | schema migrations | `ZIP_03/MIGRATIONS.md` |

`ZIP_10/DOCKER_COMPOSE.md` defines the local development stack as
PostgreSQL, Redis, API, Bot, and optional Kafka.

---

## 5. Milestone Dependency

`ZIP_12/MILESTONES.md` sequence, mapped to the ZIPs that define each:

| Milestone | Defining ZIP(s) |
|---|---|
| M1 Foundation | ZIP_01, ZIP_02, ZIP_03 |
| M2 Connectors | ZIP_04 |
| M3 Deal Engine | ZIP_05 |
| M4 Bot | ZIP_06 |
| M5 Planner | ZIP_07 |
| M6 Purchase | ZIP_08 |
| M7 ML | ZIP_09 |
| M8 Production | ZIP_10, ZIP_11 |

ZIP_12 is not a milestone; it governs how work on M1-M8 is carried out
(`ZIP_12/README.md`).

---

## 6. Known Gaps in This Graph

These are recorded rather than resolved, because resolving them would mean
inventing architecture that no document states.

1. ~~Event bus technology is undecided.~~ **Resolved:** Redis Streams
   (section 3).
2. ~~Event names disagree across packages.~~ **Resolved:** the canonical
   twelve-event catalog is in `ZIP_02/EVENT_DRIVEN_ARCHITECTURE.md`
   section 2. `ZIP_05/EVENTS.md`, `ZIP_06/EVENTS.md` and
   `ZIP_07/EVENT_FLOW.md` still carry the old names and need correcting.
3. **Three services are missing from the graph in section 2:** the Account
   Service, the Inventory Service and the Event Store Consumer, all added in
   `ZIP_02/SERVICE_RESPONSIBILITIES.md` sections 9-11. The runtime graph
   above predates them and is being updated.
4. Revalidation is event-driven, but no document names the service that
   performs the connector call and emits `DEAL_REVALIDATED`. The Bot edge to
   Connectors in section 2 may therefore be wrong.
5. The AI/ML inference edge back into the Deal Engine is described as a
   future phase (`ZIP_09/ML_ROADMAP.md` Phase 3). Its trigger point and
   fallback behaviour are not specified beyond "fallbacks"
   (`ZIP_09/INFERENCE_SERVICE.md`).
