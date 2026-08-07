# Decision Log

Foundation ADRs. ADR-003 onward are recorded in
`ZIP_02/ARCHITECTURE_DECISIONS.md`, which also holds the full index.

Every ADR uses the same structure: Context, Decision, Alternatives
Considered, Consequences, Future Improvements.

> **On the Alternatives sections.** The original discussions that produced
> these decisions are not recorded anywhere in this repository. The
> alternatives below are **engineering alternatives considered during
> architecture finalization**, reconstructed from the technical shape of each
> decision. They are not a historical record of what was debated, and no
> business motivation has been attributed to anyone.

---

## ADR-001: Event-Driven Architecture

### Context

The system spans discovery, scoring, user approval, planning and execution.
These stages run at different rates and fail independently: a scan is
continuous and cheap, a purchase is rare, slow and expensive. A user may act
on a notification hours after it was produced.

Several services also need the same facts for different purposes. A completed
purchase matters to order history, to inventory, to account health and to ML
dataset building at the same time.

### Decision

Services communicate asynchronously through events. All communication uses
versioned event payloads, and no service reads another service's database
(`ZIP_02/SERVICE_CONTRACTS.md`). Synchronous APIs are reserved for dashboard
and admin use (`ZIP_02/SERVICE_COMMUNICATION.md`).

### Alternatives Considered

*Engineering alternatives, per the note above.*

1. **Synchronous service-to-service calls.** Simpler to trace and reason
   about, with immediate error propagation. Rejected: it couples availability
   across the whole chain, so a slow marketplace connector would stall
   scanning, scoring and notification behind it.
2. **A single monolithic service with internal function calls.** Fastest to
   build and no serialization. Rejected: browser automation for purchasing
   has resource and failure characteristics nothing else in the system
   shares, and it would sit in the same process as scanning.
3. **A shared database as the integration point.** Rejected: it makes every
   schema change a cross-service change and provides no natural fan-out.

### Consequences

- Fan-out is free. New consumers attach to existing events without changing
  producers.
- Every consumer must be idempotent, and failures need dead-lettering
  (`ZIP_02/FAILURE_RECOVERY.md`).
- Debugging requires correlation IDs, because no single call stack spans a
  workflow (`ZIP_10/LOGGING.md`).
- Eventual consistency is the default, so the Bot must model waiting states
  explicitly (`ZIP_06/STATES.md`).
- An event catalog becomes a contract that must be governed
  (`ZIP_02/EVENT_DRIVEN_ARCHITECTURE.md`).

### Future Improvements

- Payload schemas for all thirteen events, which do not yet exist (Q18).
- A defined idempotency key per consumer (Q17).

---

## ADR-002: One Connector Per Marketplace

### Context

Four marketplaces are supported. Each exposes data differently, authenticates
differently, and structures products differently. Downstream services should
not need to know which marketplace a product came from
(`ZIP_04/DATA_SOURCE_STRATEGY.md`).

### Decision

Each marketplace gets its own connector. Every connector implements the same
interface — `fetch_products()`, `fetch_listing()`, `refresh_listing()`,
`normalize()` — and is responsible for converting marketplace-specific fields
into the canonical product model
(`ZIP_04/CONNECTOR_INTERFACE.md`, `ZIP_04/COMMON_NORMALIZATION.md`).

### Alternatives Considered

*Engineering alternatives, per the note above.*

1. **A single configurable connector driven by per-marketplace config.**
   Attractive while the marketplaces look similar. Rejected: authentication,
   pagination and error semantics differ enough that the configuration
   language would become a programming language.
2. **Normalization downstream instead of in the connector.** Would keep
   connectors thin. Rejected: it pushes marketplace-specific knowledge into
   the Deal Engine, which is exactly what the canonical model exists to
   prevent.

### Consequences

- Four connectors to build and maintain against independently changing
  sources.
- Adding a marketplace is additive and touches no existing connector.
- The canonical product model becomes load-bearing: every connector must
  produce it, so it must cover every marketplace's fields.
- Shared concerns — retry, backoff, error classification — are documented
  once and applied per connector
  (`ZIP_04/COMMON_RETRY_STRATEGY.md`, `ZIP_04/COMMON_ERROR_HANDLING.md`).

### Future Improvements

- The canonical product model has no field list, which blocks every
  connector's `normalize()` (Q49).
- Connector methods have no signatures, parameters, return types or
  pagination contract (Q50).
- Ratings and review count are now scoring inputs
  (`ZIP_05/DEAL_SCORING.md`) but are not in the connector interface (Q44).

---

## Index

| ADR | Decision | Recorded in |
|---|---|---|
| ADR-001 | Event-driven architecture | this file |
| ADR-002 | One connector per marketplace | this file |
| ADR-003 | One purchase agent per marketplace | `ZIP_02/ARCHITECTURE_DECISIONS.md` |
| ADR-004 | Deal revalidation before purchase | `ZIP_02/ARCHITECTURE_DECISIONS.md` |
| ADR-005 | Platform preserved through lifecycle | `ZIP_02/ARCHITECTURE_DECISIONS.md` |
| ADR-006 | Redis Streams as the canonical event bus | `ZIP_02/ARCHITECTURE_DECISIONS.md` |
| ADR-007 | Dedicated Account Service | `ZIP_02/ARCHITECTURE_DECISIONS.md` |
| ADR-008 | Dedicated Revalidation Service | `ZIP_02/ARCHITECTURE_DECISIONS.md` |
| ADR-009 | Event-driven boundaries, no shared database reads | `ZIP_02/ARCHITECTURE_DECISIONS.md` |
| ADR-010 | Event Store Consumer as sole writer | `ZIP_02/ARCHITECTURE_DECISIONS.md` |
| ADR-011 | UUID primary keys, marketplace IDs as external references | `ZIP_02/ARCHITECTURE_DECISIONS.md` |
| ADR-012 | Inventory limited to purchase tracking in the MVP | `ZIP_02/ARCHITECTURE_DECISIONS.md` |
