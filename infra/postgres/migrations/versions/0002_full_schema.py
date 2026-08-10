"""full schema — all 18 tables, enums, FKs and indexes

Revision ID: 0002_full_schema
Revises: 0001_baseline
Create Date: Sprint 1 Task 1.6

Transcribes `ZIP_13_ENGINEERING_CONTRACTS/DATABASE_SCHEMA.md` §1-§18 and
`ENUMS.md` verbatim. The DDL is executed as raw SQL, copied statement for
statement out of those documents, because the task's Definition of Done is a
line-by-line diff of this migration against the contract — a SQLAlchemy
`op.create_table()` rendering would have to be mentally re-compiled back into
DDL before it could be diffed at all.

Enum types are created first: every enum in `ENUMS.md` becomes a Postgres
`CREATE TYPE ... AS ENUM`, including `account_health_band` and `error_severity`,
which no column in §1-§18 references. `ENUMS.md` defines them as database types
regardless, and the sprint's Definition of Done is "all 18 tables + all enums
exist exactly per `DATABASE_SCHEMA.md`/`ENUMS.md`".

`gen_random_uuid()` is core in PostgreSQL 13+ (the compose image is 16), so no
`pgcrypto` extension is created.
"""

from __future__ import annotations

from alembic import op

revision = "0002_full_schema"
down_revision = "0001_baseline"
branch_labels = None
depends_on = None


# --- ENUMS.md ---------------------------------------------------------------
# Order of members within each type is the order in ENUMS.md; Postgres orders
# enum values by declaration, so it is not cosmetic.
ENUM_TYPES = """
CREATE TYPE marketplace_code AS ENUM ('AMAZON','FLIPKART','MYNTRA','NYKAA');

CREATE TYPE deal_status AS ENUM (
  'SCORED','NOTIFIED','DEAL_SENT','INTERESTED','REVALIDATING','CONFIRMED',
  'PRICE_CHANGED','SOLD_OUT','WATCHING','ORDERED','IGNORED','EXPIRED',
  'PRICE_CHANGED_REJECTED','SOLD_OUT_REJECTED'
);

CREATE TYPE order_status AS ENUM (
  'REQUESTED','PLANNING_FAILED','PLANNED','EXECUTING','PARTIAL','COMPLETED',
  'FAILED','CANCELLED'
);

CREATE TYPE order_item_status AS ENUM (
  'PENDING','EXECUTING','COMPLETED','FAILED','CANCELLED'
);

CREATE TYPE purchase_task_status AS ENUM (
  'CREATED','ASSIGNED','EXECUTING','COMPLETED','FAILED','RETRYING','DEAD_LETTERED'
);

CREATE TYPE account_status AS ENUM (
  'ACTIVE','WARNING','COOLDOWN','SUSPENDED','BANNED','DISABLED_MANUAL'
);

CREATE TYPE account_health_band AS ENUM ('HEALTHY','WARNING','CRITICAL','ZERO');

CREATE TYPE conversation_state AS ENUM (
  'IDLE','AWAITING_QUANTITY','AWAITING_CONFIRMATION','AWAITING_ADMIN_INPUT'
);

CREATE TYPE user_interest_action AS ENUM ('INTERESTED','IGNORED','WATCH_LATER');

CREATE TYPE inventory_item_status AS ENUM ('PURCHASED','DELIVERED','RETURNED','RESOLD');

CREATE TYPE event_producer_service AS ENUM (
  'marketplace-connector','deal-engine','revalidation-service','telegram-bot',
  'order-planner','account-service','inventory-service','purchase-agent',
  'event-store-consumer','api-gateway','ml-service'
);

CREATE TYPE currency_code AS ENUM ('INR');

CREATE TYPE error_severity AS ENUM ('INFO','WARNING','ERROR','CRITICAL');

CREATE TYPE brand_tier AS ENUM ('PREMIUM','STANDARD','UNBRANDED');
"""

ENUM_TYPE_NAMES = (
    "marketplace_code",
    "deal_status",
    "order_status",
    "order_item_status",
    "purchase_task_status",
    "account_status",
    "account_health_band",
    "conversation_state",
    "user_interest_action",
    "inventory_item_status",
    "event_producer_service",
    "currency_code",
    "error_severity",
    "brand_tier",
)

# --- DATABASE_SCHEMA.md §1-§18 ----------------------------------------------
# Tables are created in FK dependency order; within that constraint the order
# follows the document's numbering.
TABLES = """
-- §1 brands
CREATE TABLE brands (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name          VARCHAR(200) NOT NULL UNIQUE,
  tier          brand_tier NOT NULL DEFAULT 'STANDARD',
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- §2 marketplaces. Seed row per marketplace_code value (scripts/seed_marketplaces.py);
-- no dynamic inserts at runtime.
CREATE TABLE marketplaces (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  code          marketplace_code NOT NULL UNIQUE,
  display_name  VARCHAR(50) NOT NULL,
  base_url      VARCHAR(500) NOT NULL,
  is_active     BOOLEAN NOT NULL DEFAULT true,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- §3 products
CREATE TABLE products (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  brand_id        UUID REFERENCES brands(id),
  canonical_title VARCHAR(500) NOT NULL,
  category        VARCHAR(200),
  subcategory     VARCHAR(200),
  attributes      JSONB NOT NULL DEFAULT '{}',  -- size/color/variant map, CANONICAL_MODELS.md
  image_url       VARCHAR(1000),
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_products_brand ON products(brand_id);
CREATE INDEX idx_products_category ON products(category);

-- §4 listings. External marketplace ID lives here (ADR-011), never as the PK.
CREATE TABLE listings (
  id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  product_id            UUID NOT NULL REFERENCES products(id),
  marketplace_id        UUID NOT NULL REFERENCES marketplaces(id),
  external_listing_id   VARCHAR(200) NOT NULL,  -- ASIN, FSN, marketplace SKU, etc.
  url                   VARCHAR(1000) NOT NULL,
  current_price         INTEGER NOT NULL,        -- paise
  currency              currency_code NOT NULL DEFAULT 'INR',
  mrp                   INTEGER,                 -- paise, nullable if unknown
  rating                NUMERIC(2,1),            -- 0.0-5.0, DEAL_SCORING.md input
  review_count          INTEGER,
  in_stock              BOOLEAN NOT NULL DEFAULT true,
  last_scanned_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (marketplace_id, external_listing_id)
);
CREATE INDEX idx_listings_product ON listings(product_id);
CREATE INDEX idx_listings_marketplace ON listings(marketplace_id);
CREATE INDEX idx_listings_last_scanned ON listings(last_scanned_at);

-- §5 price_history. Attaches to listing_id, not product_id (resolves Q26).
-- Immutable: rows are never updated, only inserted.
CREATE TABLE price_history (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  listing_id    UUID NOT NULL REFERENCES listings(id),
  price         INTEGER NOT NULL,   -- paise
  in_stock      BOOLEAN NOT NULL,
  observed_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_price_history_listing_time ON price_history(listing_id, observed_at DESC);
-- lowest_price / first_seen / last_seen are computed via window query, not stored columns.

-- §6 deals
CREATE TABLE deals (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  listing_id        UUID NOT NULL REFERENCES listings(id),
  status            deal_status NOT NULL DEFAULT 'SCORED',
  score             NUMERIC(5,2) NOT NULL,        -- 0-100, DEAL_SCORING.md output
  score_breakdown   JSONB NOT NULL,               -- per-factor contribution, immutable snapshot
  detected_price    INTEGER NOT NULL,             -- paise, price at detection time
  reference_price   INTEGER NOT NULL,             -- paise, the price it's discounted against
  discount_pct      NUMERIC(5,2) NOT NULL,
  notified_at       TIMESTAMPTZ,
  expires_at        TIMESTAMPTZ NOT NULL,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_deals_listing ON deals(listing_id);
CREATE INDEX idx_deals_status ON deals(status);
CREATE INDEX idx_deals_expires ON deals(expires_at) WHERE status NOT IN ('EXPIRED','IGNORED','ORDERED');
-- Dedup rule: at most one deal per listing_id with status NOT IN
-- ('EXPIRED','IGNORED','ORDERED','PRICE_CHANGED_REJECTED','SOLD_OUT_REJECTED')
-- enforced at application layer in the Deal Engine (Sprint 3 Task 3.4,
-- SELECT ... FOR UPDATE before insert), not by a partial unique index.

-- §7 telegram_users
CREATE TABLE telegram_users (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  telegram_chat_id  BIGINT NOT NULL UNIQUE,
  username          VARCHAR(100),
  display_name      VARCHAR(200),
  timezone          VARCHAR(50) NOT NULL DEFAULT 'Asia/Kolkata',
  status            VARCHAR(20) NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE','BLOCKED')),
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- §8 user_interests
CREATE TABLE user_interests (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  deal_id           UUID NOT NULL REFERENCES deals(id),
  telegram_user_id  UUID NOT NULL REFERENCES telegram_users(id),
  action            user_interest_action NOT NULL,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_user_interests_deal ON user_interests(deal_id);
CREATE INDEX idx_user_interests_user ON user_interests(telegram_user_id);

-- §9 accounts. marketplace_id is mandatory, not nullable (resolves Q27).
-- credentials_ref is a secrets-manager reference, never the secret itself.
CREATE TABLE accounts (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  marketplace_id    UUID NOT NULL REFERENCES marketplaces(id),
  label             VARCHAR(100) NOT NULL,           -- internal alias, never the login email in logs
  credentials_ref   VARCHAR(200) NOT NULL,           -- secrets-manager reference, not the secret itself
  status            account_status NOT NULL DEFAULT 'ACTIVE',
  health_score      INTEGER NOT NULL DEFAULT 100 CHECK (health_score BETWEEN 0 AND 100),
  cooldown_until    TIMESTAMPTZ,
  daily_spend_cap   INTEGER NOT NULL,                -- paise
  daily_spend_used  INTEGER NOT NULL DEFAULT 0,      -- paise, reset by daily job
  last_used_at      TIMESTAMPTZ,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_accounts_marketplace ON accounts(marketplace_id);
CREATE INDEX idx_accounts_status ON accounts(status);

-- §10 orders
CREATE TABLE orders (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  deal_id           UUID NOT NULL REFERENCES deals(id),
  telegram_user_id  UUID NOT NULL REFERENCES telegram_users(id),
  correlation_id    UUID NOT NULL,                   -- shared across the whole purchase workflow
  requested_quantity INTEGER NOT NULL CHECK (requested_quantity > 0),
  fulfilled_quantity INTEGER NOT NULL DEFAULT 0,
  status            order_status NOT NULL DEFAULT 'REQUESTED',
  total_amount      INTEGER,                         -- paise, set once planned
  failure_reason    VARCHAR(500),
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_orders_deal ON orders(deal_id);
CREATE INDEX idx_orders_user ON orders(telegram_user_id);
CREATE INDEX idx_orders_correlation ON orders(correlation_id);

-- §11 order_items
CREATE TABLE order_items (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  order_id      UUID NOT NULL REFERENCES orders(id),
  listing_id    UUID NOT NULL REFERENCES listings(id),
  quantity      INTEGER NOT NULL CHECK (quantity > 0),
  unit_price    INTEGER NOT NULL,   -- paise, price at planning time
  status        order_item_status NOT NULL DEFAULT 'PENDING',
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_order_items_order ON order_items(order_id);

-- §12 purchase_tasks. One row per account allocated to an order, with its own
-- immutable UUID independent of order_items (ADR-011).
CREATE TABLE purchase_tasks (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  order_id        UUID NOT NULL REFERENCES orders(id),
  order_item_id   UUID NOT NULL REFERENCES order_items(id),
  account_id      UUID NOT NULL REFERENCES accounts(id),
  quantity        INTEGER NOT NULL CHECK (quantity > 0),
  status          purchase_task_status NOT NULL DEFAULT 'CREATED',
  attempt_count   INTEGER NOT NULL DEFAULT 0,
  marketplace_order_ref VARCHAR(200),  -- set on PURCHASE_COMPLETED
  failure_reason  VARCHAR(500),
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_purchase_tasks_order ON purchase_tasks(order_id);
CREATE INDEX idx_purchase_tasks_account ON purchase_tasks(account_id);
CREATE INDEX idx_purchase_tasks_status ON purchase_tasks(status);

-- §13 events. Sole write path: Event Store Consumer (ADR-010). Append-only.
CREATE TABLE events (
  seq             BIGSERIAL PRIMARY KEY,   -- exception to UUID-PK rule: ordering requires monotonicity
  event_id        UUID NOT NULL UNIQUE,    -- from the envelope, doubles as idempotency key
  event_type      VARCHAR(100) NOT NULL,
  version         INTEGER NOT NULL,
  correlation_id  UUID,
  producer_service event_producer_service NOT NULL,
  payload         JSONB NOT NULL,
  produced_at     TIMESTAMPTZ NOT NULL,
  stored_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_events_type ON events(event_type);
CREATE INDEX idx_events_correlation ON events(correlation_id);
CREATE INDEX idx_events_produced_at ON events(produced_at);

-- §14 inventory_items. Phase-2 columns (resale_price, profit) are nullable now
-- so the migration that activates Phase 2 is additive, not destructive.
CREATE TABLE inventory_items (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  purchase_task_id  UUID NOT NULL REFERENCES purchase_tasks(id),
  listing_id        UUID NOT NULL REFERENCES listings(id),
  quantity          INTEGER NOT NULL CHECK (quantity > 0),
  purchase_price    INTEGER NOT NULL,  -- paise
  status            inventory_item_status NOT NULL DEFAULT 'PURCHASED',
  resale_price      INTEGER,           -- paise, Phase 2, admin-entered
  profit            INTEGER,           -- paise, Phase 2, generated: resale_price - purchase_price
  acquired_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_inventory_purchase_task ON inventory_items(purchase_task_id);

-- §15 bot_conversations. One row per Telegram user, mutable single-row state
-- machine (STATE_TRANSITIONS.md §4).
CREATE TABLE bot_conversations (
  telegram_user_id  UUID PRIMARY KEY REFERENCES telegram_users(id),
  state             conversation_state NOT NULL DEFAULT 'IDLE',
  active_deal_id    UUID REFERENCES deals(id),
  active_order_id   UUID REFERENCES orders(id),
  pending_action    JSONB,               -- e.g. {"type":"quantity_prompt","deal_id":...}
  state_entered_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- §16 bot_messages
CREATE TABLE bot_messages (
  id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  telegram_user_id      UUID NOT NULL REFERENCES telegram_users(id),
  telegram_message_id   BIGINT NOT NULL,
  deal_id               UUID REFERENCES deals(id),
  order_id              UUID REFERENCES orders(id),
  message_type          VARCHAR(50) NOT NULL,  -- 'DEAL_CARD','QUANTITY_PROMPT','CONFIRMATION','STATUS_UPDATE'
  sent_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (telegram_user_id, telegram_message_id)
);
CREATE INDEX idx_bot_messages_deal ON bot_messages(deal_id);

-- §17 bot_audit_log
CREATE TABLE bot_audit_log (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  telegram_user_id  UUID NOT NULL REFERENCES telegram_users(id),
  action            VARCHAR(100) NOT NULL,   -- 'BUTTON_CLICKED','COMMAND_RECEIVED','MESSAGE_SENT'
  detail            JSONB NOT NULL DEFAULT '{}',
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_bot_audit_user_time ON bot_audit_log(telegram_user_id, created_at DESC);

-- §18 processed_events. Consumer-side idempotency ledger (resolves Q17).
-- TTL: rows older than 7 days are purged by a daily job.
CREATE TABLE processed_events (
  consumer_service  event_producer_service NOT NULL,
  event_id          UUID NOT NULL,
  processed_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (consumer_service, event_id)
);
"""

# Reverse creation order, so every FK child is gone before its parent.
TABLE_NAMES_DROP_ORDER = (
    "processed_events",
    "bot_audit_log",
    "bot_messages",
    "bot_conversations",
    "inventory_items",
    "events",
    "purchase_tasks",
    "order_items",
    "orders",
    "accounts",
    "user_interests",
    "telegram_users",
    "deals",
    "price_history",
    "listings",
    "products",
    "marketplaces",
    "brands",
)


def upgrade() -> None:
    op.execute(ENUM_TYPES)
    op.execute(TABLES)


def downgrade() -> None:
    for table in TABLE_NAMES_DROP_ORDER:
        op.execute(f"DROP TABLE IF EXISTS {table}")
    for enum_type in ENUM_TYPE_NAMES:
        op.execute(f"DROP TYPE IF EXISTS {enum_type}")
