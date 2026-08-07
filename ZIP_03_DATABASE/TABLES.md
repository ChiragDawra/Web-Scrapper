# Tables

Canonical table list. Entities and relationships are in `ER_DIAGRAM.md`.

All internal entities use immutable UUID primary keys. Marketplace-specific
identifiers are stored as unique external reference columns and are **never**
primary keys (ADR-011).

---

## Table List

| Table | Entity | Owning service |
|---|---|---|
| `brands` | Brand | Deal Engine |
| `marketplaces` | Marketplace | Deal Engine |
| `products` | Product (canonical) | Deal Engine |
| `listings` | Listing | Deal Engine |
| `deals` | Deal | Deal Engine |
| `price_history` | PriceHistory | Deal Engine |
| `telegram_users` | TelegramUser | Telegram Bot |
| `user_interests` | UserInterest | Telegram Bot |
| `accounts` | Account | Account Service |
| `orders` | Order | Order Planner |
| `order_items` | OrderItem | Order Planner |
| `purchase_tasks` | PurchaseTask | Order Planner |
| `events` | Event | Event Store Consumer |

### Added since the previous revision

- `telegram_users` — the User entity did not previously exist.
- `user_interests` — required by `ER_DIAGRAM.md`; every Interested action is
  recorded whether or not a purchase follows.
- `purchase_tasks` — one row per allocated account per order; purchase tasks
  carry immutable UUIDs (ADR-011).

> **Table ownership.** The "owning service" column follows from
> `ZIP_02/SERVICE_CONTRACTS.md`: no service reads another service's database.
> Ownership is assigned here to match the service boundaries in
> `ZIP_02/SERVICE_RESPONSIBILITIES.md`. No document previously stated which
> service owns which table, so this mapping needs confirmation (Q53).

---

## telegram_users

The only table with a defined column set so far.

| Column | Notes |
|---|---|
| UUID | Primary key, immutable |
| Telegram Chat ID | Unique external reference. Never used as a key |
| Username | |
| Display Name | |
| Timezone | |
| Status | |

Raw Telegram chat IDs must never be used as keys anywhere in the schema.
`user_interests` references `telegram_user_id`, not the chat ID.

> **Incomplete.** Types, nullability, and the value set for `Status` are
> undefined (Q54).

---

## Missing Tables

The Inventory Service is in scope and owns purchase tracking (ADR-012), but
no inventory table exists in this list. Stock, resale and profit tracking are
Phase 2 and likewise have no tables (Q31).

---

## Open Points

1. **No column definitions for twelve of thirteen tables (Q18a).** Only
   `telegram_users` has a field list. Every other table has a name and
   nothing else — no columns, types, nullability, defaults or foreign key
   declarations. This is the single largest gap remaining in ZIP_03 and it
   blocks `MIGRATIONS.md`, `INDEXES.md` and `CONSTRAINTS.md` from being
   actionable.
2. **Inventory tables missing (Q31).**
3. **Table ownership unconfirmed (Q53).**
4. **`price_history` attachment (Q26).** Whether a snapshot belongs to a
   listing or to a product is still unstated. Prices are marketplace-specific,
   which argues for `listing_id`, but no document says so.
5. **UUID coverage (Q29).** ADR-011 names Product, Listing, Deal, Order,
   PurchaseTask, UserInterest and TelegramUser. Whether Brand, Marketplace,
   OrderItem, PriceHistory, Account and Event also take UUID primary keys is
   unstated.
6. **Bot conversation state has no table (Q55).** `ZIP_06/BOT_DATABASE.md`
   requires conversation state, message mapping, pending actions and an audit
   log. None of these appear above.
