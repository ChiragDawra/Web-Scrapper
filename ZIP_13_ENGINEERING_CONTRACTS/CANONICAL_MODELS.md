# Canonical Models

Resolves Q49 (no service owns the canonical product model) and the ratings
gap (Q44). These are the shapes every connector's `normalize()` must
produce and every downstream service consumes — independent of database
column names, though they map 1:1 onto `DATABASE_SCHEMA.md`.

---

## CanonicalProduct

Produced by every Marketplace Connector's `normalize()`. Maps onto
`products` + `listings`.

```json
{
  "canonical_title": "string, required, max 500",
  "brand_name": "string, nullable — connector best-effort extraction",
  "category": "string, nullable",
  "subcategory": "string, nullable",
  "attributes": { "size": "string", "color": "string", "variant": "string" },
  "image_url": "string (URL), nullable",
  "marketplace": "marketplace_code, required",
  "external_listing_id": "string, required — ASIN/FSN/SKU",
  "url": "string (URL), required",
  "price": "integer, paise, required",
  "mrp": "integer, paise, nullable",
  "currency": "currency_code, default INR",
  "rating": "number, 0.0-5.0, nullable",
  "review_count": "integer, nullable",
  "in_stock": "boolean, required"
}
```

Field ownership: `attributes` is an open map — connectors add
marketplace-specific keys freely, but `size`/`color`/`variant` are the three
keys the Deal Engine's scoring and dedup logic reads; any other key is
carried through opaquely and not interpreted downstream.

Brand resolution: the Deal Engine resolves `brand_name` to a `brands.id` by
case-insensitive exact match, creating a new `brands` row (tier
`STANDARD`) if no match exists. Brand tier upgrades to `PREMIUM` are manual,
via Admin Dashboard only.

---

## ScoredDeal

Produced by the Deal Engine's scoring step. Maps onto `deals`.

```json
{
  "listing_id": "UUID, required",
  "score": "number, 0-100, required",
  "score_breakdown": {
    "discount_score": "number",
    "brand_score": "number",
    "rating_score": "number",
    "velocity_score": "number",
    "weights_version": "string — which scoring config version produced this"
  },
  "detected_price": "integer, paise",
  "reference_price": "integer, paise",
  "discount_pct": "number",
  "expires_at": "timestamptz"
}
```

`score_breakdown` is stored verbatim and never recomputed (`STATE_TRANSITIONS.md`
§1) — it is the audit trail for why a deal was surfaced, and an ML training
feature.

---

## RevalidationResult

Produced by the Revalidation Service, consumed by the Telegram Bot.

```json
{
  "deal_id": "UUID, required",
  "listing_id": "UUID, required",
  "current_price": "integer, paise, required",
  "in_stock": "boolean, required",
  "changed": "boolean, required — true if price delta > 2% or in_stock flipped",
  "checked_at": "timestamptz, required"
}
```

---

## AllocationPlan

Produced by the Account Service in response to `ACCOUNT_ALLOCATION_REQUEST`,
consumed by Order Planner.

```json
{
  "order_id": "UUID, required",
  "requested_quantity": "integer, required",
  "allocations": [
    { "account_id": "UUID", "quantity": "integer" }
  ],
  "fully_satisfied": "boolean — true if sum(allocations.quantity) == requested_quantity"
}
```

An empty `allocations` array (with `fully_satisfied: false`) is a valid
response and drives `PLANNING_FAILED` (`STATE_TRANSITIONS.md` §2).

---

## PurchaseOutcome

Produced by a Purchase Agent on task completion or failure, consumed by
Order Planner, Inventory Service, Account Service, ML Service.

```json
{
  "purchase_task_id": "UUID, required",
  "success": "boolean, required",
  "marketplace_order_ref": "string, nullable — set only when success=true",
  "actual_price_paid": "integer, paise, nullable — set only when success=true",
  "error_code": "string, nullable — one of ERROR_CODES.md, set only when success=false",
  "attempt_count": "integer, required"
}
```
