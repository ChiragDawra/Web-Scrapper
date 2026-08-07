# Resolved Questions

Every `Q#` flagged as open/undefined/incomplete/unstated across ZIP_01-07
(later ZIPs raised no numbered questions), mapped to its binding
resolution in this ZIP. `Q1-Q55` is the full range assigned across those
docs; numbers with no entry below (`Q6, Q9-Q12, Q19, Q22, Q23, Q25, Q28,
Q30`) were never independently raised as a flagged gap in any ZIP_01-07
source — there is nothing to resolve for them.

| # | Original gap | Resolution |
|---|---|---|
| Q1 | Event Bus undecided: Redis Streams vs Kafka (`ZIP_01/GLOSSARY.md`) | **Redis Streams for MVP**, fixed throughout `EVENT_SCHEMAS.md`. Kafka migration is a Phase-2 infra decision, not a contract change. |
| Q2 | Event names disagree across `ZIP_02/05/06/07` | `EVENT_SCHEMAS.md` is the canonical event name + payload registry; it supersedes every prior name list. |
| Q3 | Deal lifecycle state name inconsistency (`NEW` vs `DETECTED`, `SCORED` distinct or not) | `ENUMS.md` `deal_status` and `STATE_TRANSITIONS.md` §1 are canonical: lifecycle starts at `SCORED` (post-detection, pre-scoring states are internal to the Deal Engine and not persisted). |
| Q4 | `Listing` entity missing from `ZIP_03/ER_DIAGRAM.md` despite being used elsewhere | `DATABASE_SCHEMA.md` §4 `listings` is the canonical table; the ER diagram gap was a documentation omission, not a design question. |
| Q5 | Five ADRs recorded as one-line titles with no context/alternatives/consequences | Out of scope for this ZIP — a documentation-quality gap in `ZIP_01/DECISION_LOG.md`, not a contract ambiguity. No engineering decision is blocked on it. |
| Q7 | Score formula has terms but no weights, normalization, or output range | `CANONICAL_MODELS.md` fixes `ScoredDeal.score` to `0-100`. Weights live in `/scoring-config` (`API_CONTRACTS.md` §5), versioned as `weights_version`, summing to 1.0 per component (`VALIDATION_RULES.md` §6). |
| Q8 | Confidence component: computation method and "high" threshold undefined | Superseded — no standalone "confidence" component in `ScoredDeal.score_breakdown` (`CANONICAL_MODELS.md`); confidence is folded into the weighted `discount_score`/`brand_score`/`rating_score`/`velocity_score` breakdown. Minimum-score publish threshold is a `/scoring-config` value (`VALIDATION_RULES.md` §2). |
| Q13 | No document names the service performing revalidation | **Revalidation Service**, dedicated (ADR-008), full interface in `SERVICE_INTERFACES.md` §3. |
| Q14 | Event version placement and compatibility policy unspecified | `EVENT_SCHEMAS.md` §1: `version` is an envelope field, breaking changes bump it, `event_type` name is stable; consumers reject unrecognized versions (`SYS_EVENT_SCHEMA_INVALID`). |
| Q15 | Correlation ID field name, generation point, propagation mechanism unspecified | Field is `correlation_id` in the envelope (`EVENT_SCHEMAS.md` §1). Generation point is fixed per-flow: e.g. `DEAL_REVALIDATION_REQUEST` sets it to `deal_id`, `ACCOUNT_ALLOCATION_REQUEST` sets it to `order_id` — propagated unchanged by every downstream event in that chain. |
| Q16 | No service named as owner of `DEAL_EXPIRED` emission / TTL timer | Deal Engine (Deal Lifecycle component), consistent with its ownership of `deals` (`DATABASE_SCHEMA.md` table-ownership section). Expiry is driven by a scheduled sweep, same pattern as the Bot's timeout sweep (`STATE_TRANSITIONS.md` §4). |
| Q17 | No idempotency key or retry constants defined for consumers | `event_id` is the idempotency key, deduped via `processed_events` (`DATABASE_SCHEMA.md` §18). Retry constants: exponential backoff, base 2s, multiplier 2, max attempts per flow (`STATE_TRANSITIONS.md` §5, `ERROR_CODES.md`). |
| Q18 | No payload schema exists for any event | `EVENT_SCHEMAS.md` defines every event's payload. (Q18a, a sub-flag on the same gap in `DATABASE_SCHEMA.md`, is resolved the same way.) |
| Q20 | Undefined: user taps Interested on an already-expired deal | `STATE_TRANSITIONS.md` §1 "Tap-after-expiry" guard — Bot answers with an expiry notice, no `USER_INTERESTED` emitted, no state change. |
| Q21 | Undefined: is `ORDERED` truly terminal given a purchase can still fail afterward | Yes, terminal at the deal level by design (`STATE_TRANSITIONS.md` §1 "Relationship to Order outcome") — purchase success/failure is tracked independently on `orders`, never reopens the deal. |
| Q24 | No `REVALIDATING` timeout; no `WAITING_QUANTITY`/`CONFIRMING` timeouts; no transitions defined for Ignore/Watch Later | `STATE_TRANSITIONS.md` §1 (30s revalidation timeout -> `PRICE_CHANGED`) and §4 (10 min `AWAITING_QUANTITY`, 5 min `AWAITING_CONFIRMATION`, both revert to `IDLE`; `IGNORED`/`WATCHING` transitions defined in §1). |
| Q26 | Whether `PriceHistory` attaches to Listing or Product | Resolved in `DATABASE_SCHEMA.md` §5: attaches to `listing_id`. Prices are marketplace-specific; attaching to Product would merge divergent price series. |
| Q27 | Whether Account belongs to a Marketplace | Resolved in `DATABASE_SCHEMA.md` §9: `accounts.marketplace_id` is a mandatory (non-nullable) FK — one account, one marketplace, no cross-marketplace session sharing. |
| Q29 | Whether UUID PKs apply to Brand/Marketplace/OrderItem/PriceHistory/Account/Event, or was the omission deliberate | Not deliberate. **All entity PKs are UUID v4, no exceptions** (`README.md` "Non-negotiable defaults", `DATABASE_SCHEMA.md`). The sole exception is `events.seq`, a `BIGSERIAL` used only for ordering — `events.event_id` is still a UUID. |
| Q31 | No Inventory entity/table exists | `DATABASE_SCHEMA.md` §14 `inventory_items`, MVP-scoped to purchase tracking (ADR-012), with nullable `resale_price`/`profit` columns pre-added for an additive Phase-2 migration. |
| Q32 | Undefined interface for Order Planner to read account availability (event vs sync API vs shared read model) | Event-only: `ACCOUNT_ALLOCATION_REQUEST` / `ACCOUNT_ALLOCATION_RESPONSE` (`EVENT_SCHEMAS.md` §4). No shared read model, no synchronous cross-service DB read — consistent with ADR-009. |
| Q33 | No document says where realised profit is recorded | `inventory_items.profit` (`DATABASE_SCHEMA.md` §14), Phase 2 only — generated as `resale_price - purchase_price`, admin-entered via `PATCH /inventory/{id}` (`API_CONTRACTS.md` §3, currently 501/not implemented in MVP). |
| Q34 | Whether a deal is rescored on price change after `SCORED`/`NOTIFIED` | No. **No in-place rescoring, ever** (`STATE_TRANSITIONS.md` §1). A later qualifying price on the same listing produces a brand-new `deals` row instead, subject to the one-open-deal-per-listing dedup rule. |
| Q35 | `ACCOUNT_ALLOCATION_REQUEST`/`RESPONSE` sit outside the "thirteen-event" business catalog — separate governed channel or folded in? | Folded in. `EVENT_SCHEMAS.md` treats all request/response and business events under one envelope and one registry — there is no separate governance tier. |
| Q36 | Deal TTL: fixed 24h or per-marketplace configurable — inconsistent between docs | Fixed at 24h for MVP, sourced from `deals.expires_at` computed once at `SCORED` (`DATABASE_SCHEMA.md` §6). Per-marketplace configurability is a `/scoring-config`-adjacent Phase-2 feature, not implemented now. |
| Q37 | Unspecified event(s) around Bot-initiated purchase | `PURCHASE_REQUESTED` is the sole Bot-emitted purchase event (`EVENT_SCHEMAS.md` §4), emitted only on the `AWAITING_CONFIRMATION -> IDLE` confirm edge (`STATE_TRANSITIONS.md` §4). |
| Q38 | Order Planner behavior if Account Service never responds to allocation request | `PLAN_ALLOCATION_TIMEOUT` after 10s, retried up to 3 attempts, then dead-lettered (`ERROR_CODES.md`, `SERVICE_INTERFACES.md` §6). |
| Q39 | Whether a `PARTIAL` order triggers replanning of the failed portion, or terminates as-is | Terminates as-is; `PARTIAL` is terminal (`STATE_TRANSITIONS.md` §2). User may manually trigger a new order for the shortfall by re-approving the deal — a brand-new `orders` row, never a resurrection of the old one. |
| Q40 | Whether the Planner partially fulfils or rejects outright when eligible accounts can't cover requested quantity | Partially fulfils — allocates as many units as available (down to a minimum of 1) and proceeds to `PLANNED`; only **zero** eligible accounts causes `PLANNING_FAILED` (`STATE_TRANSITIONS.md` §2). |
| Q41 | Account recovery paths have triggers but no defined health-score effect | Fixed deltas table in `STATE_TRANSITIONS.md` §3: successful login/session refresh = no change; cooldown completion = +20; manual re-enable = reset to 100. |
| Q42 | Admin Dashboard missing from the official service list | Included as a first-class consumer throughout `API_CONTRACTS.md` and `DTOS.md` §3; it is a client of the API Gateway, not a separate backend service, so it owns no tables. |
| Q43 | Where scoring weights live (code constants vs DB vs config store) | Database-backed, versioned config exposed via `GET`/`PUT /scoring-config` (`API_CONTRACTS.md` §5), read by the Deal Engine at score time and stamped onto each deal as `weights_version` (`CANONICAL_MODELS.md`). |
| Q44 | Ratings and review count are scoring inputs but not in the connector interface | Added to `CanonicalProduct` as `rating` and `review_count`, both nullable (`CANONICAL_MODELS.md`). |
| Q45 | No duplicate-notification window defined | Enforced by the one-open-deal-per-listing dedup rule (`DATABASE_SCHEMA.md` §6) plus the `WATCHING -> DEAL_SENT` re-notify guard requiring either a further price drop or 24h elapsed (`STATE_TRANSITIONS.md` §1) — no separate duplicate-window config needed. |
| Q46 | No rate limit on notifications per user/hour | Not implemented in MVP; the dedup + re-notify guards above are the only throttle. Flagged here as accepted MVP scope, not a silent gap. |
| Q47 | Whether notifications go to one operator, a group, or per-user subscriptions | Per-user: `telegram_users` + `user_interests` (`DATABASE_SCHEMA.md` §7-8), one `bot_conversations` row per `telegram_user_id` (§15). Every deal card, quantity prompt, and confirmation is scoped to a single Telegram user. |
| Q48 | No defined price-change tolerance for "changed" vs "unchanged"; no defined edge for re-sending a deal card | Tolerance fixed at 2% (`STATE_TRANSITIONS.md` §1 guard); re-send edge is `WATCHING -> DEAL_SENT` on further price drop or 24h elapsed. |
| Q49 | No service owns the canonical product model | `CanonicalProduct` (`CANONICAL_MODELS.md`) — produced by every Connector's `normalize()`, the sole shape downstream services consume. |
| Q50 | Undefined pagination contract | `PagedResponse<T>` (`DTOS.md` §1) — fixed envelope (`items`, `page`, `page_size`, `total_count`, `has_next`), used by every list endpoint in `API_CONTRACTS.md`. |
| Q51 | Scanner Engine and Scheduler not in the official service list | Internal components of the Deal Engine, not separate deployables — consistent with `SERVICE_INTERFACES.md` §2 (Deal Engine owns detection-to-scoring end to end) and the Deal Engine's sole ownership of `products`/`listings`/`deals`. |
| Q52 | ML Service internal split (training / registry / inference) unstated | One logical service boundary in `SERVICE_INTERFACES.md` §11 for MVP; internal split into separate FastAPI deployables (training job vs inference API) is an infra/deployment detail, not a contract boundary — both read the same `events` table exception and expose no owned tables either way. |
| Q53 | Table ownership across services unconfirmed | `DATABASE_SCHEMA.md` "Table ownership" section — one authoritative table, no service queries a table it doesn't own (ADR-009). |
| Q54 | `telegram_users.status`-equivalent field: types, nullability, value set undefined | No free-standing `status` column exists on `telegram_users` in the final schema (`DATABASE_SCHEMA.md` §7) — the only per-user "state" concept is `bot_conversations.state` (`conversation_state` enum, `ENUMS.md`), which fully replaces the undefined field. |
| Q55 | Bot conversation state has no entity/table | `DATABASE_SCHEMA.md` §15 `bot_conversations`, full state machine in `STATE_TRANSITIONS.md` §4. |

---

## Numbers with no flagged gap

`Q6, Q9, Q10, Q11, Q12, Q19, Q22, Q23, Q25, Q28, Q30` do not appear as a
named open question in any ZIP_01-07 source document. They are not
resolved here because there was nothing on record to resolve. If a gap
surfaces later under one of these numbers, treat the relevant section of
this ZIP as binding by subject matter (e.g. a purchase-execution question
falls under `STATE_TRANSITIONS.md` §5 / `SERVICE_INTERFACES.md` §7
regardless of its number) rather than waiting for a numbered entry.
