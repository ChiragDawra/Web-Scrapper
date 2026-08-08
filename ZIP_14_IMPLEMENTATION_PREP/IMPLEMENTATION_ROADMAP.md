# Implementation Roadmap

Status of the architecture this roadmap builds against: **ZIP_13_ENGINEERING_CONTRACTS, v1.0, FROZEN.** This document does not modify architecture, database schema, event schemas, API contracts, DTOs, service interfaces, validation rules, or state transitions. Every task below cites the exact ZIP_13 file/section it implements. Where a task would require an architectural decision ZIP_13 does not make, it is flagged under "Known Gaps" at the end of this document, not decided here.

Sequencing basis: `SERVICE_INTERFACES.md` (11 services), `DATABASE_SCHEMA.md` "Table ownership", `EVENT_SCHEMAS.md` producer/consumer pairs. A service is scheduled only after every event type it *consumes* has a producer already built (or is built in the same sprint against fixtures).

---

## 1. Overall Timeline

This is a solo-developer-plus-AI-pairing build (Claude Code sessions), not a multi-engineer team sprint cadence. "Sprint" below means a themed, self-contained block of work, not a fixed two-week calendar box.

| Metric | Estimate | Basis |
|---|---|---|
| Total sprints | 17 (Sprint 0 - Sprint 16) | see §2 |
| Total atomic tasks | ~118 | sum of §4 task tables |
| Total engineering effort (fully serial) | ~118 focus-hours (~15 working days at 8h/day) | sum of all sprint effort estimates |
| Critical-path effort (parallel branches run alongside) | ~78 focus-hours (~10 working days at 8h/day) | see §3 |
| Full-time solo pace | ~2-3 calendar weeks | critical path + buffer |
| Part-time pace (10-15h/week) | ~6-10 calendar weeks | critical path / weekly hours |

These are estimates for a working, tested MVP slice per sprint — not padded for unknowns beyond what `RESOLVED_QUESTIONS.md` and the "Known Gaps" section already flag. Re-estimate after Sprint 3 once real per-task velocity is known.

---

## 2. Sprint List

| # | Sprint | Depends On | Parallelizable With |
|---|---|---|---|
| 0 | Repo & Infra Bootstrap | none | — |
| 1 | Event Bus Foundation & Full Schema Migration | 0 | — |
| 2 | Marketplace Connector Framework + Amazon Connector | 1 | 8 |
| 3 | Deal Engine Core | 1, 2 | 8 |
| 4 | Remaining Connectors (Flipkart, Myntra, Nykaa) | 2 | 3, 5, 8 |
| 5 | Revalidation Service | 1, 2 | 3, 4, 8 |
| 6 | Telegram Bot — Conversation State Machine & Deal Flow | 3, 5 | 8 |
| 7 | Telegram Bot — Purchase Flow | 6 | 8 |
| 8 | Account Service | 1 | 2-7 |
| 9 | Order Planner | 7, 8 | — |
| 10 | Purchase Agent Framework + Amazon Purchase Agent | 9 | — |
| 11 | Remaining Purchase Agents (Flipkart, Myntra, Nykaa) | 10 | 12, 15 |
| 12 | Inventory Service | 10 | 11, 15 |
| 13 | API Gateway | 3, 6, 8, 9, 12 | 15 |
| 14 | Admin Dashboard (frontend) | 13 | 15 |
| 15 | ML Service (stretch) | 1, 12 | 11, 12, 13, 14 |
| 16 | Integration, Hardening & Release | all | — |

---

## 3. Critical Path

```
Sprint 0 -> Sprint 1 -> Sprint 2 -> Sprint 3 -> Sprint 6 -> Sprint 7
  -> Sprint 9 -> Sprint 10 -> Sprint 12 -> Sprint 13 -> Sprint 14 -> Sprint 16
```

Off-critical-path branches that must complete before their join point but have slack:
- Sprint 4 (remaining connectors) and Sprint 5 (revalidation) must finish before Sprint 6 needs full marketplace coverage, but Sprint 6 only strictly requires Sprint 3 + Sprint 5's interface, not all four connectors live.
- Sprint 8 (Account Service) only depends on Sprint 1 and has ~24 hours of slack before Sprint 9 needs it.
- Sprint 11 (remaining purchase agents) and Sprint 15 (ML Service) can run entirely alongside Sprints 12-14.

---

## 4. Milestones

| Milestone | End of Sprint | Definition |
|---|---|---|
| M1 — Event backbone live | 1 | Full 18-table schema migrated; envelope publish/subscribe/dedup working; Event Store Consumer persisting every event type. |
| M2 — Ingestion + scoring live (one marketplace) | 3 | Amazon listings flow end-to-end into scored, deduplicated `deals` rows. |
| M3 — End-to-end user-facing deal flow live | 7 | A Telegram user can discover, express interest, revalidate, and confirm a purchase — `PURCHASE_REQUESTED` reaches the bus. No real spend yet. |
| M4 — Order planning + allocation live | 9 | `PURCHASE_REQUESTED` fans out to `PURCHASE_TASK_CREATED` against real (seeded) accounts, respecting caps/cooldowns. |
| M5 — First fully automated purchase | 12 | One marketplace proven deal-to-inventory end-to-end, real checkout automation, real `inventory_items` row. |
| M6 — Admin visibility + ML export live | 14/15 | Staff can observe and operate the system via the Dashboard; training data export works. |
| M7 — MVP release-ready | 16 | Full E2E test suite green across all 11 services in the compose stack; release checklist executed or its gaps logged. |

---

## 5. Standard Review Checklist

Applies to every task below unless a task lists an addition. A task is not "done" until every applicable item is checked, not just its own Definition of Done.

- [ ] Implementation matches exact field names, types, and required/nullable-ness from the ZIP_13 contract the task cites — no invented fields, no omitted ones.
- [ ] No new table, column, event type, endpoint, or enum value introduced beyond what ZIP_13 defines. A perceived gap is logged under "Known Gaps," never silently patched.
- [ ] Cross-service data access is via events or the API Gateway's read-only exception only (ADR-009) — no direct cross-schema queries, no service touching a table outside its ownership list (`DATABASE_SCHEMA.md` "Table ownership").
- [ ] Every consumed event is checked against `processed_events` before any side effect runs (dedup, resolves Q17).
- [ ] Error paths return/emit only codes defined in `ERROR_CODES.md`, with the documented `severity`/`retryable` values, not ad hoc strings.
- [ ] Unit and/or integration tests cover the task's Definition of Done and pass locally before commit.
- [ ] No secrets or credentials committed; `accounts.credentials_ref` pattern respected (reference only, never the secret, never the login email in logs — `DATABASE_SCHEMA.md` §9).
- [ ] Docstring/README references the exact ZIP_13 file + section the code implements, so a future reader can verify without re-deriving intent.

---

## 6. Sprint Detail

### Sprint 0 — Repo & Infra Bootstrap

**Goal:** A place for every later sprint's code to land, with a working local dev environment.
**Deliverables:** Full repo skeleton (`REPOSITORY_STRUCTURE.md`), `docker-compose.yml` with Postgres + Redis, Alembic initialized, lint/format/CI skeleton.
**Dependencies:** none.
**Definition of Done:** `docker compose up postgres redis` reaches healthy state; `alembic upgrade head` runs an empty migration cleanly; CI runs and passes on the initial commit.
**Acceptance Criteria:** A fresh clone, `docker compose up`, and one documented command reach a running, empty Postgres+Redis stack with no manual steps.

| # | Objective | Files Involved | Dependencies | Definition of Done | Review Checklist |
|---|---|---|---|---|---|
| 0.1 | Create the full monorepo folder skeleton per `REPOSITORY_STRUCTURE.md`, with placeholder `README.md` per service. | entire tree | none | `find . -type d` (excluding existing `ZIP_01`-`ZIP_13`) matches `REPOSITORY_STRUCTURE.md` exactly. | Standard |
| 0.2 | Write root `docker-compose.yml` with `postgres` + `redis` only, named volumes, healthchecks. | `docker-compose.yml` | 0.1 | `docker compose up postgres redis` reaches healthy state. | Standard |
| 0.3 | Initialize Alembic against Postgres with an empty baseline migration. | `infra/postgres/alembic.ini`, `infra/postgres/migrations/env.py`, `infra/postgres/migrations/versions/0001_baseline.py` | 0.2 | `alembic upgrade head` succeeds against the compose Postgres. | Standard |
| 0.4 | Root lint/format/type-check config + pre-commit wiring (one tool choice, applied uniformly). | `pyproject.toml`, `.pre-commit-config.yaml` | 0.1 | `pre-commit run --all-files` passes on the empty repo. | Standard |
| 0.5 | CI skeleton: lint + test job on push/PR, no deploy step. | `infra/ci/*` | 0.4 | CI run is green on the initial commit. | Standard |
| 0.6 | `.env.example` covering every env var implied across ZIP_13 (DB URL, Redis URL, Telegram bot token placeholder, `accounts.credentials_ref` placeholder pattern) — placeholders only. | `.env.example` | 0.2 | Every later service's config can theoretically source all its vars from this file's keys. | Standard + no real secret values, ever, even as examples |

---

### Sprint 1 — Event Bus Foundation & Full Schema Migration

**Goal:** The one piece every other service depends on: the event envelope, dedup, canonical models, and the complete database.
**Deliverables:** `libs/event_bus`, `libs/canonical_models`, `libs/enums`, `libs/error_codes`, full 18-table Alembic migration, Event Store Consumer service.
**Dependencies:** Sprint 0.
**Definition of Done:** Any throwaway script can publish/consume a test event through Redis Streams with envelope validation and dedup; Event Store Consumer persists it to `events`; all 18 tables + all enums exist exactly per `DATABASE_SCHEMA.md`/`ENUMS.md`.
**Acceptance Criteria:** The migrated schema diffs clean against `DATABASE_SCHEMA.md` table-by-table, column-by-column; a manually published event of each of the 12 types round-trips into `events` with correct `seq`/`stored_at`.

| # | Objective | Files Involved | Dependencies | Definition of Done | Review Checklist |
|---|---|---|---|---|---|
| 1.1 | Implement all 15 `ENUMS.md` enums as code, 1:1 name/value match. | `libs/enums/*.py` | 0.4 | Every enum value in `ENUMS.md` has exactly one code counterpart, no extras. | Standard |
| 1.2 | Implement the envelope model + JSON Schema validation per `EVENT_SCHEMAS.md` §1. | `libs/event_bus/envelope.py`, `libs/event_bus/schema/envelope.json` | 1.1 | Envelope missing nullable `correlation_id` validates; one missing `event_id` fails with `SYS_EVENT_SCHEMA_INVALID`. | Standard |
| 1.3 | Implement per-event-type JSON Schemas for all 12 event types (`EVENT_SCHEMAS.md` §2-§7), including `marketplace` on `DEAL_SCORED`/`PURCHASE_REQUESTED`/`PURCHASE_TASK_CREATED` and `listing_id`/`quantity` on `PurchaseOutcome`. | `libs/event_bus/schema/*.json` | 1.2 | One valid fixture per event type passes; one malformed fixture per event type fails. | Standard |
| 1.4 | Redis Streams publish/subscribe wrapper, consumer-group based. | `libs/event_bus/publisher.py`, `libs/event_bus/consumer.py` | 1.3, 0.2 | A local script publishes N events; a 2-worker consumer group processes all N exactly once between them. | Standard |
| 1.5 | `processed_events` dedup helper (check-before-act, write-after-act). | `libs/event_bus/dedup.py` | 1.4, 1.6 | Replaying the same `event_id` for the same `consumer_service` is skipped and logged as `SYS_DUPLICATE_EVENT`. | Standard |
| 1.6 | Full Alembic migration: all 18 tables, FKs, indexes, enum types exactly per `DATABASE_SCHEMA.md` §1-§18. | `infra/postgres/migrations/versions/0002_full_schema.py` | 0.3 | Line-by-line diff of the migration's DDL against `DATABASE_SCHEMA.md` shows zero deviation. | Standard + no added/renamed/omitted column vs. the doc |
| 1.7 | `libs/canonical_models`: `CanonicalProduct`, `ScoredDeal`, `AllocationPlan`, `RevalidationResult`, `PurchaseOutcome` exactly per `CANONICAL_MODELS.md` (including `marketplace` on `ScoredDeal`, `listing_id`/`quantity` on `PurchaseOutcome`). | `libs/canonical_models/*.py` | 1.1 | Every field per model in `CANONICAL_MODELS.md` exists with matching required/nullable-ness. | Standard |
| 1.8 | Event Store Consumer service: subscribes to every stream, validates envelope + payload, writes to `events` (sole writer, ADR-010), rejects invalid with `SYS_EVENT_SCHEMA_INVALID`. | `services/event-store-consumer/src/*` | 1.3, 1.4, 1.6 | Publishing one event of each of the 12 types yields exactly 12 new `events` rows, correct `seq` order; one malformed publish is rejected, not stored. | Standard |

**Milestone M1** reached at the end of this sprint (§4).

---

### Sprint 2 — Marketplace Connector Framework + Amazon Connector

**Goal:** First live ingestion path.
**Deliverables:** `ConnectorInterface`, shared validator, Amazon connector, `LISTING_DISCOVERED` emit.
**Dependencies:** Sprint 1.
**Definition of Done:** Against recorded/mocked Amazon fixtures, the connector emits one valid `LISTING_DISCOVERED` per valid fixture, drops malformed ones with `CONN_PARSE_FAILED`, never emits a partial product.
**Acceptance Criteria:** Every rule in `VALIDATION_RULES.md` §1 is enforced pre-emit; a fixture missing a required field produces zero events.

| # | Objective | Files Involved | Dependencies | Definition of Done | Review Checklist |
|---|---|---|---|---|---|
| 2.1 | Define `ConnectorInterface` base class, `normalize(raw) -> CanonicalProduct`. | `services/marketplace-connector/src/base/connector_interface.py` | 1.7 | Signature matches `SERVICE_INTERFACES.md` §1 exactly. | Standard |
| 2.2 | Shared validator implementing `VALIDATION_RULES.md` §1, called by every connector before returning. | `services/marketplace-connector/src/base/normalizer.py` | 2.1 | Each of the 9 rules has one pass + one fail unit test. | Standard |
| 2.3 | Amazon connector: raw-fetch stub + `normalize()` mapping. | `services/marketplace-connector/src/connectors/amazon/*.py` | 2.2 | 5+ recorded fixtures normalize correctly, including missing `mrp` (nullable) and no-stock-signal (must infer `false`, never null). | Standard |
| 2.4 | Wire Amazon entrypoint to publish `LISTING_DISCOVERED`. | `services/marketplace-connector/src/main.py` | 2.3, 1.4 | One `LISTING_DISCOVERED` per valid fixture appears on the bus. | Standard |
| 2.5 | `CONN_PARSE_FAILED` path: log + skip, no partial emit, no crash of the poll loop. | `services/marketplace-connector/src/base/connector_interface.py` | 2.3 | One malformed fixture is skipped; the next fixture in the batch still processes. | Standard |
| 2.6 | Dockerfile + dependency manifest; add `marketplace-connector-amazon` to compose. | `services/marketplace-connector/Dockerfile`, `docker-compose.yml` | 2.4 | `docker compose up marketplace-connector-amazon` runs the poll loop against fixtures without crashing. | Standard |
| 2.7 | Unit + integration test suite. | `services/marketplace-connector/tests/*` | 2.3-2.5 | Green in CI. | Standard |

---

### Sprint 3 — Deal Engine Core

**Goal:** First scored deals.
**Deliverables:** `resolveBrand()`, `score()`, dedup guard, `DEAL_SCORED` emit, `USER_INTERESTED` handling.
**Dependencies:** Sprints 1, 2.
**Definition of Done:** A `LISTING_DISCOVERED` event either produces exactly one `DEAL_SCORED` + persisted `deals` row, or is silently skipped below threshold — never both, never neither.
**Acceptance Criteria:** The one-open-deal-per-listing rule (`VALIDATION_RULES.md` §5) holds under a duplicate `LISTING_DISCOVERED` for the same listing.

| # | Objective | Files Involved | Dependencies | Definition of Done | Review Checklist |
|---|---|---|---|---|---|
| 3.1 | Repository layer for the six Deal-Engine-owned tables only (`brands`, `marketplaces`, `products`, `listings`, `price_history`, `deals`). | `services/deal-engine/src/repositories/*.py` | 1.6 | Every operation `score()`/`resolveBrand()` needs exists; no method touches a table outside the six. | Standard |
| 3.2 | `resolveBrand(brand_name) -> brand_id`, case-insensitive match, `STANDARD`-tier row created on miss. | `services/deal-engine/src/services/brand_resolver.py` | 3.1 | Same name in different casing resolves identically; unknown brand creates exactly one row on repeat calls. | Standard |
| 3.3 | `score(product) -> ScoredDeal \| null` per `VALIDATION_RULES.md` §2, reads `/scoring-config` weights. | `services/deal-engine/src/services/scorer.py` | 3.2 | Below-threshold product returns `null`, no side effects; above-threshold `score_breakdown` component weights sum to 1.0. | Standard |
| 3.4 | One-open-deal-per-listing dedup guard (`SELECT ... FOR UPDATE` before insert). | `services/deal-engine/src/services/deal_writer.py` | 3.3 | Two concurrent `LISTING_DISCOVERED` for the same listing under load produce exactly one `deals` row. | Standard |
| 3.5 | `LISTING_DISCOVERED` consumer: dedup, `score()`, persist, emit `DEAL_SCORED` with `marketplace` from the listings/marketplaces join. | `services/deal-engine/src/main.py`, `services/deal-engine/src/handlers/event_handlers.py` | 3.4, 1.5 | End-to-end from published `LISTING_DISCOVERED` to a `DEAL_SCORED` with correct `marketplace`. | Standard |
| 3.6 | `USER_INTERESTED` consumer: transitions `deals.status` per `STATE_TRANSITIONS.md` §1, tap-after-expiry guard. | `services/deal-engine/src/handlers/event_handlers.py` | 3.5 | An interest event on an `EXPIRED` deal is rejected, not applied. | Standard |
| 3.7 | Dockerfile, compose wiring, test suite. | `services/deal-engine/Dockerfile`, `docker-compose.yml`, `services/deal-engine/tests/*` | 3.1-3.6 | Green in CI. | Standard |

**Milestone M2** reached at the end of this sprint (§4).

---

### Sprint 4 — Remaining Connectors (Flipkart, Myntra, Nykaa)

**Goal:** Full marketplace coverage on ingestion.
**Deliverables:** Three more connectors reusing the Sprint 2 framework.
**Dependencies:** Sprint 2 (framework); Sprint 3 recommended, not required, to validate against.
**Definition of Done / Acceptance Criteria:** identical to Sprint 2's, per marketplace.
**Note:** Framework and validator (Sprint 2 Tasks 2.1-2.2) are not repeated. Up to 3 parallel tracks, one per marketplace.

Repeat the following 3-task set once per marketplace (`FLIPKART`, `MYNTRA`, `NYKAA`), referencing `ZIP_04/FLIPKART.md`, `ZIP_04/MYNTRA.md`, `ZIP_04/NYKAA.md` for marketplace-specific selectors/mapping:

| # | Objective | Files Involved | Dependencies | Definition of Done | Review Checklist |
|---|---|---|---|---|---|
| 4.x.1 | `{Marketplace}` connector `normalize()` mapping + fixtures. | `services/marketplace-connector/src/connectors/{marketplace}/*.py` | 2.1, 2.2 | Same as 2.3, for this marketplace. | Standard |
| 4.x.2 | Wire `{Marketplace}` entrypoint; add `marketplace-connector-{marketplace}` to compose. | `services/marketplace-connector/src/main.py`, `docker-compose.yml` | 4.x.1 | Same as 2.4/2.6, for this marketplace. | Standard |
| 4.x.3 | Test suite for `{marketplace}` connector. | `services/marketplace-connector/tests/{marketplace}/*` | 4.x.1, 4.x.2 | Green in CI. | Standard |

(9 tasks total: 4.1.1-4.1.3 Flipkart, 4.2.1-4.2.3 Myntra, 4.3.1-4.3.3 Nykaa.)

---

### Sprint 5 — Revalidation Service

**Goal:** Live price/stock re-check before a user commits to a purchase.
**Deliverables:** `revalidate()`, `DEAL_REVALIDATED` emit.
**Dependencies:** Sprints 1, 2 (at least one connector's live-read path).
**Definition of Done:** Called with a `listing_id`, returns live price/stock and computes `changed` per the 2%-delta/stock-flip guard, within the 30s budget.
**Acceptance Criteria:** Price within 2% of `detected_price` reports `changed=false`; outside 2% or a stock flip reports `changed=true`; no response is sent past 30s.

| # | Objective | Files Involved | Dependencies | Definition of Done | Review Checklist |
|---|---|---|---|---|---|
| 5.1 | `revalidate(listing_id) -> RevalidationResult`, calling the relevant connector's live-read path (not a cached `listings` row). | `services/revalidation-service/src/services/revalidator.py` | 2.x connector read paths, 1.7 | Unit tests cover <2%, exactly 2%, >2%, and stock-flip cases per `VALIDATION_RULES.md` §5. | Standard + tolerance value is read from the single source of truth, not hardcoded locally |
| 5.2 | `DEAL_REVALIDATION_REQUEST` consumer + `DEAL_REVALIDATED` emit, correlation_id threading. | `services/revalidation-service/src/handlers/event_handlers.py` | 5.1 | Request-to-response completes within the 30s budget locally. | Standard |
| 5.3 | Timeout-budget guard: no `DEAL_REVALIDATED` emitted after the service's own 30s window closes. | `services/revalidation-service/src/services/revalidator.py` | 5.2 | A forced-slow (>30s) fixture results in no event published. | Standard |
| 5.4 | Dockerfile, compose wiring, tests. | `services/revalidation-service/*` | 5.1-5.3 | Green in CI. | Standard |

---

### Sprint 6 — Telegram Bot: Conversation State Machine & Deal Flow

**Goal:** First user-visible surface.
**Deliverables:** State machine, deal-card rendering, `handleCallback()`, `USER_INTERESTED`/`DEAL_REVALIDATION_REQUEST` emit, `DEAL_SCORED`/`DEAL_REVALIDATED` consumers.
**Dependencies:** Sprints 3, 5.
**Definition of Done:** A scored deal reaches a Telegram chat as a card; tapping "Interested" transitions state, triggers revalidation, reflects the result — per `STATE_TRANSITIONS.md` §1 and §4.
**Acceptance Criteria:** A second interaction while `state != IDLE` is rejected, not accepted; a tap on an expired deal is blocked before any event is emitted.

| # | Objective | Files Involved | Dependencies | Definition of Done | Review Checklist |
|---|---|---|---|---|---|
| 6.1 | Repositories for `telegram_users`, `user_interests`, `bot_conversations`, `bot_messages`, `bot_audit_log`. | `services/telegram-bot/src/repositories/*.py` | 1.6 | CRUD covers every column in `DATABASE_SCHEMA.md` §7-8, §15-17. | Standard |
| 6.2 | `DEAL_SCORED` consumer -> render + send deal card, record `bot_messages` row (`message_type='DEAL_CARD'`). | `services/telegram-bot/src/handlers/event_handlers.py`, `services/telegram-bot/src/messages/templates.py` | 6.1 | One `DEAL_SCORED` yields exactly one Telegram message + one `bot_messages` row. | Standard |
| 6.3 | `state_machine.py`: full `STATE_TRANSITIONS.md` §4 (states, edges, timeouts) as a pure class, independent of the Telegram SDK. | `services/telegram-bot/src/conversation/state_machine.py` | 6.1 | Unit tests cover every §4 edge, including the reject-while-non-IDLE guard. | Standard |
| 6.4 | `handleCallback(telegram_user_id, callback_data)`: buttons -> state machine; "Interested" emits `USER_INTERESTED` (tap-after-expiry guard) + `DEAL_REVALIDATION_REQUEST`. | `services/telegram-bot/src/conversation/handlers.py` | 6.3, 1.4 | Tap on a live deal emits both events with correct correlation; on an expired deal, emits neither. | Standard |
| 6.5 | `DEAL_REVALIDATED` consumer + 30s timeout-to-`PRICE_CHANGED` fallback (`REVAL_TIMEOUT`). | `services/telegram-bot/src/handlers/event_handlers.py` | 6.4 | A simulated missing response is treated as `PRICE_CHANGED` after 30s, not an indefinite hang. | Standard |
| 6.6 | `sweepTimeouts()` scheduled job (60s), reverts `AWAITING_QUANTITY`/`AWAITING_CONFIRMATION` per the fixed thresholds. | `services/telegram-bot/src/conversation/timeouts.py` | 6.3 | A conversation stuck past its threshold reverts to `IDLE` on the next sweep, not before. | Standard |
| 6.7 | Dockerfile, compose wiring, tests. | `services/telegram-bot/*` | 6.1-6.6 | Green in CI. | Standard |

---

### Sprint 7 — Telegram Bot: Purchase Flow

**Goal:** Purchase intent capture.
**Deliverables:** Quantity collection/validation, confirmation, `PURCHASE_REQUESTED` emit, `PURCHASE_COMPLETED`/`PURCHASE_FAILED` consumers.
**Dependencies:** Sprint 6.
**Definition of Done:** A confirmed purchase intent reaches the bus as exactly one `PURCHASE_REQUESTED`, pre-generated `order_id`, correct `unit_price`, `marketplace` carried from the originating `DEAL_SCORED`.
**Acceptance Criteria:** `VALIDATION_RULES.md` §3 enforced (1-10 cap, non-integer rejection, stock-exceeding rejection) with no state advance on failure.

| # | Objective | Files Involved | Dependencies | Definition of Done | Review Checklist |
|---|---|---|---|---|---|
| 7.1 | `AWAITING_QUANTITY` free-text handler + `VALIDATION_RULES.md` §3 enforcement. | `services/telegram-bot/src/conversation/handlers.py` | 6.3 | Tests for non-integer, 0, 11, and stock-exceeding input all re-prompt without state change. | Standard |
| 7.2 | `AWAITING_CONFIRMATION` handler -> `PURCHASE_REQUESTED` emit, pre-generated `order_id`, `marketplace` carried from the stored `DEAL_SCORED` payload. | `services/telegram-bot/src/conversation/handlers.py` | 7.1 | Emitted event validates against the `PURCHASE_REQUESTED` schema (1.3). | Standard |
| 7.3 | `PURCHASE_COMPLETED`/`PURCHASE_FAILED` consumers -> status message to the user. | `services/telegram-bot/src/handlers/event_handlers.py` | 7.2 | Both event types produce a distinct, correct message. | Standard |
| 7.4 | `bot_audit_log` entries for every click/command/message in the purchase flow. | `services/telegram-bot/src/conversation/handlers.py` | 7.1-7.3 | A full happy-path run leaves a complete, ordered audit trail. | Standard |
| 7.5 | Integration test: card -> interested -> revalidate -> quantity -> confirm -> `PURCHASE_REQUESTED` on the bus, downstream mocked. | `services/telegram-bot/tests/integration/*` | 7.1-7.4 | Green, asserts exact event shape. | Standard |
| 7.6 | Centralize message templates + button payload constants (no magic strings in handlers). | `services/telegram-bot/src/messages/templates.py`, `services/telegram-bot/src/messages/buttons.py` | 7.3 | No literal Telegram markup strings outside these two files. | Standard |

**Milestone M3** reached at the end of this sprint (§4).

---

### Sprint 8 — Account Service

**Goal:** Real account allocation, independent of the purchase-flow critical path (only depends on Sprint 1 — schedule this in parallel with Sprints 2-7).
**Deliverables:** `allocate()`, `applyHealthDelta()`, `resetDailySpend()`, allocation request/response, health-changed emit.
**Dependencies:** Sprint 1.
**Definition of Done:** Given seeded test accounts, `allocate()` returns a plan respecting `STATE_TRANSITIONS.md` §3 status exclusions and `daily_spend_cap` (`VALIDATION_RULES.md` §4), within the 10s budget.
**Acceptance Criteria:** `fully_satisfied` matches `sum(allocations[].quantity) == requested_quantity` exactly.

| # | Objective | Files Involved | Dependencies | Definition of Done | Review Checklist |
|---|---|---|---|---|---|
| 8.1 | `accounts` repository + seed script (multiple marketplaces, mixed statuses). | `services/account-service/src/repositories/account_repo.py`, `scripts/seed_accounts.py` | 1.6 | Seed produces at least one account per marketplace in `ACTIVE`, `COOLDOWN`, `BANNED`. | Standard |
| 8.2 | `allocate(marketplace, requested_quantity) -> AllocationPlan`: status exclusion + spend-cap + floor-to-integer logic. | `services/account-service/src/services/allocator.py` | 8.1 | Tests cover full satisfaction, partial satisfaction, and zero-eligible (`PLAN_NO_ACCOUNTS`) cases. | Standard |
| 8.3 | `ACCOUNT_ALLOCATION_REQUEST` consumer -> `allocate()` -> `ACCOUNT_ALLOCATION_RESPONSE`, within the 10s budget. | `services/account-service/src/handlers/event_handlers.py` | 8.2, 1.4 | Round trip completes well inside 10s against seeded accounts. | Standard |
| 8.4 | `applyHealthDelta(account_id, event_type, reason)`: fixed delta table + status transitions (`STATE_TRANSITIONS.md` §3), `ACCOUNT_HEALTH_CHANGED` on every change. | `services/account-service/src/services/health.py` | 8.1 | A delta sequence crossing `health_score` to 0 results in `BANNED`; one event per individual change, not just band crossings. | Standard |
| 8.5 | `PURCHASE_COMPLETED`/`PURCHASE_FAILED` consumers -> `applyHealthDelta()`. | `services/account-service/src/handlers/event_handlers.py` | 8.4 | A simulated failed purchase reduces the target account's health per the defined delta. | Standard |
| 8.6 | `resetDailySpend()` scheduled job (00:00 IST). | `services/account-service/src/jobs/reset_daily_spend.py` | 8.1 | Running the job resets `daily_spend_used` to 0 for every seeded account. | Standard |
| 8.7 | Internal status-update method backing the future Gateway `PATCH /accounts/{id}/status`, enforcing the allowed-transition subset (`API_CONTRACTS.md` §4). | `services/account-service/src/services/status_updater.py` | 8.4 | Attempted transition to `COOLDOWN`/`WARNING`/`SUSPENDED` via this path is rejected; `DISABLED_MANUAL` transitions succeed. | Standard |
| 8.8 | Dockerfile, compose wiring, tests. | `services/account-service/*` | 8.1-8.7 | Green in CI. | Standard |

---

### Sprint 9 — Order Planner

**Goal:** Fan a purchase request out into per-account tasks.
**Deliverables:** `plan()`, `reconcile()`, `PURCHASE_REQUESTED` consumer, allocation-request/`PURCHASE_TASK_CREATED` emit.
**Dependencies:** Sprints 7, 8.
**Definition of Done:** A `PURCHASE_REQUESTED` results in an `orders` row, an allocation round trip, one `PURCHASE_TASK_CREATED` per allocation line, each carrying `marketplace` and `max_price` correctly.
**Acceptance Criteria:** Zero eligible accounts routes to `PLANNING_FAILED`; `fully_satisfied=false` still proceeds to `PLANNED`, not blocked.

| # | Objective | Files Involved | Dependencies | Definition of Done | Review Checklist |
|---|---|---|---|---|---|
| 9.1 | Repositories for `orders`, `order_items`, `purchase_tasks`. | `services/order-planner/src/repositories/*.py` | 1.6 | CRUD covers every column in `DATABASE_SCHEMA.md` §10-12. | Standard |
| 9.2 | `PURCHASE_REQUESTED` consumer -> `orders`/`order_items` rows, `ACCOUNT_ALLOCATION_REQUEST` emit with `marketplace` from the payload. | `services/order-planner/src/handlers/event_handlers.py` | 9.1, 1.4 | Emitted request validates against its schema; `correlation_id = order_id`. | Standard |
| 9.3 | `ACCOUNT_ALLOCATION_RESPONSE` consumer -> plan completion: `PLANNING_FAILED` on zero allocations, else `PLANNED` + one `PURCHASE_TASK_CREATED` per allocation line, `marketplace`/`max_price` set from confirmed `unit_price`. | `services/order-planner/src/services/planner.py` | 9.2 | Zero-allocation fixture -> `PLANNING_FAILED`, no tasks emitted. Partial-allocation fixture -> `PLANNED`, tasks emitted for exactly the returned lines. | Standard |
| 9.4 | `PLAN_ALLOCATION_TIMEOUT` handling: 10s wait, retried up to 3 times, then dead-lettered. | `services/order-planner/src/services/planner.py` | 9.3 | Simulated non-responding Account Service -> exactly 3 retries then dead-letter. | Standard |
| 9.5 | `reconcile(order_id)`: invoked on each `PURCHASE_COMPLETED`/`PURCHASE_FAILED`, computes `fulfilled_quantity`, sets final `order_status` once all tasks terminal. | `services/order-planner/src/services/reconciler.py` | 9.3 | Tests cover full completion, partial completion, full failure per `STATE_TRANSITIONS.md` §2; `total_amount` never recalculated here. | Standard |
| 9.6 | `PURCHASE_COMPLETED`/`PURCHASE_FAILED` consumer wiring -> `reconcile()`. | `services/order-planner/src/handlers/event_handlers.py` | 9.5 | A full simulated task set for one order reaches the correct terminal `order_status`. | Standard |
| 9.7 | Dockerfile, compose wiring, tests. | `services/order-planner/*` | 9.1-9.6 | Green in CI. | Standard |

**Milestone M4** reached at the end of this sprint (§4).

---

### Sprint 10 — Purchase Agent Framework + Amazon Purchase Agent

**Goal:** First real (automated) checkout.
**Deliverables:** Agent interface, retry policy, session management, Amazon checkout automation.
**Dependencies:** Sprint 9.
**Definition of Done:** Given a `PURCHASE_TASK_CREATED` fixture against a sandbox/mock Amazon checkout, `execute()` returns a `PurchaseOutcome` (with `listing_id`/`quantity`) and emits the corresponding event; price-mismatch and out-of-stock abort with no retry.
**Acceptance Criteria:** Retry policy matches `STATE_TRANSITIONS.md` §5 exactly — backoff base 2s, multiplier 2, max 3 attempts for infra-level errors before `DEAD_LETTERED`; business-level failures go straight to `FAILED`.

| # | Objective | Files Involved | Dependencies | Definition of Done | Review Checklist |
|---|---|---|---|---|---|
| 10.1 | `PurchaseAgentInterface` with `execute(purchase_task) -> PurchaseOutcome`. | `services/purchase-agent/src/base/agent_interface.py` | 1.7 | Signature matches `SERVICE_INTERFACES.md` §7 exactly. | Standard |
| 10.2 | Retry policy: backoff, attempt counting, infra-vs-business error classification. | `services/purchase-agent/src/base/retry_policy.py` | 10.1 | Tests cover 1st/2nd/3rd infra-error attempt timing and the immediate-`FAILED` business-error path, matching `STATE_TRANSITIONS.md` §5 and `ERROR_CODES.md` `PURCH_*` retryability flags exactly. | Standard |
| 10.3 | Browser session manager + cookie store, no cross-marketplace session sharing. | `services/purchase-agent/src/sessions/*.py` | 10.1 | A session persisted for one account is reused on a second `execute()` without re-login; sessions for different accounts never collide. | Standard |
| 10.4 | Amazon checkout automation implementing `execute()` against a sandbox/mocked page. | `services/purchase-agent/src/agents/amazon/*.py` | 10.3 | Happy-path fixture -> `success=true` + `marketplace_order_ref`; price-mismatch fixture -> `PURCH_PRICE_MISMATCH`, zero retries. | Standard |
| 10.5 | `PURCHASE_TASK_CREATED` consumer: route to the correct marketplace's agent (immutable platform identity), call `execute()`, emit `PURCHASE_COMPLETED`/`PURCHASE_FAILED` with `listing_id`/`quantity` echoed. | `services/purchase-agent/src/handlers/event_handlers.py` | 10.4, 1.4 | Emitted event validates against schema; every field Inventory Service's future `recordAcquisition` needs is present. | Standard |
| 10.6 | `EVENT_DEAD_LETTERED` emit when retries exhaust for an infra-level error. | `services/purchase-agent/src/base/retry_policy.py` | 10.2 | A fixture forced to fail 3 consecutive infra-level attempts -> exactly one `EVENT_DEAD_LETTERED`, `attempt_count=3`. | Standard |
| 10.7 | Dockerfile (Playwright base image), compose wiring, tests. | `services/purchase-agent/*` | 10.1-10.6 | Green in CI. | Standard |

---

### Sprint 11 — Remaining Purchase Agents (Flipkart, Myntra, Nykaa)

**Goal:** Full marketplace coverage on purchase execution.
**Dependencies:** Sprint 10 (framework/retry policy not repeated).
**Definition of Done / Acceptance Criteria:** identical to Sprint 10's, per marketplace. Parallelizable across up to 3 tracks, and with Sprints 12/15.

Repeat once per marketplace, referencing `ZIP_08/FLIPKART_PURCHASE_AGENT.md`, `ZIP_08/MYNTRA_PURCHASE_AGENT.md`, `ZIP_08/NYKAA_PURCHASE_AGENT.md`:

| # | Objective | Files Involved | Dependencies | Definition of Done | Review Checklist |
|---|---|---|---|---|---|
| 11.x.1 | `{Marketplace}` checkout automation. | `services/purchase-agent/src/agents/{marketplace}/*.py` | 10.1-10.3 | Same as 10.4, for this marketplace. | Standard |
| 11.x.2 | Route `{marketplace}` tasks to this agent in the consumer dispatch table. | `services/purchase-agent/src/handlers/event_handlers.py` | 11.x.1 | Same as 10.5, for this marketplace. | Standard |
| 11.x.3 | Test suite for `{marketplace}` agent. | `services/purchase-agent/tests/{marketplace}/*` | 11.x.1, 11.x.2 | Green in CI. | Standard |

(9 tasks total: 11.1.1-11.1.3 Flipkart, 11.2.1-11.2.3 Myntra, 11.3.1-11.3.3 Nykaa.)

---

### Sprint 12 — Inventory Service

**Goal:** Close the loop from purchase to inventory.
**Deliverables:** `inventory_items` repository, `recordAcquisition()`.
**Dependencies:** Sprint 10.
**Definition of Done:** A `PURCHASE_COMPLETED` results in exactly one `inventory_items` row, idempotent on `purchase_task_id`.
**Acceptance Criteria:** Replaying the same `PURCHASE_COMPLETED` `event_id` produces no duplicate row.

| # | Objective | Files Involved | Dependencies | Definition of Done | Review Checklist |
|---|---|---|---|---|---|
| 12.1 | `inventory_items` repository. | `services/inventory-service/src/repositories/inventory_repo.py` | 1.6 | CRUD covers every column in `DATABASE_SCHEMA.md` §14. | Standard |
| 12.2 | `recordAcquisition(purchase_task_id, listing_id, quantity, purchase_price)` + `PURCHASE_COMPLETED` consumer, sourcing `listing_id`/`quantity` from `PurchaseOutcome`. | `services/inventory-service/src/handlers/event_handlers.py` | 12.1, 10.5 | End-to-end from published `PURCHASE_COMPLETED` to a correct `inventory_items` row. | Standard |
| 12.3 | Dockerfile, compose wiring, tests including a duplicate-event replay test. | `services/inventory-service/*` | 12.1, 12.2 | Green in CI. | Standard |

**Milestone M5** reached at the end of this sprint (§4).

---

### Sprint 13 — API Gateway

**Goal:** Read/observe/operate surface for staff and the Bot.
**Deliverables:** Full route table (`API_CONTRACTS.md`), auth, read-replica clients.
**Dependencies:** Sprints 3, 6, 8, 9, 12.
**Definition of Done:** Every endpoint in `API_CONTRACTS.md` §1-6 returns the documented DTO shape and status codes per `ERROR_CODES.md`.
**Acceptance Criteria:** No Gateway code path writes to a table it doesn't own; `PATCH /accounts/{id}/status` rejects out-of-scope target statuses with 400.

| # | Objective | Files Involved | Dependencies | Definition of Done | Review Checklist |
|---|---|---|---|---|---|
| 13.1 | Auth middleware: staff bearer session + internal service token. | `services/api-gateway/src/auth/*.py` | 1.x | Unauthenticated staff-only route -> 401; authenticated non-staff mutation -> 403. | Standard |
| 13.2 | Read-replica/direct-query clients per owning service (read-only). | `services/api-gateway/src/clients/*.py` | 3.7, 8.8, 9.7, 12.3 | Each client reads its target's tables and cannot execute a write (enforced via read-only DB role). | Standard |
| 13.3 | `/deals` routes (`GET /deals`, `/deals/{id}`, `/deals/{id}/card`). | `services/api-gateway/src/routes/deals.py` | 13.2 | Response shapes match `DealSummaryDTO`/`DealDetailDTO`/`DealCardDTO` exactly. | Standard |
| 13.4 | `/orders` routes. | `services/api-gateway/src/routes/orders.py` | 13.2 | Response matches `OrderDetailDTO`; confirm no `POST /orders` route exists. | Standard |
| 13.5 | `/inventory` routes, `PATCH` returns 501. | `services/api-gateway/src/routes/inventory.py` | 13.2 | `PATCH` returns 501 exactly, not 404/405. | Standard |
| 13.6 | `/accounts` routes incl. `PATCH /accounts/{id}/status` delegating to Account Service's status_updater (8.7) via event, not a direct write. | `services/api-gateway/src/routes/accounts.py` | 13.2, 8.7 | Out-of-scope target status -> 400 `VALID_*`. | Standard |
| 13.7 | `/scoring-config`, `/health`, `/events/dead-letters` + replay. | `services/api-gateway/src/routes/scoring_config.py`, `health.py`, `events.py` | 13.2 | Replay republishes with a fresh `event_id`; original dead-letter record untouched. | Standard |
| 13.8 | Global `ErrorResponse` formatting + HTTP status mapping, wired centrally. | `services/api-gateway/src/main.py`, `services/api-gateway/src/dtos/error_response.py` | 13.3-13.7 | Every error path across every route returns the exact `ErrorResponse` shape (`DTOS.md` §2). | Standard |
| 13.9 | Dockerfile, compose wiring, Nginx reverse-proxy config, tests. | `services/api-gateway/*`, `infra/nginx/*` | 13.1-13.8 | Green in CI; `nginx -t` validates config. | Standard |

---

### Sprint 14 — Admin Dashboard (frontend)

**Goal:** Staff-facing operability.
**Deliverables:** Staff-authenticated app covering deals/orders/inventory/accounts/scoring-config/dead-letters.
**Dependencies:** Sprint 13.
**Definition of Done:** Every `GET`/`PATCH`/`PUT` route in `API_CONTRACTS.md` has a UI surface; no direct DB access from the frontend.
**Acceptance Criteria:** Staff login gates every mutating action; a non-staff session cannot reach account-status or scoring-config mutation UI.

**Note:** the frontend framework is not specified anywhere in the frozen ZIP_13 contracts — see "Known Gaps" §7. Task 14.1 below records that decision procedurally; it does not redesign or invent architecture, it closes an implementation-detail gap the frozen docs left open.

| # | Objective | Files Involved | Dependencies | Definition of Done | Review Checklist |
|---|---|---|---|---|---|
| 14.1 | Record the frontend-framework choice (a short note in this roadmap's "Known Gaps" §7, not a ZIP_13 edit) and scaffold the chosen framework's project skeleton. | `admin-dashboard/*` | 13.9 | `npm run dev` (or equivalent) serves a blank authenticated shell against a local Gateway. | Standard |
| 14.2 | Staff auth flow: login, bearer token storage, route guard. | `admin-dashboard/src/auth/*` | 14.1 | Unauthenticated visit to any dashboard route redirects to login. | Standard |
| 14.3 | Deals list + detail views. | `admin-dashboard/src/pages/deals/*` | 14.2 | Pagination, `status`/`marketplace` filters work against the live Gateway. | Standard |
| 14.4 | Orders list + detail views. | `admin-dashboard/src/pages/orders/*` | 14.2 | Same pattern as 14.3 for orders. | Standard |
| 14.5 | Inventory list (read-only; edit UI stubbed/disabled, matches the Gateway's 501). | `admin-dashboard/src/pages/inventory/*` | 14.2 | No functioning edit UI is shipped for a 501 endpoint. | Standard |
| 14.6 | Accounts list/detail + status-update action. | `admin-dashboard/src/pages/accounts/*` | 14.2 | Status-update form only offers the allowed target statuses (`API_CONTRACTS.md` §4), not the full enum. | Standard |
| 14.7 | Scoring-config view/edit + dead-letter list/replay views. | `admin-dashboard/src/pages/scoring-config/*`, `admin-dashboard/src/pages/dead-letters/*` | 14.2 | Replay action requires an explicit confirmation step before firing. | Standard |
| 14.8 | End-to-end UI test pass + Dockerfile/compose wiring + Nginx static serving. | `admin-dashboard/tests/*`, `admin-dashboard/Dockerfile`, `infra/nginx/*` | 14.2-14.7 | Green in CI; `docker compose up admin-dashboard` serves the built app behind Nginx. | Standard |

---

### Sprint 15 — ML Service (stretch, lowest priority for MVP)

**Goal:** Training-data export, no inference in MVP scope.
**Deliverables:** `exportTrainingData()` batch job.
**Dependencies:** Sprints 1, 12.
**Definition of Done:** Batch job produces rows matching `TrainingFeatureRowDTO` for a given date range.
**Acceptance Criteria:** The job reads only `events` (its sanctioned exception, `SERVICE_INTERFACES.md` §11) and no other service's table.

| # | Objective | Files Involved | Dependencies | Definition of Done | Review Checklist |
|---|---|---|---|---|---|
| 15.1 | `events` table batch reader with date-range filtering. | `services/ml-service/src/export/reader.py` | 1.6 | Query plan uses `idx_events_produced_at`, confirmed via `EXPLAIN`. | Standard |
| 15.2 | Feature extraction: raw event sequences -> `TrainingFeatureRowDTO`. | `services/ml-service/src/export/training_data_export.py` | 15.1 | Output schema matches `DTOS.md` §5 exactly. | Standard |
| 15.3 | `exportTrainingData(date_range)` entrypoint + scheduled batch job wiring. | `services/ml-service/src/jobs/*.py` | 15.2 | A manual invocation over a known fixture range produces the expected row count. | Standard |
| 15.4 | Dockerfile, compose wiring, tests. | `services/ml-service/*` | 15.1-15.3 | Green in CI. | Standard |

**Milestone M6** reached once Sprints 14 and 15 are both complete (§4).

---

### Sprint 16 — Integration, Hardening & Release

**Goal:** Prove the whole system works together and is safe to ship.
**Deliverables:** Full E2E suite, dead-letter replay proof, security/stress/release-checklist pass (or explicit gap log).
**Dependencies:** all prior sprints.
**Definition of Done:** A single scripted run drives a deal from `LISTING_DISCOVERED` to an `inventory_items` row and a Dashboard-visible order, across every service, in the compose stack, with zero manual intervention.
**Acceptance Criteria:** Every `ERROR_CODES.md` retryable path has a test forcing it at least once; every non-retryable path has a test confirming no retry occurs.

| # | Objective | Files Involved | Dependencies | Definition of Done | Review Checklist |
|---|---|---|---|---|---|
| 16.1 | Full happy-path E2E test: all 11 services, one marketplace, real compose stack, only the marketplace HTTP layer mocked. | `tests/e2e/happy_path_test.py` | all prior sprints | Test green, asserts final state in every owning table. | Standard |
| 16.2 | Failure-path E2E tests: `PLAN_NO_ACCOUNTS`, `PURCH_PRICE_MISMATCH`, retry-exhaustion-to-`DEAD_LETTERED`, revalidation timeout. | `tests/e2e/failure_paths_test.py` | 16.1 | Each scenario reaches its documented terminal state. | Standard |
| 16.3 | Dead-letter replay E2E: force a dead-letter, replay via the Gateway endpoint, confirm reprocessing with a fresh `event_id`. | `tests/e2e/dead_letter_replay_test.py` | 16.2 | Original dead-letter record persists unchanged; replayed event processes successfully. | Standard |
| 16.4 | Security pass per `ZIP_11/SECURITY.md`. If that document is still empty at this point, log it as an open gap in §7 rather than skip it silently. | this document, §7 | 16.1 | Checklist fully executed and signed off, or its emptiness explicitly logged as a release-blocking gap. | Standard |
| 16.5 | Load/stress pass per `ZIP_11/STRESS_TESTING.md` (same caveat as 16.4). | this document, §7 | 16.1 | Same pattern as 16.4. | Standard |
| 16.6 | `ZIP_11/RELEASE_CHECKLIST.md` walkthrough (same caveat as 16.4). | this document, §7 | 16.1-16.5 | Checklist fully executed, or its emptiness logged as a release-blocking gap. | Standard |
| 16.7 | Final documentation sync: `CURRENT_STATE.json` per ZIP updated to reflect actual completion, `CHANGELOG.md` per touched ZIP updated. | `ZIP_*/CURRENT_STATE.json`, `ZIP_*/CHANGELOG.md` | 16.1 | State files reflect reality, not aspiration. | Standard |

**Milestone M7** reached at the end of this sprint (§4).

---

## 7. Known Gaps (Recorded, Not Fixed Here)

Per this document's own scope rules: architecture, schema, events, API contracts, DTOs, service interfaces, validation rules, and state transitions are frozen and out of bounds for this roadmap. The following gaps exist in the surrounding (non-ZIP_13) documentation and were surfaced while grounding this roadmap. They are recorded, not resolved — resolving them is out of scope for this document.

1. **Admin Dashboard frontend framework is unspecified.** `API_CONTRACTS.md` defines the full REST surface the Dashboard consumes, but no ZIP states a frontend framework/language. Sprint 14, Task 14.1 is where this must be decided procedurally before that sprint's work can begin — track the decision there, not as an architecture change.
2. **ZIP_10_INFRASTRUCTURE is entirely empty stub files** (`CI_CD.md`, `DOCKER_COMPOSE.md`, `DOCKER.md`, `SECRETS.md`, `MONITORING.md`, `LOGGING.md`, `CLOUD.md`, `NGINX.md`, `POSTGRESQL.md`, `REDIS.md`, `FASTAPI.md`, `KAFKA.md`, `BACKUP_RECOVERY.md`, `DEPLOYMENT.md` all 0 lines). This roadmap assumes Docker Compose for local dev (consistent with `ZIP_12/DEPENDENCY_GRAPH.md` §4's citation of `ZIP_10/DOCKER_COMPOSE.md`, even though that file's actual content doesn't exist yet) and Alembic for migrations (per the same source). CI provider, secrets-manager product, monitoring/logging stack, cloud/hosting target, and backup/recovery strategy are all undecided. Sprint 0 Task 0.5 and Sprint 16 Tasks 16.4-16.6 will need these decisions made (by whoever owns infra strategy) before they can be executed as more than a skeleton.
3. **ZIP_11_TESTING's `SECURITY.md`, `STRESS_TESTING.md`, and `RELEASE_CHECKLIST.md` are empty stubs.** Sprint 16 references them; if they remain empty by Sprint 16, Tasks 16.4-16.6 cannot be "executed," only logged as a blocking gap, per those tasks' own Definition of Done.
4. **Most of ZIP_12_AI_ENGINEERING_SYSTEM is empty stub files**, including `BOOT_SEQUENCE.md`, `AI_CONTEXT_MANAGEMENT.md`, `CHECKLISTS.md`, and `SPRINT_GUIDES.md`, despite `MASTER_STARTER_PROMPT.md` (13 lines, populated) instructing a reader to consult `BOOT_SEQUENCE.md` first. `CLAUDE_WORKFLOW.md` (this ZIP) was written to actually fill that operational role rather than wait on those stubs; it does not edit them.
5. **`ZIP_12/DEPENDENCY_GRAPH.md` §6 lists its own known gaps** (event names disagreeing across older ZIP_05-07 docs, three services missing from an older runtime diagram, revalidation's owning service unnamed at the time). All three are already resolved in `ZIP_13_ENGINEERING_CONTRACTS` (which supersedes on every point of conflict per its own README) — this roadmap is built against ZIP_13's resolved version throughout, not the older diagram.
