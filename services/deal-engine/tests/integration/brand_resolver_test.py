"""`resolve_brand()` against a real Postgres — Sprint 3 Task 3.2.

Definition of Done, verbatim: "Same name in different casing resolves
identically; unknown brand creates exactly one row on repeat calls."
`test_same_name_in_different_casing_resolves_identically` and
`test_repeat_calls_create_exactly_one_row` are those two, in order.

Skipped, not failed, when Postgres or the migration is missing. Every test
rolls its transaction back.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from uuid import uuid4

import psycopg
import pytest
from src.repositories.brand_repo import BrandRepository
from src.services.brand_resolver import resolve_brand

from libs.enums import BrandTier

POSTGRES_TEST_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://businessscrapper:businessscrapper@127.0.0.1:5432/businessscrapper",
)


@pytest.fixture
def conn() -> Iterator[psycopg.Connection]:
    try:
        connection = psycopg.connect(POSTGRES_TEST_URL, connect_timeout=3)
    except psycopg.Error as exc:
        pytest.skip(f"Postgres unavailable at {POSTGRES_TEST_URL}: {exc}")
    with connection:
        with connection.cursor() as cur:
            cur.execute("SELECT to_regclass('public.brands')")
            if cur.fetchone()[0] is None:  # type: ignore[index]
                pytest.skip("run `alembic upgrade head` in infra/postgres first")
        try:
            yield connection
        finally:
            connection.rollback()


@pytest.fixture
def repo(conn: psycopg.Connection) -> BrandRepository:
    return BrandRepository(conn)


def unique_name(prefix: str) -> str:
    return f"{prefix}-{uuid4().hex[:12]}"


def count_named(conn: psycopg.Connection, name: str) -> int:
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM brands WHERE lower(name) = lower(%s)", (name,))
        row = cur.fetchone()
    assert row is not None
    return int(row[0])


def test_same_name_in_different_casing_resolves_identically(
    conn: psycopg.Connection, repo: BrandRepository
) -> None:
    name = unique_name("Sennheiser")

    first = resolve_brand(repo, name.lower())
    second = resolve_brand(repo, name.upper())
    third = resolve_brand(repo, name.title())

    assert first is not None
    assert first == second == third
    assert count_named(conn, name) == 1


def test_repeat_calls_create_exactly_one_row(
    conn: psycopg.Connection, repo: BrandRepository
) -> None:
    name = unique_name("Anker")

    ids = {resolve_brand(repo, name) for _ in range(5)}

    assert len(ids) == 1
    assert count_named(conn, name) == 1


def test_created_row_is_standard_tier(conn: psycopg.Connection, repo: BrandRepository) -> None:
    """Tier upgrades are manual, via the Admin Dashboard (`CANONICAL_MODELS.md`)."""
    name = unique_name("Zebronics")

    resolve_brand(repo, name)

    brand = repo.find_by_name(name)
    assert brand is not None
    assert brand.tier is BrandTier.STANDARD


def test_a_premium_brand_is_matched_not_downgraded(
    conn: psycopg.Connection, repo: BrandRepository
) -> None:
    """Resolution must never write a tier — a manual PREMIUM survives a resolve."""
    name = unique_name("Apple")
    seeded = repo.insert(name, BrandTier.PREMIUM)
    assert seeded is not None

    resolved = resolve_brand(repo, name.upper())

    assert resolved == seeded.id
    found = repo.find_by_name(name)
    assert found is not None
    assert found.tier is BrandTier.PREMIUM


def test_whitespace_variants_share_one_row(conn: psycopg.Connection, repo: BrandRepository) -> None:
    name = unique_name("Sony India")

    first = resolve_brand(repo, f"  {name}  ")
    second = resolve_brand(repo, name.replace(" ", "\n  "))

    assert first == second
    assert count_named(conn, name) == 1


def test_absent_brand_name_creates_nothing(conn: psycopg.Connection, repo: BrandRepository) -> None:
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM brands")
        before_row = cur.fetchone()
    assert before_row is not None

    assert resolve_brand(repo, None) is None

    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM brands")
        after_row = cur.fetchone()
    assert after_row is not None
    assert after_row[0] == before_row[0]
