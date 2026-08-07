# API Contracts

REST surface exposed by the API Gateway. Two consumer groups: the Admin
Dashboard (authenticated staff) and the Telegram Bot (service-to-service,
for synchronous reads that don't warrant an event round-trip). All
mutating endpoints that change domain state beyond the Gateway's own
concern do so by publishing an event (`EVENT_SCHEMAS.md`), not by writing
to a table the Gateway doesn't own (ADR-009).

Base path: `/api/v1`. All responses: `application/json`. Auth: bearer
token (Admin Dashboard, staff session) or internal service token
(Telegram Bot, service mesh only — never exposed publicly).

---

## 1. Deals

### `GET /deals`
Admin Dashboard. Query params: `status` (deal_status, optional),
`marketplace` (marketplace_code, optional), `page`, `page_size`.
Response: `PagedResponse<DealSummaryDTO>` (`DTOS.md` §3).

### `GET /deals/{deal_id}`
Admin Dashboard + Bot. Response: `DealDetailDTO`.
404 if not found (`CONN_LISTING_NOT_FOUND`-style lookup miss).

### `GET /deals/{deal_id}/card`
Bot only. Response: `DealCardDTO` (`DTOS.md` §4) — used when the Bot needs
to re-render a card from a stale `deal_id` (e.g. inline query) rather than
its own cached copy.

---

## 2. Orders

### `GET /orders`
Admin Dashboard. Query params: `status` (order_status, optional), `page`,
`page_size`. Response: `PagedResponse<OrderDetailDTO>`.

### `GET /orders/{order_id}`
Admin Dashboard + Bot. Response: `OrderDetailDTO`.

Order creation is never a Gateway POST — it happens only via
`PURCHASE_REQUESTED` (`EVENT_SCHEMAS.md` §4), emitted directly by the Bot
onto the event bus. The Gateway has no `POST /orders`.

---

## 3. Inventory

### `GET /inventory`
Admin Dashboard. Query params: `status` (inventory_item_status, optional),
`page`, `page_size`. Response: `PagedResponse<InventoryItemDTO>`.

### `PATCH /inventory/{inventory_item_id}` (Phase 2 only)
Admin Dashboard. Body: `{ "resale_price": integer paise, "status": inventory_item_status }`.
Not implemented in MVP — returns 501 if called; listed here so the contract
is pre-agreed for Phase 2 rather than designed ad hoc.

---

## 4. Accounts

### `GET /accounts`
Admin Dashboard. Query params: `status` (account_status, optional),
`marketplace` (marketplace_code, optional). Response:
`PagedResponse<AccountDTO>`.

### `GET /accounts/{account_id}`
Admin Dashboard. Response: `AccountDTO`.

### `PATCH /accounts/{account_id}/status`
Admin Dashboard, staff-authenticated only (403 otherwise). Body:
`AccountStatusUpdateRequest` (`DTOS.md` §3).

Allowed transitions via this endpoint: `-> DISABLED_MANUAL` (from any
non-`BANNED` status) and `DISABLED_MANUAL -> ACTIVE` / `BANNED ->
DISABLED_MANUAL` per `STATE_TRANSITIONS.md` §3. Any other target status in
the request body is rejected with 400 `VALID_*` — this endpoint cannot set
`COOLDOWN`, `WARNING`, or `SUSPENDED`; those are system-managed only.

---

## 5. Deal scoring config (Admin Dashboard, read/write)

### `GET /scoring-config`
Returns the active scoring weights (`weights_version` referenced in
`CANONICAL_MODELS.md`'s `ScoredDeal.score_breakdown`).

### `PUT /scoring-config`
Staff-authenticated only. Creates a new `weights_version`; does not mutate
past `deals.score_breakdown` rows (`STATE_TRANSITIONS.md` §1 — no in-place
rescoring). Effective immediately for deals scored after this call.

---

## 6. Health / observability

### `GET /health`
Unauthenticated. Liveness only — `{ "status": "ok" }`.

### `GET /events/dead-letters`
Admin Dashboard. Query params: `consumer_service`, `event_type`, `page`.
Lists `EVENT_DEAD_LETTERED` events (`EVENT_SCHEMAS.md` §7) for manual
review.

### `POST /events/dead-letters/{original_event_id}/replay`
Admin Dashboard, staff-authenticated only. Republishes the original event
onto its original stream with a fresh `event_id` (new idempotency key —
the original stays dead-lettered as a record). Manual only, never
automatic (`ERROR_CODES.md`, `SYS_DEAD_LETTERED`).

---

## Error handling

Every non-2xx response body is `ErrorResponse` (`DTOS.md` §2). Status code
mapping is fixed in `ERROR_CODES.md` — "HTTP status mapping" table. No
endpoint invents its own status code scheme.
