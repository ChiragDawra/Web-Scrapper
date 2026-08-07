# Deal Intelligence Events

Event names follow the canonical catalog in
`ZIP_02/EVENT_DRIVEN_ARCHITECTURE.md`. Where this file and the catalog
disagree, the catalog wins.

Transport is Redis Streams. Every event is versioned, e.g. `DEAL_SCORED.v1`.

---

## Deal discovery chain

The Deal Engine owns the first three transitions only. It does not own
revalidation and it does not own purchasing.

```
DEAL_DETECTED
     |
     v
DEAL_SCORED
     |
     v
DEAL_NOTIFIED
```

Downstream, outside this package:

```
DEAL_NOTIFIED -> USER_INTERESTED -> DEAL_REVALIDATION_REQUEST
              -> DEAL_REVALIDATED -> PURCHASE_REQUESTED
```

`USER_INTERESTED` is produced by the Bot (`ZIP_06/EVENTS.md`).
`DEAL_REVALIDATION_REQUEST` and `DEAL_REVALIDATED` are produced by the
Revalidation Service, not by the Deal Engine.

> `DEAL_FOUND` is deprecated. It has been replaced by `DEAL_DETECTED`.

---

## Events produced by the Deal Engine

| Event | Emitted by | When |
|---|---|---|
| `DEAL_DETECTED` | Deal Detector | A listing satisfies the rule engine (`DEAL_DETECTOR.md`, `RULE_ENGINE.md`) |
| `DEAL_SCORED` | Deal Scoring | The 0-100 score is assigned (`DEAL_SCORING.md`) |
| `DEAL_NOTIFIED` | Notification Engine | Confidence >= 70 and the deal is published (`NOTIFICATION_ENGINE.md`) |
| `DEAL_EXPIRED` | Deal Lifecycle component | Any expiry trigger fires (see below) |

### DEAL_EXPIRED

The Deal Lifecycle component lives inside the Deal Engine and owns the
terminal expiry transition. A deal expires when **any one** of the following
occurs:

1. The scanner can no longer find the listing.
2. The configured TTL expires.
3. Live revalidation fails.

The Scheduler triggers periodic expiry scans but does not own the transition
(`SCHEDULER.md`).

A deal may move to `EXPIRED` from **any non-terminal state**, not only from
`REVALIDATED`. `EXPIRED` is terminal.
See `ZIP_02/STATE_DIAGRAMS.md` section 1.

---

## Events consumed by the Deal Engine

| Event | Consumed by | Purpose |
|---|---|---|
| `DEAL_DETECTED` | Deal Scoring | Trigger scoring |
| `DEAL_SCORED` | Notification Engine | Apply the confidence threshold |
| `DEAL_REVALIDATED` | Deal Lifecycle component | A failed revalidation is an expiry trigger |

---

## Not produced by this package

| Event | Owner |
|---|---|
| `USER_INTERESTED`, `PURCHASE_REQUESTED`, `PURCHASE_CANCELLED` | Telegram Bot |
| `DEAL_REVALIDATION_REQUEST`, `DEAL_REVALIDATED` | Revalidation Service |
| `ORDER_PLANNED`, `PURCHASE_TASK_CREATED` | Order Planner |
| `PURCHASE_COMPLETED`, `PURCHASE_FAILED` | Purchase Agents |

---

## Open points

1. No payload schema exists for `DEAL_DETECTED`, `DEAL_SCORED`,
   `DEAL_NOTIFIED` or `DEAL_EXPIRED` (Q18).
2. Whether a deal is rescored when its price changes while at `SCORED` or
   `NOTIFIED` is unspecified (Q34).
3. The TTL is stated as 24 hours in `ZIP_02/STATE_DIAGRAMS.md` but described
   as "configured" here. Whether it is fixed or per-marketplace is
   unspecified (Q36).
