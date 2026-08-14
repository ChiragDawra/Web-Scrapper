"""Dedup guard under concurrency — Sprint 3 Task 3.4.

Definition of Done: "Two concurrent `LISTING_DISCOVERED` for the same listing
under load produce exactly one `deals` row."
`test_concurrent_writers_produce_exactly_one_deal` is that, with real threads
on real connections — the guard is a claim about lock contention, and a single
connection can never contend with itself.

Unlike the rest of this suite these tests **commit**: an advisory lock is only
observable across transactions, and an uncommitted insert is invisible to the
other connection by definition. Everything written is therefore deleted in a
fixture teardown, in FK order. Nothing outside the rows created here is
touched, and the rows are keyed by a per-test UUID.
"""

from __future__ import annotations

import os
import threading
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import psycopg
import pytest
from src.repositories.deal_repo import DealRepository
from src.repositories.listing_repo import ListingRepository
from src.repositories.marketplace_repo import MarketplaceRepository
from src.repositories.product_repo import ProductRepository
from src.services.deal_writer import write_deal

from libs.canonical_models.scored_deal import ScoreBreakdown, ScoredDeal
from libs.enums import DealStatus, MarketplaceCode

POSTGRES_TEST_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://businessscrapper:businessscrapper@127.0.0.1:5432/businessscrapper",
)

BREAKDOWN = ScoreBreakdown(
    discount_score=31.25,
    brand_score=18.75,
    rating_score=14.06,
    velocity_score=25.0,
    weights_version="builtin-v1",
)


def connect() -> psycopg.Connection:
    try:
        return psycopg.connect(POSTGRES_TEST_URL, connect_timeout=3)
    except psycopg.Error as exc:
        pytest.skip(f"Postgres unavailable at {POSTGRES_TEST_URL}: {exc}")


@pytest.fixture
def committed_listing() -> Iterator[UUID]:
    """A committed listing (plus its product and marketplace), deleted afterwards.

    Committed on purpose: the concurrent writers run on their own connections
    and cannot see an uncommitted row.
    """
    conn = connect()
    with conn:
        with conn.cursor() as cur:
            cur.execute("SELECT to_regclass('public.deals')")
            if cur.fetchone()[0] is None:  # type: ignore[index]
                pytest.skip("run `alembic upgrade head` in infra/postgres first")

        marketplace = MarketplaceRepository(conn).find_by_code(MarketplaceCode.AMAZON)
        if marketplace is None:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO marketplaces (code, display_name, base_url)
                    VALUES (%s, %s, %s) RETURNING id
                    """,
                    (str(MarketplaceCode.AMAZON), "Amazon India", "https://www.amazon.in"),
                )
                row = cur.fetchone()
            assert row is not None
            marketplace_id = UUID(str(row[0]))
        else:
            marketplace_id = marketplace.id

        product = ProductRepository(conn).insert(
            brand_id=None, canonical_title=f"Concurrency Fixture {uuid4().hex[:8]}"
        )
        listing = ListingRepository(conn).insert(
            product_id=product.id,
            marketplace_id=marketplace_id,
            external_listing_id=f"CONC-{uuid4().hex[:12]}",
            url="https://www.amazon.in/dp/B0CONC0001",
            current_price=100000,
            mrp=200000,
        )
        assert listing is not None
        conn.commit()

        try:
            yield listing.id
        finally:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM deals WHERE listing_id = %s", (listing.id,))
                cur.execute("DELETE FROM listings WHERE id = %s", (listing.id,))
                cur.execute("DELETE FROM products WHERE id = %s", (product.id,))
            conn.commit()


def scored_deal(listing_id: UUID) -> ScoredDeal:
    return ScoredDeal(
        listing_id=listing_id,
        marketplace=MarketplaceCode.AMAZON,
        score=89.06,
        score_breakdown=BREAKDOWN,
        detected_price=100000,
        reference_price=200000,
        discount_pct=50.0,
        expires_at=datetime.now(UTC) + timedelta(hours=6),
    )


def count_deals(listing_id: UUID) -> int:
    conn = connect()
    with conn, conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM deals WHERE listing_id = %s", (listing_id,))
        row = cur.fetchone()
    assert row is not None
    return int(row[0])


def test_concurrent_writers_produce_exactly_one_deal(committed_listing: UUID) -> None:
    """Both workers score the same listing at the same moment; one deal exists."""
    barrier = threading.Barrier(2)
    results: list[bool] = []
    errors: list[BaseException] = []
    lock = threading.Lock()

    def worker() -> None:
        conn = connect()
        try:
            with conn:
                # Both threads reach the guard together — without the advisory
                # lock this is the interleaving that writes two rows.
                barrier.wait(timeout=10)
                result = write_deal(DealRepository(conn), scored_deal(committed_listing))
                conn.commit()
            with lock:
                results.append(result.created)
        except BaseException as exc:
            with lock:
                errors.append(exc)
        finally:
            conn.close()

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=20)

    assert errors == []
    assert sorted(results) == [False, True], "exactly one writer should have created the deal"
    assert count_deals(committed_listing) == 1


def test_second_write_returns_the_existing_open_deal(committed_listing: UUID) -> None:
    conn = connect()
    with conn:
        repo = DealRepository(conn)
        first = write_deal(repo, scored_deal(committed_listing))
        second = write_deal(repo, scored_deal(committed_listing))
        conn.commit()

    assert first.created is True
    assert second.created is False
    assert second.deal.id == first.deal.id
    assert count_deals(committed_listing) == 1


def test_a_closed_deal_does_not_block_a_new_one(committed_listing: UUID) -> None:
    """Terminal statuses free the listing — that is what "open" means in §6."""
    conn = connect()
    with conn:
        repo = DealRepository(conn)
        first = write_deal(repo, scored_deal(committed_listing))
        repo.update_status(first.deal.id, DealStatus.EXPIRED)
        second = write_deal(repo, scored_deal(committed_listing))
        conn.commit()

    assert second.created is True
    assert second.deal.id != first.deal.id
    assert count_deals(committed_listing) == 2


def test_stored_score_is_rounded_once(committed_listing: UUID) -> None:
    """`NUMERIC(5,2)` — the float is rounded here, visibly, not by the driver."""
    conn = connect()
    with conn:
        result = write_deal(DealRepository(conn), scored_deal(committed_listing))
        conn.commit()

    assert float(result.deal.score) == pytest.approx(89.06)
    assert float(result.deal.discount_pct) == pytest.approx(50.0)
