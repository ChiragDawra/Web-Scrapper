# Validation Rules

Field-level and cross-field validation, applied at the boundary where data
enters the system (API Gateway request, event publish, connector
`normalize()` output) — never re-validated deeper in the pipeline. A
service downstream of a validated boundary trusts the shape.

Failures produce `VALID_*` codes (`ERROR_CODES.md`) in `ErrorResponse.details`
(`DTOS.md` §2), keyed by field path.

---

## 1. CanonicalProduct (enforced in each Connector's `normalize()`)

| Field | Rule |
|---|---|
| `canonical_title` | required, 1-500 chars, trimmed, non-empty after trim |
| `price` | required, integer, > 0 |
| `mrp` | nullable, integer, if present must be >= `price` |
| `marketplace` | required, must be a valid `marketplace_code` |
| `external_listing_id` | required, non-empty, unique per marketplace (dedup key) |
| `url` | required, valid URL, host must match the marketplace's known domain(s) |
| `rating` | nullable, if present 0.0-5.0 |
| `review_count` | nullable, if present >= 0 |
| `in_stock` | required, boolean — connectors must not omit; infer `false` if the response gives no positive stock signal, never leave null |

A product failing any required-field rule is dropped (`CONN_PARSE_FAILED`),
not partially emitted.

---

## 2. Deal scoring input (Deal Engine)

| Field | Rule |
|---|---|
| `discount_pct` | computed as `(mrp - price) / mrp`; deals below the configured minimum threshold (from `/scoring-config`) are not scored — no `ScoredDeal` emitted, not an error |
| `score` | must resolve to 0-100; a `score_breakdown` component producing a value outside its own weighted range is a scoring-config bug, not a validation failure — fix the config, not the input |

---

## 3. Quantity input (Bot, `AWAITING_QUANTITY` state)

| Field | Rule |
|---|---|
| `quantity` | required, positive integer, 1-10 (hard cap, MVP anti-abuse limit) |
| — | free text that doesn't parse as an integer -> `VALID_QUANTITY_INVALID`, re-prompt, no state change |
| — | quantity exceeding known stock signal on the listing (if the connector reported a stock count) -> `VALID_QUANTITY_EXCEEDS_STOCK`, re-prompt with the max, no state change |

Neither validation failure advances `AWAITING_QUANTITY -> AWAITING_CONFIRMATION`
— the conversation stays in place until a valid quantity is supplied or the
10-minute timeout reverts it (`STATE_TRANSITIONS.md` §4).

---

## 4. Order allocation (Account Service)

| Field | Rule |
|---|---|
| `requested_quantity` | required, > 0 |
| Allocation per account | `min(remaining_daily_cap / unit_price, account's available quantity heuristic)`, floor to integer, never allocate a fractional unit |
| Sum of allocations | may be less than `requested_quantity` (partial is valid, `STATE_TRANSITIONS.md` §2) but never more |

---

## 5. Cross-field / cross-service invariants

These aren't single-field checks — they're consistency rules enforced at
specific points in the pipeline:

- **Price tolerance at revalidation:** `abs(current_price - detected_price) / detected_price <= 0.02` to count as unchanged (`STATE_TRANSITIONS.md` §1). This is the single source of truth for "2%" — do not hardcode a different tolerance anywhere else.
- **Price tolerance at checkout:** `actual_checkout_price <= max_price` (`PURCHASE_TASK_CREATED.max_price`, set by Order Planner from the confirmed `unit_price`) — any excess aborts with `PURCH_PRICE_MISMATCH`, no partial-tolerance haggling at this stage (unlike revalidation, checkout tolerance is zero).
- **`fully_satisfied` consistency:** `AllocationPlan.fully_satisfied` must equal `sum(allocations[].quantity) == requested_quantity` — Order Planner does not independently recompute this; it trusts the Account Service's flag as-is, per the "trust the boundary" principle above.
- **One open deal per listing:** before inserting a new `deals` row, the Deal Engine must confirm no non-terminal `deals` row exists for the same `listing_id` (`DATABASE_SCHEMA.md` §6); if one exists, skip scoring rather than creating a duplicate.
- **Event schema version match:** a consumer receiving an `event_type` it recognizes but at a `version` it doesn't handle must reject and dead-letter (`SYS_EVENT_SCHEMA_INVALID`), never attempt best-effort parsing of an unknown version.

---

## 6. Admin Dashboard input (API Gateway)

| Field | Rule |
|---|---|
| `AccountStatusUpdateRequest.reason` | required, 1-500 chars — a status change with no reason is rejected, since it is the only audit trail for manual account actions |
| `scoring-config` weights | each weight 0.0-1.0, all weights for a `score_breakdown` component must sum to 1.0 across the config, rejected otherwise |
| Pagination `page_size` | 1-100; values above 100 are clamped to 100, not rejected |
