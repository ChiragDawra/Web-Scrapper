# State Transitions

Every state machine in the system: states, edges, guards, timeouts, and what
fires on each edge. Resolves the ORDERED/PARTIAL/PLANNING_FAILED ambiguity
flagged across ZIP_05/06/07, and the Bot conversation state gap (Q55).

---

## 1. Deal lifecycle (`deals.status`)

```
SCORED --(notification worker picks up)--> NOTIFIED --(sent to Telegram)--> DEAL_SENT
DEAL_SENT --(user taps Interested)--> INTERESTED
DEAL_SENT --(user taps Ignore)-------> IGNORED [terminal]
DEAL_SENT --(user taps Watch Later)--> WATCHING
DEAL_SENT --(expires_at reached, no action)--> EXPIRED [terminal]

WATCHING --(price drops further OR 24h elapsed, re-notify)--> DEAL_SENT
WATCHING --(expires_at reached)--> EXPIRED [terminal]

INTERESTED --(Bot emits DEAL_REVALIDATION_REQUEST)--> REVALIDATING
REVALIDATING --(DEAL_REVALIDATED: price within tolerance, in stock)--> CONFIRMED
REVALIDATING --(DEAL_REVALIDATED: price outside tolerance)--> PRICE_CHANGED
REVALIDATING --(DEAL_REVALIDATED: out of stock)--> SOLD_OUT
REVALIDATING --(timeout 30s, no response)--> PRICE_CHANGED  -- fail safe: treat as changed, force re-confirmation

PRICE_CHANGED --(user re-confirms at new price)--> REVALIDATING  -- one more round-trip only, see guard below
PRICE_CHANGED --(user declines)--> PRICE_CHANGED_REJECTED [terminal]
SOLD_OUT --(user acknowledges)--> SOLD_OUT_REJECTED [terminal]

CONFIRMED --(user confirms quantity, Bot emits PURCHASE_REQUESTED)--> ORDERED [terminal]
```

### Guards

- **Tolerance for "changed" (resolves the revalidation ambiguity):** price
  delta > 2% in either direction, OR any change in `in_stock`, counts as
  changed. Below 2% is treated as unchanged and goes straight to
  `CONFIRMED`.
- **Re-confirmation loop cap:** `PRICE_CHANGED -> REVALIDATING` may happen at
  most once per deal. A second price change after re-confirmation forces
  `PRICE_CHANGED_REJECTED` automatically — no infinite haggling loop.
- **No in-place rescoring.** A deal's `score` and `score_breakdown` are
  computed once at `SCORED` and never recomputed. Later price ticks on the
  same listing do not touch this row; they are compared only during
  `REVALIDATING`. If the deal has already reached a terminal state, a new
  qualifying price on the same listing produces a *new* `deals` row (subject
  to the one-open-deal-per-listing dedup rule in `DATABASE_SCHEMA.md` §6).
- **Tap-after-expiry:** if a user taps Interested on a `DEAL_SENT` message
  whose deal has since moved to `EXPIRED`, the Bot answers the callback with
  an "this deal has expired" edit to the message and does **not** emit
  `USER_INTERESTED`. No state transition occurs.

### Relationship to Order outcome (resolves the ORDERED-vs-PARTIAL conflict)

`ORDERED` means only "the user approved and a purchase order was created."
It is intentionally terminal at the deal level and does **not** track
whether the purchase itself succeeded, partially succeeded, or failed — that
is tracked on the `orders` row (§2), which the deal references via
`orders.deal_id`. The Bot subscribes to `PURCHASE_COMPLETED` /
`PURCHASE_FAILED` independently of deal state to inform the user of the
actual outcome. This is deliberate: re-opening a deal because its order
later failed would corrupt the "user acted" signal ML depends on
(`ZIP_09/DATASET_DESIGN.md`).

---

## 2. Order lifecycle (`orders.status`)

```
REQUESTED --(Order Planner receives PURCHASE_REQUESTED, requests allocation)--> [allocating]
[allocating] --(zero eligible accounts returned)--> PLANNING_FAILED [terminal]
[allocating] --(>=1 account allocated, may be < requested_quantity)--> PLANNED
PLANNED --(PURCHASE_TASK_CREATED emitted for each allocated account)--> EXECUTING
EXECUTING --(all purchase_tasks COMPLETED, fulfilled_quantity == requested_quantity)--> COMPLETED [terminal]
EXECUTING --(all purchase_tasks resolved, 0 < fulfilled_quantity < requested_quantity)--> PARTIAL [terminal]
EXECUTING --(all purchase_tasks FAILED, fulfilled_quantity == 0)--> FAILED [terminal]
REQUESTED --(user cancels before allocation completes)--> CANCELLED [terminal]
```

### Guards

- **Partial allocation is allowed at planning time.** If fewer accounts are
  eligible than `requested_quantity` needs, the Planner allocates as many as
  are available (down to a minimum of 1 unit) and proceeds — it does not
  block waiting for capacity. Only zero eligible accounts causes
  `PLANNING_FAILED`.
- **`PARTIAL` is terminal, not retried automatically.** The user is notified
  with the itemized outcome (`X of Y units purchased`) and may manually
  trigger a new order for the shortfall by re-approving the deal (if still
  active) — this creates a brand-new `orders` row, never resurrects the old
  one.
- **`total_amount`** is set once at `PLANNED` (sum of allocated
  `order_items.unit_price * quantity`) and is not recalculated afterward,
  even if individual tasks fail — `fulfilled_quantity` and per-task status
  carry the actual outcome.

---

## 3. Account health (`accounts.status`, `accounts.health_score`)

```
ACTIVE (health_score 80-100) <-> WARNING (health_score 40-79)
WARNING --(health_score drops to 1-39)--> [CRITICAL band, status stays WARNING]
Any --(health_score reaches 0)--> BANNED [terminal, requires manual action]
ACTIVE/WARNING --(marketplace returns CAPTCHA/soft-block signal)--> COOLDOWN
COOLDOWN --(cooldown_until elapsed)--> WARNING  -- always re-enters at WARNING, never straight to ACTIVE
Any (except BANNED) --(admin disables via dashboard)--> DISABLED_MANUAL
DISABLED_MANUAL --(admin re-enables via dashboard)--> ACTIVE, health_score reset to 100
BANNED --(admin manually confirms unban)--> DISABLED_MANUAL  -- always requires a human review step before reuse
```

### Health score deltas (applied by Account Service on each purchase-task outcome)

| Event | Delta |
|---|---|
| `PURCHASE_COMPLETED` (this account) | +2 |
| `PURCHASE_FAILED`, generic failure | -20 |
| `PURCHASE_FAILED`, reason = CAPTCHA challenge | -10 |
| `PURCHASE_FAILED`, reason = account suspended/banned signal from marketplace | -40 |
| Successful login / session refresh | no change (not a purchase signal) |
| Cooldown period completes | +20 (applied on `COOLDOWN -> WARNING` transition) |
| Manual re-enable via Admin Dashboard | reset to 100 |

### Guards

- `daily_spend_used` resets to 0 by a scheduled job at 00:00 IST; this is
  independent of `health_score`.
- An account with `status IN ('COOLDOWN','SUSPENDED','BANNED','DISABLED_MANUAL')`
  is never returned by the Account Service's allocation query
  (`ACCOUNT_ALLOCATION_REQUEST` handler) — resolves ambiguity about whether
  cooldown accounts are silently skipped (yes, always).

---

## 4. Bot conversation state (`bot_conversations.state`) — resolves Q55

```
IDLE --(deal card sent, no action yet)--> IDLE  -- IDLE covers "no open interaction", deal cards don't change state
IDLE --(user taps Interested, revalidation confirmed)--> AWAITING_QUANTITY
AWAITING_QUANTITY --(user sends a quantity)--> AWAITING_CONFIRMATION
AWAITING_QUANTITY --(timeout 10 min)--> IDLE  -- deal reverts to CONFIRMED, user must re-tap to resume
AWAITING_CONFIRMATION --(user confirms)--> IDLE  -- PURCHASE_REQUESTED emitted on this edge
AWAITING_CONFIRMATION --(user cancels)--> IDLE
AWAITING_CONFIRMATION --(timeout 5 min)--> IDLE  -- order not created
IDLE --(admin flow needs free-text input, e.g. resale price entry)--> AWAITING_ADMIN_INPUT
AWAITING_ADMIN_INPUT --(input received or /cancel)--> IDLE
```

### Guards

- One `bot_conversations` row per `telegram_user_id` (PK), so a user has at
  most one open interaction at a time. A second Interested tap while
  `state != IDLE` is rejected with "finish your current action first,"
  answered as a callback toast, no state change.
- `pending_action` JSONB carries the minimal context needed to resume (deal
  id, prompt type); it is cleared (`NULL`) on every transition back to
  `IDLE`.
- Timeouts are enforced by a scheduled sweep (every 60s) comparing
  `state_entered_at` against the thresholds above, not by per-user timers.

---

## 5. Purchase task lifecycle (`purchase_tasks.status`)

```
CREATED --(assigned to a Purchase Agent worker)--> ASSIGNED
ASSIGNED --(agent starts checkout automation)--> EXECUTING
EXECUTING --(checkout succeeds)--> COMPLETED [terminal]
EXECUTING --(checkout fails, attempt_count < 3)--> RETRYING
RETRYING --(backoff elapsed, attempt_count += 1)--> EXECUTING
EXECUTING --(checkout fails, attempt_count == 3)--> FAILED [terminal]
Any non-terminal --(unrecoverable error: account banned mid-task, listing removed)--> DEAD_LETTERED [terminal]
```

Retry policy: exponential backoff, base 2s, multiplier 2, max 5 attempts
before `DEAD_LETTERED` supersedes `FAILED` for infra-level errors (network,
timeout); business-level failures (price mismatch at checkout, out of stock)
go straight to `FAILED` without exhausting retries — see
`ERROR_CODES.md` for the classification each error code maps to.
