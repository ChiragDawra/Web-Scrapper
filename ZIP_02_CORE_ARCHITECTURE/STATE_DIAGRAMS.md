# State Diagrams

Canonical state machines. Where another document disagrees, this document
wins.

---

## 1. Deal Lifecycle

```
DETECTED
   |
   v
SCORED
   |
   v
NOTIFIED
   |
   v
INTERESTED
   |
   v
REVALIDATED
   |
   +----> ORDERED   (terminal, success)
   |
   +----> EXPIRED   (terminal, failure)
```

This supersedes the earlier `NEW -> SCORED -> ...` wording in this file and
the earlier `DETECTED -> NOTIFIED -> ...` wording in
`ZIP_03/DEAL_HISTORY.md`. The first state is `DETECTED`. `SCORED` is
included.

### SCORED is a persisted state

`SCORED` **must be persisted**, not treated as a transient step. Historical
scores are required for analytics and for future ML training
(`ZIP_09/DATASET_DESIGN.md`, `ZIP_09/DEAL_SCORING_MODEL.md`).

The corollary is that a deal that scores below the notification threshold
still exists in the database at `SCORED`. It is a negative training example.

### Transitions

| From | To | Trigger | Event emitted |
|---|---|---|---|
| — | `DETECTED` | Listing satisfies the rule engine (`ZIP_05/DEAL_DETECTOR.md`) | `DEAL_DETECTED` |
| `DETECTED` | `SCORED` | Scoring completes, 0-100 assigned (`ZIP_05/DEAL_SCORING.md`) | `DEAL_SCORED` |
| `SCORED` | `NOTIFIED` | Confidence >= 70 and deal published to user (`ZIP_05/NOTIFICATION_ENGINE.md`) | `DEAL_NOTIFIED` |
| `NOTIFIED` | `INTERESTED` | User taps Interested (`ZIP_06/BUTTONS.md`) | `USER_INTERESTED` |
| `INTERESTED` | `REVALIDATED` | Live listing refresh succeeds and the deal still holds (`ZIP_06/REVALIDATION_FLOW.md`) | `DEAL_REVALIDATED` |
| `REVALIDATED` | `ORDERED` | Purchase request accepted by the planner (`ZIP_07/ORDER_PLANNER.md`) | `PURCHASE_REQUESTED`, then `ORDER_PLANNED` |
| any non-terminal | `EXPIRED` | See expiry triggers below | `DEAL_EXPIRED` |

### Expiry triggers

A deal becomes `EXPIRED` if **any one** of the following occurs. Any single
trigger is sufficient.

1. The scanner no longer finds the listing.
2. Live revalidation fails.
3. No update is received within 24 hours (TTL).

**A deal may transition from any non-terminal state directly to `EXPIRED`.**
Expiry is not confined to the post-revalidation step: the scanner and TTL
triggers fire while a deal sits at `DETECTED`, `SCORED`, `NOTIFIED` or
`INTERESTED`. `EXPIRED` is terminal.

`DEAL_EXPIRED` is emitted by the Deal Lifecycle component inside the Deal
Engine (`ZIP_05/EVENTS.md`). The Scheduler triggers periodic expiry scans but
does not own the transition.

> **Undefined.** No document states what happens when a user taps Interested
> on a deal that has already expired, nor whether `ORDERED` is truly terminal
> given that a purchase can still fail afterwards. See open questions Q20 and
> Q21.

---

## 2. Order Lifecycle

```
REQUESTED
   |
   +----> CANCELLED   (terminal, user cancelled before execution)
   |
   v
PLANNED
   |
   +----> CANCELLED   (terminal, user cancelled before execution)
   |
   v
EXECUTING
   |
   +----> SUCCESS     (terminal, all tasks succeeded)
   |
   +----> PARTIAL     (terminal, some succeeded and some failed)
   |
   +----> FAILED      (terminal, all tasks failed)
```

`PARTIAL` and `CANCELLED` are new. `PARTIAL` exists because an order is
allocated across multiple accounts (`ZIP_07/OPTIMIZATION.md`) and those tasks
can disagree.

### Task rollup

| Task outcomes | Order state |
|---|---|
| All tasks succeeded | `SUCCESS` |
| At least one succeeded **and** at least one failed | `PARTIAL` |
| All tasks failed | `FAILED` |
| Cancelled before execution began | `CANCELLED` |

### Transitions

| From | To | Trigger | Event emitted |
|---|---|---|---|
| — | `REQUESTED` | User confirms quantity (`ZIP_06/ORDER_CONFIRMATION.md`) | `PURCHASE_REQUESTED` |
| `REQUESTED` | `PLANNED` | Planner allocates across accounts (`ZIP_07/ORDER_PLANNER.md`) | `ORDER_PLANNED`, then `PURCHASE_TASK_CREATED` per account |
| `PLANNED` | `EXECUTING` | A purchase agent picks up the task (`ZIP_08/EXECUTION_PIPELINE.md`) | — |
| `EXECUTING` | `SUCCESS` | Checkout completes | `PURCHASE_COMPLETED` |
| `EXECUTING` | `FAILED` | Execution fails unrecoverably (`ZIP_08/RECOVERY.md`) | `PURCHASE_FAILED` |
| `REQUESTED` or `PLANNED` | cancelled | User cancels before execution (`ZIP_06/EVENTS.md`) | `PURCHASE_CANCELLED` |

> **Undefined.** Whether a `PARTIAL` order triggers replanning of the failed
> portion or terminates as-is is unspecified. See open question Q39.

> **Undefined.** Whether the Planner partially fulfils or rejects outright
> when eligible accounts cannot cover the requested quantity is unspecified.
> See open question Q40.

---

## 3. Bot Conversation State

From `ZIP_06/STATES.md` and `ZIP_06/STATE_MACHINE.md`.

```
IDLE
  |  deal notification arrives
  v
DEAL_SENT
  |  user taps Interested
  v
INTERESTED
  |  live refresh begins
  v
REVALIDATING
  |
  +--- refresh shows deal changed or expired ---> DEAL_SENT (updated card)
  |
  |  refresh confirms deal
  v
WAITING_QUANTITY
  |  user sends a valid quantity
  v
CONFIRMING
  |
  +--- user cancels ---> CANCELLED (terminal)
  |
  |  user confirms
  v
COMPLETED (terminal)
```

`Ignore` and `Watch Later` (`ZIP_06/BUTTONS.md`) are offered at `DEAL_SENT`.

> **Undefined.** No document states which state `Ignore` or `Watch Later`
> transitions to, nor whether `Watch Later` re-enters the flow later. No
> timeouts are defined for `WAITING_QUANTITY` or `CONFIRMING`. See open
> question Q24.

---

## 4. Account Health State

Owned by the Account Service. Levels:

```
score > 80        -> HEALTHY
50 <= score <= 80 -> WARNING
score < 50        -> DISABLED
```

Score starts at 100. Adjustments:

| Event | Delta |
|---|---|
| Login failure | −20 |
| CAPTCHA | −10 |
| Verification required | −40 |
| Successful purchase | +2 |
| Cooldown completed | +5 |

### Bounds

The score is clamped to the range **0-100**. Maximum 100, minimum 0. Positive
adjustments above 100 and negative adjustments below 0 are discarded.

### Allocation priority

The Order Planner allocates in this order
(`ZIP_07/EVENT_FLOW.md`):

1. `HEALTHY`
2. `WARNING`
3. `DISABLED` — **never allocated**

`WARNING` accounts are eligible but rank below `HEALTHY`.

### DISABLED is recoverable

`DISABLED` is not terminal. An account returns to service through any of:

- Successful login
- Cooldown completion
- Manual administrator re-enable

```
HEALTHY  <--->  WARNING  <--->  DISABLED
   (score crossings)         (recovery paths above)
```

> **Undefined.** Recovery is described by trigger, not by resulting score. A
> disabled account at score 10 that logs in successfully — does it jump to a
> fixed score, gain a fixed delta, or reset to 100? The three recovery
> methods have no score effect attached. See open question Q41.

> **Undefined.** Manual administrator re-enable implies an admin surface.
> The Admin Dashboard is referenced in the Inventory decision but is absent
> from the official service list. See open question Q42.
