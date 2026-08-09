"""Canonical enum registry.

Implements `ZIP_13_ENGINEERING_CONTRACTS/ENUMS.md` in full — Sprint 1 Task 1.1.

Every enum here is 1:1 with that document: same members, same string values, no
extras. `ENUMS.md` states that each is simultaneously a Postgres
`CREATE TYPE ... AS ENUM` and a string literal set on the wire (event payloads,
API JSON), so these are `StrEnum` — the member *value* is the wire and database
representation, and comparing against a bare string works without a cast.

No status or type column anywhere in the system may hold free text. If a value
is missing here, the fix is to raise it as a gap against `ENUMS.md`, never to
add a member (`IMPLEMENTATION_ROADMAP.md` §5).
"""

from __future__ import annotations

from enum import StrEnum

__all__ = [
    "AccountHealthBand",
    "AccountStatus",
    "BrandTier",
    "ConversationState",
    "CurrencyCode",
    "DealStatus",
    "ErrorSeverity",
    "EventProducerService",
    "InventoryItemStatus",
    "MarketplaceCode",
    "OrderItemStatus",
    "OrderStatus",
    "PurchaseTaskStatus",
    "UserInterestAction",
]


class MarketplaceCode(StrEnum):
    """`ENUMS.md` §marketplace_code."""

    AMAZON = "AMAZON"
    FLIPKART = "FLIPKART"
    MYNTRA = "MYNTRA"
    NYKAA = "NYKAA"


class DealStatus(StrEnum):
    """`ENUMS.md` §deal_status. Edges and guards: `STATE_TRANSITIONS.md` §1.

    Transcribed from that section's "Full set" line, which is authoritative:
    the arrow diagram above it omits `PRICE_CHANGED_REJECTED` and
    `SOLD_OUT_REJECTED`, both of which the same section lists as terminal.
    """

    SCORED = "SCORED"
    NOTIFIED = "NOTIFIED"
    DEAL_SENT = "DEAL_SENT"
    INTERESTED = "INTERESTED"
    REVALIDATING = "REVALIDATING"
    CONFIRMED = "CONFIRMED"
    PRICE_CHANGED = "PRICE_CHANGED"
    SOLD_OUT = "SOLD_OUT"
    WATCHING = "WATCHING"
    ORDERED = "ORDERED"
    IGNORED = "IGNORED"
    EXPIRED = "EXPIRED"
    PRICE_CHANGED_REJECTED = "PRICE_CHANGED_REJECTED"
    SOLD_OUT_REJECTED = "SOLD_OUT_REJECTED"


class OrderStatus(StrEnum):
    """`ENUMS.md` §order_status. See `STATE_TRANSITIONS.md` §2."""

    REQUESTED = "REQUESTED"
    PLANNING_FAILED = "PLANNING_FAILED"
    PLANNED = "PLANNED"
    EXECUTING = "EXECUTING"
    PARTIAL = "PARTIAL"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class OrderItemStatus(StrEnum):
    """`ENUMS.md` §order_item_status."""

    PENDING = "PENDING"
    EXECUTING = "EXECUTING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class PurchaseTaskStatus(StrEnum):
    """`ENUMS.md` §purchase_task_status."""

    CREATED = "CREATED"
    ASSIGNED = "ASSIGNED"
    EXECUTING = "EXECUTING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    RETRYING = "RETRYING"
    DEAD_LETTERED = "DEAD_LETTERED"


class AccountStatus(StrEnum):
    """`ENUMS.md` §account_status. See `STATE_TRANSITIONS.md` §3."""

    ACTIVE = "ACTIVE"
    WARNING = "WARNING"
    COOLDOWN = "COOLDOWN"
    SUSPENDED = "SUSPENDED"
    BANNED = "BANNED"
    DISABLED_MANUAL = "DISABLED_MANUAL"


class AccountHealthBand(StrEnum):
    """`ENUMS.md` §account_health_band.

    Bands over `accounts.health_score` (0-100, `DATABASE_SCHEMA.md` §9):
    `HEALTHY` 80-100, `WARNING` 40-79, `CRITICAL` 1-39, `ZERO` 0 (forces
    `AccountStatus.BANNED`). The thresholds are documented here rather than
    implemented as a lookup — deriving a band from a score is the Account
    Service's job (Sprint 8), not this registry's.
    """

    HEALTHY = "HEALTHY"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"
    ZERO = "ZERO"


class ConversationState(StrEnum):
    """`ENUMS.md` §conversation_state. See `STATE_TRANSITIONS.md` §4."""

    IDLE = "IDLE"
    AWAITING_QUANTITY = "AWAITING_QUANTITY"
    AWAITING_CONFIRMATION = "AWAITING_CONFIRMATION"
    AWAITING_ADMIN_INPUT = "AWAITING_ADMIN_INPUT"


class UserInterestAction(StrEnum):
    """`ENUMS.md` §user_interest_action."""

    INTERESTED = "INTERESTED"
    IGNORED = "IGNORED"
    WATCH_LATER = "WATCH_LATER"


class InventoryItemStatus(StrEnum):
    """`ENUMS.md` §inventory_item_status."""

    PURCHASED = "PURCHASED"
    DELIVERED = "DELIVERED"
    RETURNED = "RETURNED"
    RESOLD = "RESOLD"  # Phase 2 only


class EventProducerService(StrEnum):
    """`ENUMS.md` §event_producer_service.

    Values are the deployable service names, lowercase and hyphenated. They are
    written to `processed_events.consumer_service` for dedup and into the
    per-consumer DLQ stream name `{event_type}.dlq.{consumer_service}`
    (`EVENT_SCHEMAS.md` §8), so the exact spelling is load-bearing.
    """

    MARKETPLACE_CONNECTOR = "marketplace-connector"
    DEAL_ENGINE = "deal-engine"
    REVALIDATION_SERVICE = "revalidation-service"
    TELEGRAM_BOT = "telegram-bot"
    ORDER_PLANNER = "order-planner"
    ACCOUNT_SERVICE = "account-service"
    INVENTORY_SERVICE = "inventory-service"
    PURCHASE_AGENT = "purchase-agent"
    EVENT_STORE_CONSUMER = "event-store-consumer"
    API_GATEWAY = "api-gateway"
    ML_SERVICE = "ml-service"


class CurrencyCode(StrEnum):
    """`ENUMS.md` §currency_code.

    `INR` is the only value supported in MVP; the field exists for forward
    compatibility. Adding a second member is an architecture change, not a
    convenience.
    """

    INR = "INR"


class ErrorSeverity(StrEnum):
    """`ENUMS.md` §error_severity. See `ERROR_CODES.md`."""

    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


class BrandTier(StrEnum):
    """`ENUMS.md` §brand_tier — scoring input (`ZIP_05/DEAL_SCORING.md`)."""

    PREMIUM = "PREMIUM"
    STANDARD = "STANDARD"
    UNBRANDED = "UNBRANDED"
