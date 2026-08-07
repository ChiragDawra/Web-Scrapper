# ER Diagram

Canonical entity set and relationships. Supersedes the prior entity list,
which omitted `Listing` even though `TABLES.md` and `RELATIONSHIPS.md` both
depend on it.

---

## 1. Entities

Both `Listing` and `UserInterest` exist. Neither replaces the other.

| Entity | Table | Notes |
|---|---|---|
| Brand | `brands` | |
| Product | `products` | Canonical product (`CANONICAL_PRODUCT_MODEL.md`) |
| Marketplace | `marketplaces` | Amazon, Flipkart, Myntra, Nykaa |
| Listing | `listings` | Marketplace-specific offer for a product |
| Deal | `deals` | |
| PriceHistory | `price_history` | Immutable snapshots (`PRICE_HISTORY_DESIGN.md`) |
| TelegramUser | `telegram_users` | UUID, Telegram Chat ID, Username, Display Name, Timezone, Status |
| UserInterest | `user_interests` | One row per Interested action; references `telegram_user_id` |
| Account | `accounts` | Owned by the Account Service |
| Order | `orders` | |
| OrderItem | `order_items` | |
| PurchaseTask | *table name unassigned* | One per account per order (`ZIP_07/PURCHASE_QUEUE.md`) |
| Event | `events` | Written only by the Event Store Consumer |

`PurchaseTask` is new to this diagram. It is required because purchase tasks
carry immutable UUIDs (section 3) and because `ORDER_PLANNED` fans out into
one `PURCHASE_TASK_CREATED` per allocated account.

> `TABLES.md` does not yet list `user_interests` or a purchase task table.
> That file needs updating to match this diagram.

---

## 2. Relationships

```
Brand
  |  1:N
  v
Product ------------------ 1:N ------> PriceHistory
  |  1:N                                   (see Q26)
  v
Listing <---- N:1 ---- Marketplace
  |  1:N
  v
Deal
  |  1:N                 1:N
  +---------> Order      +--------> UserInterest
                |  1:N
                v
             OrderItem

Order
  |  1:N
  v
PurchaseTask ----- N:1 ----> Account ----- N:1 ----> Marketplace
                                              (see Q27)
```

### Confirmed cardinality

| Relationship | Cardinality | Source |
|---|---|---|
| Brand -> Product | 1:N | `RELATIONSHIPS.md` |
| Product -> Listing | 1:N | `RELATIONSHIPS.md`; a product may have a listing on each of Amazon, Flipkart, Nykaa and Myntra |
| Marketplace -> Listing | 1:N | `RELATIONSHIPS.md` |
| Listing -> Deal | 1:N | `RELATIONSHIPS.md` |
| Deal -> Order | 1:N | `RELATIONSHIPS.md` |
| Order -> OrderItem | 1:N | `TABLES.md` |
| Deal -> UserInterest | 1:N | Every Interested action is recorded, whether or not a purchase follows |
| Order -> PurchaseTask | 1:N | `ZIP_07/OPTIMIZATION.md` allocates one order across multiple accounts |
| PurchaseTask -> Account | N:1 | `ZIP_07/ACCOUNT_ALLOCATION.md` |

### The Product/Listing split

A single canonical Product may carry several Listings, one per marketplace.
This is what makes cross-marketplace price comparison possible while keeping
marketplace identity immutable through the deal and order lifecycle
(ADR-005, `ZIP_02/ARCHITECTURE_DECISIONS.md`).

---

## 3. Identifiers

The following entities use **immutable UUID primary keys**:

- Product
- Listing
- Deal
- Order
- PurchaseTask
- UserInterest

This is consistent with `POSTGRESQL_SCHEMA.md` (UUID primary keys) and
`CONSTRAINTS.md` (immutable deal IDs).

- TelegramUser

**Official rule (ADR-011):**

1. Every internal entity uses an immutable UUID as its primary key.
2. Marketplace-specific identifiers are stored as unique **external
   reference columns**.
3. Marketplace identifiers are **never** used as primary keys.

Raw Telegram chat IDs follow the same rule: `telegram_users` carries the chat
ID as a unique external reference, and `user_interests` references
`telegram_user_id`, never the chat ID.

This reconciles `CONSTRAINTS.md` (unique marketplace listing IDs) with
`POSTGRESQL_SCHEMA.md` (UUID primary keys) — both hold, at different columns.

> Brand, Marketplace, OrderItem, PriceHistory, Account and Event are not in
> the UUID list. Whether that is deliberate is unstated. See open question
> Q29.

---

## 4. Unresolved

1. **PriceHistory attachment (Q26).** `PRICE_HISTORY_DESIGN.md` tracks
   `first_seen`, `last_seen` and `lowest_price` but does not say whether a
   snapshot belongs to a Listing or to a Product. Prices are
   marketplace-specific, which argues for Listing, but the document does not
   state it. The diagram above shows Product pending confirmation.
2. **Account to Marketplace (Q27).** An account belongs to a marketplace —
   this is implied by `ZIP_07/MARKETPLACE_ROUTING.md` and
   `ZIP_08/SESSION_PERSISTENCE.md`, which forbids sharing sessions across
   marketplaces — but no document declares the relationship.
3. ~~No User entity.~~ **Resolved:** `TelegramUser` added, with
   `user_interests` referencing `telegram_user_id`.
4. **No Inventory entity (Q31).** The Inventory Service owns purchase
   tracking in the MVP (ADR-012) but has no entity or table. Stock, resale
   and profit are Phase 2 and likewise have none.
5. **Conversation state has no entity (Q55).** `ZIP_06/BOT_DATABASE.md`
   requires conversation state, message mapping, pending actions and an audit
   log.
5. **Column definitions.** This diagram fixes entities and relationships
   only. No entity has a defined column list, type set, or nullability. That
   remains the largest single gap in ZIP_03.
