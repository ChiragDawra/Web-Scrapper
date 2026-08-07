# Complete System Design

Canonical service list and system-level principles. Where another document
disagrees, this document wins.

---

## Official Service List

Eleven services.

| # | Service | Owns | Detail |
|---|---|---|---|
| 1 | Marketplace Connectors | Ingestion and normalization, one per marketplace | `ZIP_04` |
| 2 | Deal Engine | Discovery, scoring, notification, deal lifecycle | `ZIP_05` |
| 3 | Revalidation Service | Live listing refresh before purchase | `SERVICE_RESPONSIBILITIES.md` |
| 4 | Telegram Bot | User interaction, human approval gate | `ZIP_06` |
| 5 | Order Planner | Allocation and planning | `ZIP_07` |
| 6 | Account Service | Marketplace accounts, health, cooldowns, limits, rotation | `SERVICE_RESPONSIBILITIES.md` |
| 7 | Inventory Service | Purchase tracking (MVP), profit and resale (Phase 2) | ADR-012 |
| 8 | Purchase Agents | Marketplace-specific checkout execution, one per marketplace | `ZIP_08` |
| 9 | Event Store Consumer | Sole writer of the `events` table | ADR-010 |
| 10 | API Gateway | REST entry, authentication, rate limiting, routing | `API_GATEWAY.md` |
| 11 | ML Service | Training, model registry, inference | `ZIP_09` |

Infrastructure — PostgreSQL, Redis, Nginx, Docker — is not a service. It is
the runtime the services sit on (`ZIP_10`).

### Changes from the previous list

- `Bot` is now `Telegram Bot`.
- `AI Services` is now `ML Service`, singular.
- `Infrastructure` removed from the service list; it is a runtime layer.
- Added: Revalidation Service, Account Service, Inventory Service, Event
  Store Consumer, API Gateway.

---

## Service Topology

```
   Marketplace Connectors (x4)
        |            ^
        v            |
   Deal Engine       |  DEAL_REVALIDATION_REQUEST
        |            |
        | DEAL_NOTIFIED
        v            |
   Telegram Bot      |
        |            |
        | USER_INTERESTED
        v            |
   Revalidation Service
        |
        | DEAL_REVALIDATED -> Telegram Bot
        |
   Telegram Bot --PURCHASE_REQUESTED--> Order Planner
                                             |
                          ACCOUNT_ALLOCATION_REQUEST
                                             v
                                      Account Service
                                             |
                          ACCOUNT_ALLOCATION_RESPONSE
                                             v
                                        Order Planner
                                             |
                              PURCHASE_TASK_CREATED
                                             v
                                   Purchase Agents (x4)
                                             |
                        PURCHASE_COMPLETED | PURCHASE_FAILED
                                             |
                     +-----------------------+------------------+
                     v                       v                  v
              Inventory Service        Account Service     ML Service

   Every event above is also consumed by the Event Store Consumer,
   which is the only writer of the events table.

   API Gateway sits in front for dashboard and admin traffic only.
```

Full edge list with sources: `ZIP_12/DEPENDENCY_GRAPH.md`.

---

## Principles

### Event-driven

All inter-service communication is asynchronous over Redis Streams, using
versioned event payloads. No service reads another service's database
(ADR-001, ADR-006, ADR-009). Synchronous APIs are reserved for dashboard and
admin.

### Modular

One responsibility per service, with explicit boundaries recorded in
`SERVICE_RESPONSIBILITIES.md`. One connector per marketplace (ADR-002) and
one purchase agent per marketplace (ADR-003).

### Human-in-the-loop purchasing

No purchase happens without explicit human approval
(`ZIP_01/PROJECT_PHILOSOPHY.md`). The approval is enforced twice: at the Bot
confirmation step (`ZIP_06/ORDER_CONFIRMATION.md`), and again at execution
time, where agents refuse to act without upstream confirmation and fresh deal
validation (`ZIP_08/SAFETY_GUARDS.md`).

What the user approves is what gets bought — this is what ADR-004
(revalidation) and ADR-005 (immutable platform) exist to guarantee.

### Immutable history

Prices are stored as snapshots rather than overwritten
(`ZIP_03/PRICE_HISTORY_DESIGN.md`). Scored deals are persisted even when
never notified. Business events are persisted for replay and audit
(ADR-010). The system is designed so that history is never lost, because ML
depends on it (`ZIP_09/DATASET_DESIGN.md`).

---

## Open Points

1. **Scanner Engine and Scheduler are not in the service list (Q51).** Both
   are documented as distinct components (`ZIP_05/SCANNER_ENGINE.md`,
   `ZIP_05/SCHEDULER.md`) and the Scheduler is explicitly given work —
   triggering periodic expiry scans. Whether they are internal components of
   the Deal Engine or separate services is unstated.
2. **Admin Dashboard is not in the service list (Q42).** It is required for
   manual resale entry (ADR-012) and for manual account re-enable
   (`STATE_DIAGRAMS.md` section 4).
3. **ML Service internal split (Q52).** `ZIP_09` describes a training
   pipeline, a model registry and an inference API. Whether these are one
   deployable service or three is unstated. `ZIP_10/FASTAPI.md` names
   Inference as a separate FastAPI service.
4. **No service owns the canonical product model (Q49).** Connectors produce
   it, the Deal Engine consumes it, and no document defines its fields.
