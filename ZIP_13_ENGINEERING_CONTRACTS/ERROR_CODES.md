# Error Codes

Canonical registry. Used in HTTP error bodies (`API_CONTRACTS.md`), event
payload `error` fields, and `purchase_tasks.failure_reason` /
`orders.failure_reason`. Format: `DOMAIN_REASON`, all caps, snake-separated.

Every error carries: `code`, `message` (human-readable, safe to show a user
or log), `severity` (`error_severity` enum), `retryable` (bool).

---

## Connector / ingestion (`CONN_*`)

| Code | Meaning | Severity | Retryable |
|---|---|---|---|
| `CONN_RATE_LIMITED` | Marketplace returned 429 or equivalent | WARNING | yes |
| `CONN_AUTH_FAILED` | Marketplace session/API auth rejected | ERROR | no (needs credential refresh) |
| `CONN_PARSE_FAILED` | Response shape didn't match expected structure | ERROR | no (needs code fix) |
| `CONN_LISTING_NOT_FOUND` | Listing removed or delisted | INFO | no |
| `CONN_TIMEOUT` | Upstream request exceeded timeout | WARNING | yes |
| `CONN_CAPTCHA` | CAPTCHA challenge encountered | WARNING | yes, with backoff |

## Revalidation (`REVAL_*`)

| Code | Meaning | Severity | Retryable |
|---|---|---|---|
| `REVAL_TIMEOUT` | No `DEAL_REVALIDATED` within 30s | WARNING | yes, once |
| `REVAL_PRICE_CHANGED` | Price delta exceeded 2% tolerance | INFO | no |
| `REVAL_SOLD_OUT` | Listing out of stock at revalidation | INFO | no |

## Order Planning (`PLAN_*`)

| Code | Meaning | Severity | Retryable |
|---|---|---|---|
| `PLAN_NO_ACCOUNTS` | Zero eligible accounts for the marketplace | ERROR | no |
| `PLAN_INSUFFICIENT_CAPACITY` | Eligible accounts exist but total capacity < requested quantity | WARNING | no (proceeds as PARTIAL) |
| `PLAN_ALLOCATION_TIMEOUT` | `ACCOUNT_ALLOCATION_RESPONSE` not received within 10s | ERROR | yes, 3 attempts then dead-letter |

## Purchase execution (`PURCH_*`)

| Code | Meaning | Severity | Retryable |
|---|---|---|---|
| `PURCH_PRICE_MISMATCH` | Checkout-time price differs from planned price beyond tolerance | ERROR | no |
| `PURCH_OUT_OF_STOCK` | Item unavailable at checkout step | ERROR | no |
| `PURCH_CHECKOUT_FAILED` | Generic checkout automation failure (selector not found, page error) | ERROR | yes, up to 3 attempts |
| `PURCH_PAYMENT_FAILED` | Payment step rejected | ERROR | no |
| `PURCH_ACCOUNT_BLOCKED` | Account banned/suspended mid-task | CRITICAL | no, task dead-lettered |
| `PURCH_TIMEOUT` | Automation exceeded step timeout | WARNING | yes, up to 3 attempts |

## Account Service (`ACCT_*`)

| Code | Meaning | Severity | Retryable |
|---|---|---|---|
| `ACCT_COOLDOWN_ACTIVE` | Account requested while in cooldown | INFO | n/a |
| `ACCT_DAILY_CAP_EXCEEDED` | Allocation would exceed `daily_spend_cap` | INFO | n/a |
| `ACCT_SESSION_EXPIRED` | Stored session invalid, re-login required | WARNING | yes |

## Bot / API validation (`VALID_*`)

| Code | Meaning | Severity | Retryable |
|---|---|---|---|
| `VALID_QUANTITY_INVALID` | Quantity not a positive integer within allowed range | INFO | n/a |
| `VALID_QUANTITY_EXCEEDS_STOCK` | Requested quantity exceeds known stock signal | INFO | n/a |
| `VALID_DEAL_EXPIRED` | Action taken on an expired deal | INFO | n/a |
| `VALID_DUPLICATE_ACTION` | Conversation state already past this step (double-tap) | INFO | n/a |

## System (`SYS_*`)

| Code | Meaning | Severity | Retryable |
|---|---|---|---|
| `SYS_EVENT_SCHEMA_INVALID` | Payload failed JSON Schema validation on publish | CRITICAL | no, publish rejected |
| `SYS_DUPLICATE_EVENT` | `event_id` already in `processed_events` for this consumer | INFO | n/a, skip processing |
| `SYS_DEAD_LETTERED` | Message exceeded retry budget, moved to DLQ stream | CRITICAL | no, needs manual replay |

---

## HTTP status mapping (API Gateway)

| Error class | HTTP status |
|---|---|
| `VALID_*` | 400 |
| `*_AUTH_FAILED`, unauthenticated request | 401 |
| Authenticated but forbidden (e.g. non-admin hitting admin route) | 403 |
| Resource not found (`CONN_LISTING_NOT_FOUND`-equivalent lookups) | 404 |
| `ACCT_DAILY_CAP_EXCEEDED`, `PLAN_INSUFFICIENT_CAPACITY` treated as conflicts | 409 |
| `CONN_RATE_LIMITED` | 429 |
| Any `severity: CRITICAL` unhandled internally | 500 |

Response body shape: see `DTOS.md` §"ErrorResponse".
