# DTOs

Request/response shapes for the API Gateway (consumed by Admin Dashboard and
the Telegram Bot's HTTP calls where it doesn't go through events) and for
inter-service HTTP calls that are not pure event pub/sub. Field types follow
the same conventions as `CANONICAL_MODELS.md`: money in paise, timestamps
`timestamptz` ISO-8601, all IDs UUID v4.

Every list endpoint returns the `PagedResponse<T>` envelope in §1. Every
error returns `ErrorResponse` in §2.

---

## 1. PagedResponse<T>

```json
{
  "items": "T[], required",
  "page": "integer, required, 1-indexed",
  "page_size": "integer, required, default 25, max 100",
  "total_count": "integer, required",
  "has_next": "boolean, required"
}
```

## 2. ErrorResponse

```json
{
  "code": "string, required — one of ERROR_CODES.md",
  "message": "string, required — human-readable, safe to display",
  "severity": "error_severity, required",
  "retryable": "boolean, required",
  "details": "object, nullable — field-level validation errors, see VALIDATION_RULES.md §5"
}
```

---

## 3. Admin Dashboard DTOs

### DealSummaryDTO (list view)
```json
{
  "deal_id": "UUID",
  "canonical_title": "string",
  "marketplace": "marketplace_code",
  "score": "number",
  "discount_pct": "number",
  "status": "deal_status",
  "created_at": "timestamptz"
}
```

### DealDetailDTO (single deal)
Extends `DealSummaryDTO` with:
```json
{
  "score_breakdown": "object",
  "listing_url": "string (URL)",
  "detected_price": "integer paise",
  "reference_price": "integer paise",
  "brand_name": "string, nullable",
  "brand_tier": "brand_tier, nullable",
  "interested_user_count": "integer",
  "order_id": "UUID, nullable — set once status reaches ORDERED"
}
```

### AccountDTO
```json
{
  "account_id": "UUID",
  "marketplace": "marketplace_code",
  "status": "account_status",
  "health_score": "integer",
  "daily_spend_cap": "integer paise",
  "daily_spend_used": "integer paise",
  "cooldown_until": "timestamptz, nullable"
}
```

### AccountStatusUpdateRequest (PATCH body)
```json
{
  "status": "account_status, required — DISABLED_MANUAL or ACTIVE only, see API_CONTRACTS.md §4",
  "reason": "string, required, max 500 — written to bot_audit_log-equivalent admin log"
}
```

### OrderDetailDTO
```json
{
  "order_id": "UUID",
  "status": "order_status",
  "requested_quantity": "integer",
  "fulfilled_quantity": "integer",
  "total_amount": "integer paise",
  "failure_reason": "string, nullable",
  "items": [
    {
      "order_item_id": "UUID",
      "account_id": "UUID",
      "quantity": "integer",
      "status": "order_item_status",
      "purchase_task_id": "UUID, nullable"
    }
  ]
}
```

### InventoryItemDTO
```json
{
  "inventory_item_id": "UUID",
  "listing_id": "UUID",
  "canonical_title": "string",
  "quantity": "integer",
  "purchase_price": "integer paise",
  "status": "inventory_item_status",
  "resale_price": "integer paise, nullable — Phase 2",
  "profit": "integer paise, nullable — Phase 2",
  "acquired_at": "timestamptz"
}
```

---

## 4. Telegram Bot ↔ API Gateway DTOs

The Bot's primary interaction path is events (`EVENT_SCHEMAS.md`), but
read-only lookups (e.g. rendering a deal card from a stale callback) go
through the Gateway synchronously.

### DealCardDTO
```json
{
  "deal_id": "UUID",
  "canonical_title": "string",
  "image_url": "string (URL), nullable",
  "detected_price": "integer paise",
  "reference_price": "integer paise",
  "discount_pct": "number",
  "marketplace": "marketplace_code",
  "in_stock": "boolean",
  "expires_at": "timestamptz"
}
```

### QuantityConfirmationDTO
```json
{
  "deal_id": "UUID, required",
  "quantity": "integer, required — validated against VALIDATION_RULES.md §3"
}
```

---

## 5. ML Service DTOs

### TrainingFeatureRowDTO
Read-only export consumed by the ML Service's offline training job (pulls
from `events`, never live tables — ADR-009).
```json
{
  "deal_id": "UUID",
  "score_breakdown": "object",
  "user_action": "user_interest_action, nullable — null if no interaction recorded",
  "purchase_outcome": "boolean, nullable — null if never ordered",
  "brand_tier": "brand_tier",
  "marketplace": "marketplace_code",
  "discount_pct": "number"
}
```
