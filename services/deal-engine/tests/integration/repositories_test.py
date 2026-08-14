"""Deal Engine repositories against a real Postgres — Sprint 3 Task 3.1.

These are integration tests and not unit tests on purpose: every claim being
made here is a claim about Postgres. `ON CONFLICT DO NOTHING ... RETURNING`
returning no row, `lower(name) = lower(%s)` matching case-insensitively,
`status <> ALL(%s)` against an enum column, `NUMERIC(5,2)` coming back as a
`Decimal` — a stubbed cursor would agree with whatever the code assumed.

Runs against the compose Postgres with `alembic upgrade head` applied; skipped,
not failed, when either is missing. Every test rolls its transaction back, so
the developer's database is left exactly as it was found.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from uuid import UUID, uuid4

import psycopg
import pytest
from src.repositories.brand_repo import BrandRepository
from src.repositories.deal_repo import OPEN_DEAL_STATUSES, DealRepository
from src.repositories.listing_repo import ListingRepository
from src.repositories.marketplace_repo import MarketplaceRepository
from src.repositories.price_history_repo import PriceHistoryRepository
from src.repositories.product_repo import ProductRepository

from libs.canonical_models.scored_deal import ScoreBreakdown
from libs.enums import BrandTier, CurrencyCode, DealStatus, MarketplaceCode

POSTGRES_TEST_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://businessscrapper:businessscrapper@127.0.0.1:5432/businessscrapper",
)

BREAKDOWN = ScoreBreakdown(
    discount_score=40.0,
    brand_score=20.0,
    rating_score=15.0,
    velocity_score=5.0,
    weights_version="v1",
)


@pytest.fixture
def conn() -> Iterator[psycopg.Connection]:
    try:
        connection = psycopg.connect(POSTGRES_TEST_URL, connect_timeout=3)
    except psycopg.Error as exc:
        pytest.skip(f"Postgres unavailable at {POSTGRES_TEST_URL}: {exc}")
    with connection:
        with connection.cursor() as cur:
            cur.execute("SELECT to_regclass('public.deals')")
            if cur.fetchone()[0] is None:  # type: ignore[index]
                pytest.skip("run `alembic upgrade head` in infra/postgres first")
        try:
            yield connection
        finally:
            # Never commit: the test database is the developer's, not the suite's.
            connection.rollback()


def unique_name(prefix: str) -> str:
    """Names must be unique — `brands.name` is UNIQUE and rollback is not isolation."""
    return f"{prefix}-{uuid4().hex[:12]}"


@pytest.fixture
def marketplace_id(conn: psycopg.Connection) -> UUID:
    """A seeded `marketplaces` row.

    Written with raw SQL rather than through the repository because the
    repository deliberately has no insert (`DATABASE_SCHEMA.md` §2: seeded, not
    created at runtime). The row is rolled back with the rest of the test.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO marketplaces (code, display_name, base_url)
            VALUES (%s, %s, %s)
            ON CONFLICT (code) DO UPDATE SET display_name = EXCLUDED.display_name
            RETURNING id
            """,
            (str(MarketplaceCode.AMAZON), "Amazon India", "https://www.amazon.in"),
        )
        row = cur.fetchone()
    assert row is not None
    return UUID(str(row[0]))


@pytest.fixture
def product_id(conn: psycopg.Connection) -> UUID:
    return ProductRepository(conn).insert(brand_id=None, canonical_title="Test Product").id


@pytest.fixture
def listing_id(conn: psycopg.Connection, marketplace_id: UUID, product_id: UUID) -> UUID:
    listing = ListingRepository(conn).insert(
        product_id=product_id,
        marketplace_id=marketplace_id,
        external_listing_id=unique_name("ASIN"),
        url="https://www.amazon.in/dp/B0TEST0001",
        current_price=104950,
    )
    assert listing is not None
    return listing.id


# --- brands -----------------------------------------------------------------


def test_brand_lookup_is_case_insensitive(conn: psycopg.Connection) -> None:
    name = unique_name("Sennheiser")
    inserted = BrandRepository(conn).insert(name)
    assert inserted is not None

    found = BrandRepository(conn).find_by_name(name.upper())

    assert found is not None
    assert found.id == inserted.id


def test_brand_lookup_does_not_treat_the_argument_as_a_pattern(conn: psycopg.Connection) -> None:
    """`%` in a marketplace-supplied brand name is a character, not a wildcard."""
    repo = BrandRepository(conn)
    repo.insert(unique_name("Bose"))

    assert repo.find_by_name("%") is None


def test_brand_defaults_to_standard_tier(conn: psycopg.Connection) -> None:
    brand = BrandRepository(conn).insert(unique_name("Unknown"))

    assert brand is not None
    assert brand.tier is BrandTier.STANDARD


def test_reinserting_a_brand_name_returns_none(conn: psycopg.Connection) -> None:
    """The concurrent-insert path: `DO NOTHING` yields no row, caller re-reads."""
    repo = BrandRepository(conn)
    name = unique_name("Sony")
    assert repo.insert(name) is not None

    assert repo.insert(name) is None
    assert repo.find_by_name(name) is not None


# --- marketplaces -----------------------------------------------------------


def test_marketplace_found_by_code(conn: psycopg.Connection, marketplace_id: UUID) -> None:
    found = MarketplaceRepository(conn).find_by_code(MarketplaceCode.AMAZON)

    assert found is not None
    assert found.id == marketplace_id
    assert found.code is MarketplaceCode.AMAZON


def test_unseeded_marketplace_is_none(conn: psycopg.Connection) -> None:
    with conn.cursor() as cur:
        cur.execute("DELETE FROM marketplaces WHERE code = %s", (str(MarketplaceCode.NYKAA),))

    assert MarketplaceRepository(conn).find_by_code(MarketplaceCode.NYKAA) is None


# --- products ---------------------------------------------------------------


def test_product_attributes_default_to_an_empty_map(conn: psycopg.Connection) -> None:
    product = ProductRepository(conn).insert(brand_id=None, canonical_title="Headphones")

    assert product.attributes == {}


def test_product_round_trips(conn: psycopg.Connection) -> None:
    repo = ProductRepository(conn)
    brand = BrandRepository(conn).insert(unique_name("JBL"))
    assert brand is not None

    inserted = repo.insert(
        brand_id=brand.id,
        canonical_title="JBL Tune 770NC",
        category="Electronics",
        subcategory="Headphones",
        attributes={"color": "black"},
        image_url="https://example.invalid/a.jpg",
    )
    fetched = repo.get_by_id(inserted.id)

    assert fetched == inserted
    assert fetched is not None
    assert fetched.attributes["color"] == "black"


# --- listings ---------------------------------------------------------------


def test_listing_found_by_marketplace_and_external_id(
    conn: psycopg.Connection, marketplace_id: UUID, product_id: UUID
) -> None:
    repo = ListingRepository(conn)
    external_id = unique_name("B0")

    inserted = repo.insert(
        product_id=product_id,
        marketplace_id=marketplace_id,
        external_listing_id=external_id,
        url="https://www.amazon.in/dp/B0TEST0002",
        current_price=99900,
        mrp=150000,
        rating=Decimal("4.3"),
        review_count=1204,
    )
    assert inserted is not None
    found = repo.find_by_external(marketplace_id, external_id)

    assert found == inserted
    assert found is not None
    assert found.currency is CurrencyCode.INR
    assert found.rating == Decimal("4.3")


def test_duplicate_external_listing_id_returns_none(
    conn: psycopg.Connection, marketplace_id: UUID, product_id: UUID
) -> None:
    repo = ListingRepository(conn)
    external_id = unique_name("B0")
    args = {
        "product_id": product_id,
        "marketplace_id": marketplace_id,
        "external_listing_id": external_id,
        "url": "https://www.amazon.in/dp/B0TEST0003",
        "current_price": 50000,
    }
    assert repo.insert(**args) is not None  # type: ignore[arg-type]

    assert repo.insert(**args) is None  # type: ignore[arg-type]


def test_update_observation_advances_last_scanned_at(
    conn: psycopg.Connection, listing_id: UUID
) -> None:
    repo = ListingRepository(conn)
    before = repo.get_by_id(listing_id)
    assert before is not None

    updated = repo.update_observation(listing_id, current_price=88800, in_stock=False)

    assert updated is not None
    assert updated.current_price == 88800
    assert updated.in_stock is False
    assert updated.last_scanned_at >= before.last_scanned_at


def test_update_observation_keeps_the_url_when_none_is_passed(
    conn: psycopg.Connection, listing_id: UUID
) -> None:
    repo = ListingRepository(conn)
    original = repo.get_by_id(listing_id)
    assert original is not None

    updated = repo.update_observation(listing_id, current_price=1, url=None)

    assert updated is not None
    assert updated.url == original.url


def test_update_observation_on_a_missing_listing_is_none(conn: psycopg.Connection) -> None:
    assert ListingRepository(conn).update_observation(uuid4(), current_price=1) is None


# --- price_history ----------------------------------------------------------


def test_latest_observation_is_the_most_recent(conn: psycopg.Connection, listing_id: UUID) -> None:
    repo = PriceHistoryRepository(conn)
    repo.insert(listing_id, 120000, True)
    newest = repo.insert(listing_id, 99900, True)

    assert repo.latest(listing_id) == newest


def test_stats_over_the_window(conn: psycopg.Connection, listing_id: UUID) -> None:
    repo = PriceHistoryRepository(conn)
    for price in (120000, 99900, 110000):
        repo.insert(listing_id, price, True)

    stats = repo.stats(listing_id, window_days=30)

    assert stats is not None
    assert stats.observation_count == 3
    assert stats.lowest_price == 99900
    assert stats.highest_price == 120000
    assert stats.first_seen <= stats.last_seen


def test_stats_excludes_observations_outside_the_window(
    conn: psycopg.Connection, listing_id: UUID
) -> None:
    repo = PriceHistoryRepository(conn)
    repo.insert(listing_id, 50000, True)
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE price_history SET observed_at = now() - INTERVAL '10 days' WHERE listing_id = %s",
            (listing_id,),
        )
    repo.insert(listing_id, 99900, True)

    stats = repo.stats(listing_id, window_days=3)

    assert stats is not None
    assert stats.observation_count == 1
    assert stats.lowest_price == 99900


def test_stats_with_no_history_is_none(conn: psycopg.Connection, listing_id: UUID) -> None:
    """Not a zero-filled row: a new listing has no lowest price, and 0 would read
    as the deepest discount in the system."""
    assert PriceHistoryRepository(conn).stats(listing_id, window_days=30) is None


# --- deals ------------------------------------------------------------------


def insert_deal(conn: psycopg.Connection, listing_id: UUID, status: DealStatus) -> UUID:
    return (
        DealRepository(conn)
        .insert(
            listing_id=listing_id,
            score=Decimal("80.00"),
            score_breakdown=BREAKDOWN,
            detected_price=99900,
            reference_price=150000,
            discount_pct=Decimal("33.40"),
            expires_at=datetime.now(UTC) + timedelta(hours=6),
            status=status,
        )
        .id
    )


def test_terminal_and_open_statuses_partition_the_enum() -> None:
    assert OPEN_DEAL_STATUSES.isdisjoint(
        {
            DealStatus.EXPIRED,
            DealStatus.IGNORED,
            DealStatus.ORDERED,
            DealStatus.PRICE_CHANGED_REJECTED,
            DealStatus.SOLD_OUT_REJECTED,
        }
    )
    assert DealStatus.SCORED in OPEN_DEAL_STATUSES
    assert DealStatus.WATCHING in OPEN_DEAL_STATUSES


def test_deal_round_trips_with_its_breakdown(conn: psycopg.Connection, listing_id: UUID) -> None:
    repo = DealRepository(conn)
    deal_id = insert_deal(conn, listing_id, DealStatus.SCORED)

    deal = repo.get_by_id(deal_id)

    assert deal is not None
    assert deal.status is DealStatus.SCORED
    assert deal.score == Decimal("80.00")
    assert deal.score_breakdown == BREAKDOWN
    assert deal.detected_price == 99900


@pytest.mark.parametrize("status", sorted(OPEN_DEAL_STATUSES))
def test_open_statuses_are_found(
    conn: psycopg.Connection, listing_id: UUID, status: DealStatus
) -> None:
    insert_deal(conn, listing_id, status)

    found = DealRepository(conn).find_open_for_listing(listing_id)

    assert found is not None
    assert found.status is status


@pytest.mark.parametrize(
    "status",
    [
        DealStatus.EXPIRED,
        DealStatus.IGNORED,
        DealStatus.ORDERED,
        DealStatus.PRICE_CHANGED_REJECTED,
        DealStatus.SOLD_OUT_REJECTED,
    ],
)
def test_terminal_statuses_are_not_found(
    conn: psycopg.Connection, listing_id: UUID, status: DealStatus
) -> None:
    """A listing whose only deal is terminal is free to receive a new one."""
    insert_deal(conn, listing_id, status)

    assert DealRepository(conn).find_open_for_listing(listing_id) is None


def test_update_status_closes_a_deal(conn: psycopg.Connection, listing_id: UUID) -> None:
    repo = DealRepository(conn)
    deal_id = insert_deal(conn, listing_id, DealStatus.SCORED)

    updated = repo.update_status(deal_id, DealStatus.EXPIRED)

    assert updated is not None
    assert updated.status is DealStatus.EXPIRED
    assert repo.find_open_for_listing(listing_id) is None


def test_update_status_on_a_missing_deal_is_none(conn: psycopg.Connection) -> None:
    assert DealRepository(conn).update_status(uuid4(), DealStatus.EXPIRED) is None


def test_lock_listing_is_held_by_the_transaction(
    conn: psycopg.Connection, listing_id: UUID
) -> None:
    """The dedup guard's foundation: the lock exists and is transaction-scoped.

    A second connection is not opened to prove contention — that needs a
    timeout and a thread, and what matters for Task 3.1 is that the lock is
    taken on the current transaction. Task 3.4 owns the guard itself.
    """
    DealRepository(conn).lock_listing(listing_id)

    with conn.cursor() as cur:
        cur.execute(
            "SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND pid = pg_backend_pid()"
        )
        row = cur.fetchone()

    assert row is not None
    assert row[0] == 1
