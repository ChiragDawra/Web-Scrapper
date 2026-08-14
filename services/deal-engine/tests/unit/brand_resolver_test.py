"""`resolve_brand()` without a database — Sprint 3 Task 3.2.

The DoD claims ("same casing resolves identically", "exactly one row on repeat
calls") are claims about Postgres and are tested in
`tests/integration/brand_resolver_test.py`. What is here is the part a database
cannot easily be made to show: name normalization, and the concurrent-insert
branch, which needs `insert()` to return `None` at a moment a single-threaded
integration test never reaches.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import cast
from uuid import UUID, uuid4

import pytest
from src.repositories.brand_repo import Brand, BrandRepository
from src.services.brand_resolver import MAX_NAME_LENGTH, resolve_brand

from libs.enums import BrandTier


class FakeBrandRepository:
    """In-memory stand-in with the same case-insensitive semantics as the SQL."""

    def __init__(self, *, conflict_on_insert: bool = False, loser_sees_row: bool = False) -> None:
        self.rows: dict[str, Brand] = {}
        self.insert_calls: list[str] = []
        self._conflict_on_insert = conflict_on_insert
        self._loser_sees_row = loser_sees_row

    def find_by_name(self, name: str) -> Brand | None:
        return self.rows.get(name.lower())

    def insert(self, name: str, tier: BrandTier = BrandTier.STANDARD) -> Brand | None:
        self.insert_calls.append(name)
        if self._conflict_on_insert or name.lower() in self.rows:
            if self._loser_sees_row:
                # The winning transaction's row, now visible to the re-read.
                self.seed(name, tier)
            return None
        brand = Brand(id=uuid4(), name=name, tier=tier, created_at=datetime.now(UTC))
        self.rows[name.lower()] = brand
        return brand

    def seed(self, name: str, tier: BrandTier = BrandTier.STANDARD) -> Brand:
        brand = Brand(id=uuid4(), name=name, tier=tier, created_at=datetime.now(UTC))
        self.rows[name.lower()] = brand
        return brand

    def as_repo(self) -> BrandRepository:
        return cast(BrandRepository, self)


@pytest.mark.parametrize("brand_name", [None, "", "   ", "\n\t"])
def test_missing_brand_name_resolves_to_none(brand_name: str | None) -> None:
    """`products.brand_id` is nullable; an unnamed product gets no brand row."""
    repo = FakeBrandRepository()

    assert resolve_brand(repo.as_repo(), brand_name) is None
    assert repo.insert_calls == []


def test_existing_brand_is_not_reinserted() -> None:
    repo = FakeBrandRepository()
    seeded = repo.seed("Sony")

    assert resolve_brand(repo.as_repo(), "SONY") == seeded.id
    assert repo.insert_calls == []


def test_new_brand_is_created_at_standard_tier() -> None:
    repo = FakeBrandRepository()

    brand_id = resolve_brand(repo.as_repo(), "Boat")

    assert isinstance(brand_id, UUID)
    assert repo.rows["boat"].tier is BrandTier.STANDARD


def test_whitespace_is_trimmed_and_collapsed() -> None:
    """A line break mid-name in marketplace HTML is not a different brand."""
    repo = FakeBrandRepository()

    first = resolve_brand(repo.as_repo(), "  Sony   India  ")
    second = resolve_brand(repo.as_repo(), "Sony India")

    assert first == second
    assert repo.insert_calls == ["Sony India"]


def test_stored_name_keeps_its_original_casing() -> None:
    repo = FakeBrandRepository()

    resolve_brand(repo.as_repo(), "boAt")

    assert repo.rows["boat"].name == "boAt"


def test_name_is_capped_at_the_column_width() -> None:
    repo = FakeBrandRepository()

    resolve_brand(repo.as_repo(), "x" * (MAX_NAME_LENGTH + 50))

    assert repo.insert_calls == ["x" * MAX_NAME_LENGTH]


def test_concurrent_insert_is_resolved_by_rereading() -> None:
    """`insert()` returning `None` means another transaction won; re-read, do not fail."""
    repo = FakeBrandRepository(conflict_on_insert=True, loser_sees_row=True)

    brand_id = resolve_brand(repo.as_repo(), "JBL")

    assert brand_id == repo.rows["jbl"].id
    assert repo.insert_calls == ["JBL"]


def test_a_conflict_with_no_readable_row_raises() -> None:
    """Silently returning `None` would attach the product to no brand at all."""
    repo = FakeBrandRepository(conflict_on_insert=True)

    with pytest.raises(RuntimeError, match="conflicted on insert"):
        resolve_brand(repo.as_repo(), "Ghost")
