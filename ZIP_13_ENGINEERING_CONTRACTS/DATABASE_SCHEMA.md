# Database Schema

Full DDL for all thirteen ZIP_03 tables plus the three tables required by
ZIP_03 §"Open Points" (inventory, bot conversation state, processed-events
dedup). Resolves Q18a, Q26, Q27, Q29, Q31, Q53, Q54, Q55.

All timestamps `timestamptz`. All money integer minor units (paise). All
primary keys UUID v4 (`gen_random_uuid()`) except `events` (see §14) and
lookup tables `brands`/`marketplaces` (surrogate UUID too — ADR-011 applies
with no exception; resolves Q29's "Brand/Marketplace/OrderItem/PriceHistory/
Account/Event" ambiguity: all get UUID PKs, `events` additionally gets a
monotonic `seq` for stream ordering).

---

## 1. brands

```sql
CREATE TABLE brands (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  name          VARCHAR(200) NOT NULL UNIQUE,
  tier          brand_tier NOT NULL DEFAULT 'STANDARD',
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

## 2. marketplaces

```sql
CREATE TABLE marketplaces (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  code          marketplace_code NOT NULL UNIQUE,
  display_name  VARCHAR(50) NOT NULL,
  base_url      VARCHAR(500) NOT NULL,
  is_active     BOOLEAN NOT NULL DEFAULT true,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- Seed row per marketplace_code value. No dynamic inserts at runtime.
```

## 3. products

```sql
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
```

## 4. listings

Marketplace-specific offer for a product. External marketplace ID lives here
(ADR-011), never as the PK.

```sql
CREATE TABLE listings (
  id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  product_id            UUID NOT NULL REFERENCES products(id),
  marketplace_id        UUID NOT NULL REFERENCES marketplaces(id),
  external_listing_id   VARCHAR(200) NOT NULL,  -- ASIN, FSN, marketplace SKU, etc.
  url                   VARCHAR(1000) NOT NULL,
  current_price         INTEGER NOT NULL,        -- paise
  currency              currency_code NOT NULL DEFAULT 'INR',
  mrp                   INTEGER,                 -- paise, nullable if unknown
  rating                NUMERIC(2,1),             -- 0.0-5.0, DEAL_SCORING.md input
  review_count          INTEGER,
  in_stock              BOOLEAN NOT NULL DEFAULT true,
  last_scanned_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (marketplace_id, external_listing_id)
);
CREATE INDEX idx_listings_product ON listings(product_id);
CREATE INDEX idx_listings_marketplace ON listings(marketplace_id);
CREATE INDEX idx_listings_last_scanned ON listings(last_scanned_at);
```

## 5. price_history

**Resolves Q26: attaches to `listing_id`, not `product_id`.** Prices are
marketplace-specific (a product's Amazon price and Flipkart price diverge);
attaching to Product would silently merge two different price series.
Immutable — rows are never updated, only inserted (`ZIP_03/PRICE_HISTORY_DESIGN.md`).

```sql
CREATE TABLE price_history (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  listing_id    UUID NOT NULL REFERENCES listings(id),
  price         INTEGER NOT NULL,   -- paise
  in_stock      BOOLEAN NOT NULL,
  observed_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_price_history_listing_time ON price_history(listing_id, observed_at DESC);
-- lowest_price / first_seen / last_seen are computed via window query, not stored columns.
```

## 6. deals

```sql
CREATE TABLE deals (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  listing_id        UUID NOT NULL REFERENCES listings(id),
  status            deal_status NOT NULL DEFAULT 'SCORED',
  score             NUMERIC(5,2) NOT NULL,        -- 0-100, DEAL_SCORING.md output
  score_breakdown   JSONB NOT NULL,                -- per-factor contribution, immutable snapshot
  detected_price    INTEGER NOT NULL,              -- paise, price at detection time
  reference_price   INTEGER NOT NULL,              -- paise, the price it's discounted against
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
-- enforced at application layer in the Deal Engine (partial unique index
-- on a mutable status set is not practical in Postgres without a generated
-- column; Deal Engine enforces via SELECT ... FOR UPDATE before insert).
```

## 7. telegram_users

```sql
CREATE TABLE telegram_users (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  telegram_chat_id  BIGINT NOT NULL UNIQUE,
  username          VARCHAR(100),
  display_name      VARCHAR(200),
  timezone          VARCHAR(50) NOT NULL DEFAULT 'Asia/Kolkata',
  status            VARCHAR(20) NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE','BLOCKED')),
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

## 8. user_interests

```sql
CREATE TABLE user_interests (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  deal_id           UUID NOT NULL REFERENCES deals(id),
  telegram_user_id  UUID NOT NULL REFERENCES telegram_users(id),
  action            user_interest_action NOT NULL,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_user_interests_deal ON user_interests(deal_id);
CREATE INDEX idx_user_interests_user ON user_interests(telegram_user_id);
```

## 9. accounts

**Resolves Q27: `marketplace_id` FK is mandatory, not nullable.** An account
is credentials for exactly one marketplace (`ZIP_08/SESSION_PERSISTENCE.md`
forbids cross-marketplace session sharing).

```sql
CREATE TABLE accounts (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  marketplace_id    UUID NOT NULL REFERENCES marketplaces(id),
  label             VARCHAR(100) NOT NULL,          -- internal alias, never the login email in logs
  credentials_ref    VARCHAR(200) NOT NULL,          -- secrets-manager reference, not the secret itself
  status            account_status NOT NULL DEFAULT 'ACTIVE',
  health_score      INTEGER NOT NULL DEFAULT 100 CHECK (health_score BETWEEN 0 AND 100),
  cooldown_until    TIMESTAMPTZ,
  daily_spend_cap   INTEGER NOT NULL,                -- paise
  daily_spend_used  INTEGER NOT NULL DEFAULT 0,       -- paise, reset by daily job
  last_used_at      TIMESTAMPTZ,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_accounts_marketplace ON accounts(marketplace_id);
CREATE INDEX idx_accounts_status ON accounts(status);
```

## 10. orders

```sql
CREATE TABLE orders (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  deal_id           UUID NOT NULL REFERENCES deals(id),
  telegram_user_id  UUID NOT NULL REFERENCES telegram_users(id),
  correlation_id    UUID NOT NULL,                   -- shared across the whole purchase workflow
  requested_quantity INTEGER NOT NULL CHECK (requested_quantity > 0),
  fulfilled_quantity INTEGER NOT NULL DEFAULT 0,
  status            order_status NOT NULL DEFAULT 'REQUESTED',
  total_amount      INTEGER,                          -- paise, set once planned
  failure_reason    VARCHAR(500),
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_orders_deal ON orders(deal_id);
CREATE INDEX idx_orders_user ON orders(telegram_user_id);
CREATE INDEX idx_orders_correlation ON orders(correlation_id);
```

## 11. order_items

```sql
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
```

## 12. purchase_tasks

One row per account allocated to an order. Carries its own immutable UUID
(ADR-011, ER_DIAGRAM.md §3) independent of `order_items`, because a single
`order_item` quantity may be split across several accounts.

```sql
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
```

## 13. events

Sole write path: Event Store Consumer (ADR-010). Append-only.

```sql
CREATE TABLE events (
  seq             BIGSERIAL PRIMARY KEY,   -- exception to UUID-PK rule: ordering requires monotonicity
  event_id        UUID NOT NULL UNIQUE,     -- from the envelope, doubles as idempotency key
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
```

## 14. inventory_items

Resolves Q31 for the MVP scope (ADR-012: purchase tracking only). Phase-2
columns (`resale_price`, `profit`) are added nullable now so the migration
that activates Phase 2 is additive, not destructive.

```sql
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
```

## 15. bot_conversations

Resolves Q55. One row per Telegram user, mutable single-row conversation
state machine (`STATE_TRANSITIONS.md` §4). Message mapping and audit log are
separate tables (§16, §17) rather than JSONB blobs here, so they can be
queried and retained independently.

```sql
CREATE TABLE bot_conversations (
  telegram_user_id  UUID PRIMARY KEY REFERENCES telegram_users(id),
  state             conversation_state NOT NULL DEFAULT 'IDLE',
  active_deal_id    UUID REFERENCES deals(id),
  active_order_id   UUID REFERENCES orders(id),
  pending_action    JSONB,                -- e.g. {"type":"quantity_prompt","deal_id":...}
  state_entered_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
```

## 16. bot_messages

Maps a sent Telegram message to the deal/order it represents, so button
callbacks can be resolved back to a row without re-parsing message text.

```sql
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
```

## 17. bot_audit_log

```sql
CREATE TABLE bot_audit_log (
  id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  telegram_user_id  UUID NOT NULL REFERENCES telegram_users(id),
  action            VARCHAR(100) NOT NULL,   -- 'BUTTON_CLICKED','COMMAND_RECEIVED','MESSAGE_SENT'
  detail            JSONB NOT NULL DEFAULT '{}',
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX idx_bot_audit_user_time ON bot_audit_log(telegram_user_id, created_at DESC);
```

## 18. processed_events

Consumer-side idempotency ledger (resolves Q17). One row per
(consumer_service, event_id). A consumer checks this table before acting on
an event; absence of a row means "not yet processed."

```sql
CREATE TABLE processed_events (
  consumer_service  event_producer_service NOT NULL,
  event_id          UUID NOT NULL,
  processed_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (consumer_service, event_id)
);
-- TTL: rows older than 7 days are purged by a daily job. Redis Streams
-- consumer-group ack alone is not sufficient because at-least-once delivery
-- can redeliver after a consumer crash post-ack-pending; this table is the
-- durable backstop.
```

---

## Table ownership (resolves Q53)

| Table | Owning service |
|---|---|
| `brands`, `marketplaces`, `products`, `listings`, `price_history`, `deals` | Deal Engine |
| `telegram_users`, `user_interests`, `bot_conversations`, `bot_messages`, `bot_audit_log` | Telegram Bot |
| `accounts` | Account Service |
| `orders`, `order_items`, `purchase_tasks` | Order Planner |
| `inventory_items` | Inventory Service |
| `events` | Event Store Consumer (sole writer, ADR-010) |
| `processed_events` | Owned per-row by whichever service's name is in `consumer_service`; each service manages only its own rows |

No service queries a table it does not own (ADR-009). Cross-service data
needs are satisfied by consuming events, never by joining across ownership
boundaries.
