# Repository Structure

Complete production repository skeleton for the BusinessScrapper system, grounded in `ZIP_13_ENGINEERING_CONTRACTS/SERVICE_INTERFACES.md` (11 services), `DATABASE_SCHEMA.md` "Table ownership", and `EVENT_SCHEMAS.md`. Folders and filenames only — no code, no implementation. This structure should exist in full before Sprint 1 of `IMPLEMENTATION_ROADMAP.md` begins (Sprint 0 creates it).

Layout choice: **single monorepo**, one deployable Docker image per service, orchestrated by one root `docker-compose.yml`. This matches `ZIP_12/DEPENDENCY_GRAPH.md` §4's citation of a Compose-based local stack and keeps `libs/` shared code (event envelope, canonical models, enums) importable by every service without a package registry.

Everything under `ZIP_01_FOUNDATION/` through `ZIP_13_ENGINEERING_CONTRACTS/` already exists and is untouched by this structure. `ZIP_14_IMPLEMENTATION_PREP/` (this ZIP) is docs-only, no code.

---

## 1. Root

```
BuisnessScrapper/
├── ZIP_01_FOUNDATION/                 (existing, untouched)
├── ZIP_02_CORE_ARCHITECTURE/          (existing, untouched)
├── ZIP_03_DATABASE/                   (existing, untouched)
├── ZIP_04_MARKETPLACE_LAYER/          (existing, untouched)
├── ZIP_05_DEAL_INTELLIGENCE/          (existing, untouched)
├── ZIP_06_BOT_SYSTEM/                 (existing, untouched)
├── ZIP_07_ORDER_SYSTEM/               (existing, untouched)
├── ZIP_08_PURCHASE_AGENTS/            (existing, untouched)
├── ZIP_09_AI_ML/                      (existing, untouched)
├── ZIP_10_INFRASTRUCTURE/             (existing, untouched)
├── ZIP_11_TESTING/                    (existing, untouched)
├── ZIP_12_AI_ENGINEERING_SYSTEM/      (existing, untouched)
├── ZIP_13_ENGINEERING_CONTRACTS/      (existing, untouched, FROZEN)
├── ZIP_14_IMPLEMENTATION_PREP/        (existing, untouched — this ZIP)
├── services/
├── libs/
├── admin-dashboard/
├── infra/
├── scripts/
├── tests/
├── docker-compose.yml
├── docker-compose.override.yml.example
├── .env.example
├── .gitignore
├── .pre-commit-config.yaml
├── Makefile
├── pyproject.toml
└── README.md
```

---

## 2. `services/` — one directory per `SERVICE_INTERFACES.md` entry

```
services/
├── marketplace-connector/
├── deal-engine/
├── revalidation-service/
├── telegram-bot/
├── order-planner/
├── account-service/
├── purchase-agent/
├── inventory-service/
├── event-store-consumer/
├── api-gateway/
└── ml-service/
```

### 2.1 Standard internal layout — applies to: `deal-engine`, `revalidation-service`, `order-planner`, `account-service`, `inventory-service`, `event-store-consumer`, `api-gateway`, `ml-service`

```
<service-name>/
├── src/
│   ├── __init__.py
│   ├── main.py
│   ├── config.py
│   ├── handlers/
│   │   ├── __init__.py
│   │   └── event_handlers.py
│   ├── services/
│   │   └── __init__.py
│   ├── repositories/
│   │   └── __init__.py
│   └── jobs/                      (only where the service has a scheduled job — account-service, revalidation-service N/A, ml-service)
│       └── __init__.py
├── tests/
│   ├── __init__.py
│   ├── unit/
│   ├── integration/
│   └── fixtures/
├── Dockerfile
├── requirements.txt
├── pyproject.toml
├── .env.example
└── README.md
```

Per-service internal folders that differ from the plain default above:

**`deal-engine/`**
```
deal-engine/
└── src/
    ├── handlers/event_handlers.py
    ├── services/
    │   ├── brand_resolver.py
    │   ├── scorer.py
    │   └── deal_writer.py
    └── repositories/
        ├── brand_repo.py
        ├── marketplace_repo.py
        ├── product_repo.py
        ├── listing_repo.py
        ├── price_history_repo.py
        └── deal_repo.py
```

**`revalidation-service/`**
```
revalidation-service/
└── src/
    ├── handlers/event_handlers.py
    └── services/revalidator.py
```
(stateless — no `repositories/`, per `SERVICE_INTERFACES.md` §3 "Owns no tables")

**`account-service/`**
```
account-service/
└── src/
    ├── handlers/event_handlers.py
    ├── services/
    │   ├── allocator.py
    │   ├── health.py
    │   └── status_updater.py
    ├── repositories/account_repo.py
    └── jobs/reset_daily_spend.py
```

**`order-planner/`**
```
order-planner/
└── src/
    ├── handlers/event_handlers.py
    ├── services/
    │   ├── planner.py
    │   └── reconciler.py
    └── repositories/
        ├── order_repo.py
        ├── order_item_repo.py
        └── purchase_task_repo.py
```

**`inventory-service/`**
```
inventory-service/
└── src/
    ├── handlers/event_handlers.py
    └── repositories/inventory_repo.py
```

**`event-store-consumer/`**
```
event-store-consumer/
└── src/
    ├── handlers/event_handlers.py
    └── repositories/event_repo.py
```
(sole writer to `events`, ADR-010 — no `services/` layer needed beyond persistence)

**`api-gateway/`**
```
api-gateway/
└── src/
    ├── routes/
    │   ├── __init__.py
    │   ├── deals.py
    │   ├── orders.py
    │   ├── inventory.py
    │   ├── accounts.py
    │   ├── scoring_config.py
    │   ├── health.py
    │   └── events.py
    ├── auth/
    │   ├── __init__.py
    │   ├── staff_session.py
    │   └── service_token.py
    ├── clients/                    (read-only clients into each owning service's tables — ADR-009 read exception)
    │   ├── __init__.py
    │   ├── deal_engine_client.py
    │   ├── order_planner_client.py
    │   ├── account_service_client.py
    │   └── inventory_service_client.py
    └── dtos/
        ├── __init__.py
        └── error_response.py
```
(owns no tables, no `repositories/`)

**`ml-service/`**
```
ml-service/
└── src/
    ├── export/
    │   ├── __init__.py
    │   ├── reader.py
    │   └── training_data_export.py
    └── jobs/
        └── __init__.py
```
(owns no tables, batch-reads `events` directly — the one sanctioned exception, `SERVICE_INTERFACES.md` §11)

### 2.2 Multi-marketplace plugin layout — `marketplace-connector/`

```
marketplace-connector/
├── src/
│   ├── __init__.py
│   ├── main.py
│   ├── config.py
│   ├── base/
│   │   ├── __init__.py
│   │   ├── connector_interface.py
│   │   └── normalizer.py
│   └── connectors/
│       ├── __init__.py
│       ├── amazon/
│       │   ├── __init__.py
│       │   ├── connector.py
│       │   └── selectors.py
│       ├── flipkart/
│       │   ├── __init__.py
│       │   ├── connector.py
│       │   └── selectors.py
│       ├── myntra/
│       │   ├── __init__.py
│       │   ├── connector.py
│       │   └── selectors.py
│       └── nykaa/
│           ├── __init__.py
│           ├── connector.py
│           └── selectors.py
├── tests/
│   ├── __init__.py
│   ├── unit/
│   ├── integration/
│   ├── amazon/
│   ├── flipkart/
│   ├── myntra/
│   ├── nykaa/
│   └── fixtures/                  (recorded/mocked marketplace responses, ZIP_11/MARKETPLACE_MOCKING.md)
├── Dockerfile
├── requirements.txt
├── pyproject.toml
├── .env.example
└── README.md
```
(owns no tables, per `SERVICE_INTERFACES.md` §1)

### 2.3 Multi-marketplace plugin layout — `purchase-agent/`

```
purchase-agent/
├── src/
│   ├── __init__.py
│   ├── main.py
│   ├── config.py
│   ├── base/
│   │   ├── __init__.py
│   │   ├── agent_interface.py
│   │   └── retry_policy.py
│   ├── sessions/
│   │   ├── __init__.py
│   │   ├── browser_session_manager.py
│   │   └── cookie_store.py
│   ├── handlers/
│   │   ├── __init__.py
│   │   └── event_handlers.py
│   └── agents/
│       ├── __init__.py
│       ├── amazon/
│       │   ├── __init__.py
│       │   ├── agent.py
│       │   └── checkout_flow.py
│       ├── flipkart/
│       │   ├── __init__.py
│       │   ├── agent.py
│       │   └── checkout_flow.py
│       ├── myntra/
│       │   ├── __init__.py
│       │   ├── agent.py
│       │   └── checkout_flow.py
│       └── nykaa/
│           ├── __init__.py
│           ├── agent.py
│           └── checkout_flow.py
├── tests/
│   ├── __init__.py
│   ├── unit/
│   ├── integration/
│   ├── amazon/
│   ├── flipkart/
│   ├── myntra/
│   ├── nykaa/
│   └── fixtures/
├── Dockerfile                      (Playwright base image)
├── requirements.txt
├── pyproject.toml
├── .env.example
└── README.md
```
(owns no tables, all state changes go through Order Planner via events — `SERVICE_INTERFACES.md` §7)

### 2.4 `telegram-bot/` — distinct layout (conversation state machine, message templates)

```
telegram-bot/
├── src/
│   ├── __init__.py
│   ├── main.py
│   ├── config.py
│   ├── conversation/
│   │   ├── __init__.py
│   │   ├── state_machine.py
│   │   ├── handlers.py
│   │   └── timeouts.py
│   ├── messages/
│   │   ├── __init__.py
│   │   ├── templates.py
│   │   └── buttons.py
│   ├── handlers/
│   │   ├── __init__.py
│   │   └── event_handlers.py
│   └── repositories/
│       ├── __init__.py
│       ├── telegram_user_repo.py
│       ├── user_interest_repo.py
│       ├── bot_conversation_repo.py
│       ├── bot_message_repo.py
│       └── bot_audit_log_repo.py
├── tests/
│   ├── __init__.py
│   ├── unit/
│   └── integration/
├── Dockerfile
├── requirements.txt
├── pyproject.toml
├── .env.example
└── README.md
```

---

## 3. `libs/` — shared code, imported by every service, owned by no single service

```
libs/
├── event_bus/
│   ├── __init__.py
│   ├── envelope.py
│   ├── publisher.py
│   ├── consumer.py
│   ├── dedup.py
│   └── schema/
│       ├── envelope.json
│       ├── listing_discovered.json
│       ├── deal_scored.json
│       ├── user_interested.json
│       ├── deal_revalidation_request.json
│       ├── deal_revalidated.json
│       ├── purchase_requested.json
│       ├── account_allocation_request.json
│       ├── account_allocation_response.json
│       ├── purchase_task_created.json
│       ├── purchase_completed.json
│       ├── purchase_failed.json
│       ├── account_health_changed.json
│       └── event_dead_lettered.json
├── canonical_models/
│   ├── __init__.py
│   ├── canonical_product.py
│   ├── scored_deal.py
│   ├── allocation_plan.py
│   ├── revalidation_result.py
│   └── purchase_outcome.py
├── enums/
│   ├── __init__.py
│   └── enums.py
├── error_codes/
│   ├── __init__.py
│   └── error_codes.py
├── db/
│   ├── __init__.py
│   ├── engine.py
│   └── base_repository.py
└── testing/
    ├── __init__.py
    ├── fixtures.py
    └── event_test_helpers.py
```

---

## 4. `admin-dashboard/` — frontend

Framework choice is an open gap (`IMPLEMENTATION_ROADMAP.md` §7, item 1) — layout below is framework-agnostic and applies regardless of which SPA framework Sprint 14 Task 14.1 selects.

```
admin-dashboard/
├── src/
│   ├── auth/
│   ├── pages/
│   │   ├── deals/
│   │   ├── orders/
│   │   ├── inventory/
│   │   ├── accounts/
│   │   ├── scoring-config/
│   │   └── dead-letters/
│   ├── api/                        (Gateway client only — no direct DB access)
│   └── components/
├── public/
├── tests/
├── Dockerfile
├── package.json
├── .env.example
└── README.md
```

---

## 5. `infra/` — everything cross-cutting infrastructure

```
infra/
├── docker/
│   └── base-images/                (shared base Dockerfiles, e.g. Playwright base for purchase-agent)
├── postgres/
│   ├── alembic.ini
│   └── migrations/
│       ├── env.py
│       └── versions/
├── redis/
│   └── redis.conf
├── nginx/
│   ├── nginx.conf
│   └── conf.d/
└── ci/
    └── (pipeline definitions — provider TBD, `IMPLEMENTATION_ROADMAP.md` §7 item 2)
```

---

## 6. `scripts/` and `tests/`

```
scripts/
├── seed_accounts.py
├── seed_marketplaces.py
└── replay_dead_letter.py

tests/
└── e2e/
    ├── happy_path_test.py
    ├── failure_paths_test.py
    └── dead_letter_replay_test.py
```

Per-service unit/integration tests live inside each service's own `tests/` directory (§2). `tests/e2e/` at root is reserved for cross-service scenarios that exercise the full compose stack (`IMPLEMENTATION_ROADMAP.md` Sprint 16).

---

## 7. Root-file purposes (no content shown — filenames only)

| File | Purpose |
|---|---|
| `docker-compose.yml` | Orchestrates Postgres, Redis, Nginx, and every service in `services/` + `admin-dashboard/` for local/dev. |
| `docker-compose.override.yml.example` | Template for developer-local overrides (ports, volumes); never committed with real values. |
| `.env.example` | Every env var referenced across all services, placeholder values only. |
| `.gitignore` | Standard exclusions plus `.env`, `*.db`, browser session/cookie storage paths. |
| `.pre-commit-config.yaml` | Lint/format/type-check hooks, one config for the whole monorepo. |
| `Makefile` | Common commands (`make up`, `make migrate`, `make test`, `make lint`) — thin wrappers, no logic of their own. |
| `pyproject.toml` | Root-level lint/format/type-check tool configuration shared across services. |
| `README.md` | Points a new reader to `ZIP_13_ENGINEERING_CONTRACTS/README.md` (contracts) and `ZIP_14_IMPLEMENTATION_PREP/CLAUDE_WORKFLOW.md` (how to work in this repo). |
