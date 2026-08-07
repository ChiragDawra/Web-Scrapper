# Order System Event Flow

Event names follow the canonical catalog in
`ZIP_02/EVENT_DRIVEN_ARCHITECTURE.md`. Where this file and the catalog
disagree, the catalog wins.

Transport is Redis Streams. Every event is versioned, e.g. `ORDER_PLANNED.v1`.

---

## Main flow

```
PURCHASE_REQUESTED          (Telegram Bot)
        |
        v
ACCOUNT_ALLOCATION_REQUEST  (Order Planner -> Account Service)
        |
        v
ACCOUNT_ALLOCATION_RESPONSE (Account Service -> Order Planner)
        |
        v
ORDER_PLANNED               (Order Planner)
        |
        v
PURCHASE_TASK_CREATED       (Order Planner, one per allocated account)
        |
        v
PURCHASE_COMPLETED | PURCHASE_FAILED   (Purchase Agents)
```

`PURCHASE_CANCELLED` may arrive from the Bot before execution begins.

---

## Account allocation is event-driven

The Order Planner never reads the Account Service database. Availability is
obtained through a request/response pair:

| Event | Direction | Purpose |
|---|---|---|
| `ACCOUNT_ALLOCATION_REQUEST` | Planner to Account Service | Ask for eligible accounts for a marketplace and quantity |
| `ACCOUNT_ALLOCATION_RESPONSE` | Account Service to Planner | Return eligible accounts with health level and remaining limits |

There is no synchronous API exception for this path. This satisfies
`ZIP_02/SERVICE_CONTRACTS.md`.

Allocation priority applied by the Planner
(`ZIP_02/SERVICE_RESPONSIBILITIES.md` section 9):

1. `HEALTHY`
2. `WARNING`
3. `DISABLED` — never allocated

> **Conflict on record.** These two names are not in the thirteen-event
> canonical catalog. See open question Q35 in
> `ZIP_02/EVENT_DRIVEN_ARCHITECTURE.md`.

---

## Events produced by the Order Planner

| Event | When | Source |
|---|---|---|
| `ACCOUNT_ALLOCATION_REQUEST` | After validating the deal | `ORDER_PLANNER.md` |
| `ORDER_PLANNED` | An allocation satisfying the requested quantity was produced | `ORDER_PLANNER.md`, `OPTIMIZATION.md` |
| `PURCHASE_TASK_CREATED` | One per allocated account, published to that marketplace's queue | `PURCHASE_QUEUE.md` |

One `ORDER_PLANNED` fans out into N `PURCHASE_TASK_CREATED` events, where N
is the number of accounts the optimizer selected.

---

## Events consumed by the Order Planner

| Event | Purpose |
|---|---|
| `PURCHASE_REQUESTED` | Start planning (`ORDER_PLANNER.md`) |
| `ACCOUNT_ALLOCATION_RESPONSE` | Receive eligible accounts |
| `PURCHASE_COMPLETED` | Advance order state, record outcome (`ORDER_HISTORY.md`) |
| `PURCHASE_FAILED` | Advance order state, record outcome |
| `PURCHASE_CANCELLED` | Abandon planning before execution |
| `DEAL_EXPIRED` | Abort planning for an expired deal (`FAILURE_SCENARIOS.md`) |

---

## Order state and task outcomes

Task results roll up to the order state defined in
`ZIP_02/STATE_DIAGRAMS.md` section 2:

| Task outcomes | Order state |
|---|---|
| All tasks succeeded | `SUCCESS` |
| At least one succeeded **and** at least one failed | `PARTIAL` |
| All tasks failed | `FAILED` |
| Cancelled before execution | `CANCELLED` |

`PARTIAL` is a terminal state introduced specifically for the multi-account
allocation model. It exists because one order fans out across several
accounts and those tasks can disagree.

---

## Failure handling

- Transient planning failures are retried without duplicating successful
  allocations (`RETRY_LOGIC.md`).
- Unrecoverable planning events are routed to the dead letter queue for
  manual inspection (`DEAD_LETTER_QUEUE.md`).
- Consumers are idempotent (`ZIP_02/FAILURE_RECOVERY.md`).

---

## Open points

1. No payload schema exists for any event in this flow (Q18).
2. No timeout is defined for `ACCOUNT_ALLOCATION_RESPONSE`. If the Account
   Service does not answer, Planner behaviour is unspecified (Q38).
3. Whether a `PARTIAL` order triggers replanning of the failed portion, or
   terminates, is unspecified (Q39).
4. `ZIP_07/FAILURE_SCENARIOS.md` lists "insufficient accounts" as a scenario.
   Whether the Planner partially fulfils or rejects outright when eligible
   accounts cannot cover the requested quantity is unspecified (Q40).
