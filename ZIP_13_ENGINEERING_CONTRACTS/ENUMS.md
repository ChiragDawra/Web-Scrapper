# Enums

Canonical enum registry. No status/type column anywhere in the system may
hold free text. Every enum below is a Postgres `CREATE TYPE ... AS ENUM` and
a matching string literal set on the wire (event payloads, API JSON).

---

## marketplace_code
`AMAZON` | `FLIPKART` | `MYNTRA` | `NYKAA`

## deal_status
`SCORED` -> `NOTIFIED` -> `DEAL_SENT` -> (`INTERESTED` | `IGNORED` | `WATCHING` | `EXPIRED`)
`INTERESTED` -> (`REVALIDATING`) -> (`CONFIRMED` | `PRICE_CHANGED` | `SOLD_OUT`)
`CONFIRMED` -> `ORDERED`
Terminal: `EXPIRED`, `IGNORED`, `ORDERED`, `PRICE_CHANGED_REJECTED`, `SOLD_OUT_REJECTED`
Full set: `SCORED`, `NOTIFIED`, `DEAL_SENT`, `INTERESTED`, `REVALIDATING`,
`CONFIRMED`, `PRICE_CHANGED`, `SOLD_OUT`, `WATCHING`, `ORDERED`, `IGNORED`,
`EXPIRED`, `PRICE_CHANGED_REJECTED`, `SOLD_OUT_REJECTED`
See `STATE_TRANSITIONS.md` §1 for edges and guards.

## order_status
`REQUESTED`, `PLANNING_FAILED`, `PLANNED`, `EXECUTING`, `PARTIAL`, `COMPLETED`,
`FAILED`, `CANCELLED`
See `STATE_TRANSITIONS.md` §2.

## order_item_status
`PENDING`, `EXECUTING`, `COMPLETED`, `FAILED`, `CANCELLED`

## purchase_task_status
`CREATED`, `ASSIGNED`, `EXECUTING`, `COMPLETED`, `FAILED`, `RETRYING`,
`DEAD_LETTERED`

## account_status
`ACTIVE`, `WARNING`, `COOLDOWN`, `SUSPENDED`, `BANNED`, `DISABLED_MANUAL`
See `STATE_TRANSITIONS.md` §3.

## account_health_band
`HEALTHY` (score 80-100), `WARNING` (score 40-79), `CRITICAL` (score 1-39),
`ZERO` (score 0, forces `BANNED`)

## conversation_state
`IDLE`, `AWAITING_QUANTITY`, `AWAITING_CONFIRMATION`, `AWAITING_ADMIN_INPUT`
See `STATE_TRANSITIONS.md` §4.

## user_interest_action
`INTERESTED`, `IGNORED`, `WATCH_LATER`

## inventory_item_status
`PURCHASED`, `DELIVERED`, `RETURNED`, `RESOLD` (Phase 2 only)

## event_producer_service
`marketplace-connector`, `deal-engine`, `revalidation-service`, `telegram-bot`,
`order-planner`, `account-service`, `inventory-service`, `purchase-agent`,
`event-store-consumer`, `api-gateway`, `ml-service`

## currency_code
`INR` (only value supported in MVP; field exists for forward compatibility)

## error_severity
`INFO`, `WARNING`, `ERROR`, `CRITICAL`
See `ERROR_CODES.md`.

## brand_tier (scoring input, `ZIP_05/DEAL_SCORING.md`)
`PREMIUM`, `STANDARD`, `UNBRANDED`
