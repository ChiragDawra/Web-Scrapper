"""`resolveBrand(brand_name) -> brand_id` — Sprint 3 Task 3.2.

`SERVICE_INTERFACES.md` §2: case-insensitive exact match against `brands`,
creating a `STANDARD`-tier row on miss (`CANONICAL_MODELS.md` "Brand
resolution"). Tier upgrades to `PREMIUM` are manual, via the Admin Dashboard —
nothing on this path ever writes a tier other than `STANDARD`.

`brand_name` is nullable on `CanonicalProduct` ("connector best-effort
extraction"), and `products.brand_id` is nullable to match, so an absent name
resolves to `None` rather than to a brand called "Unknown": one shared row
collecting every unidentified product would make brand-tier scoring meaningless
for all of them.
"""

from __future__ import annotations

import logging
from typing import Final
from uuid import UUID

from libs.enums import BrandTier
from src.repositories.brand_repo import BrandRepository

__all__ = ["resolve_brand"]

logger: Final = logging.getLogger(__name__)

# `brands.name` is VARCHAR(200) (`DATABASE_SCHEMA.md` §1). Marketplace text can
# be longer; truncating is better than a failed insert, and matching then stays
# consistent because every write goes through this same truncation.
MAX_NAME_LENGTH: Final = 200


def resolve_brand(repo: BrandRepository, brand_name: str | None) -> UUID | None:
    """Return the `brands.id` for `brand_name`, creating the row if it is new.

    `None` when the connector supplied no usable name. The caller commits: like
    the repositories, this function participates in the handler's transaction
    and never opens one of its own.
    """
    name = _normalize(brand_name)
    if name is None:
        return None

    existing = repo.find_by_name(name)
    if existing is not None:
        return existing.id

    inserted = repo.insert(name, BrandTier.STANDARD)
    if inserted is not None:
        logger.info("created brand %r at tier %s", name, BrandTier.STANDARD)
        return inserted.id

    # `insert()` returned no row, which means `ON CONFLICT DO NOTHING` fired:
    # a concurrent transaction inserted the same name between the lookup and
    # the insert. Re-read rather than raise — the desired end state (one row,
    # this name) is exactly what happened.
    reread = repo.find_by_name(name)
    if reread is None:
        # Only reachable if the row vanished between the conflict and this
        # read, which needs a manual delete mid-transaction. Loud, because
        # silently returning None would attach the product to no brand at all.
        raise RuntimeError(f"brand {name!r} conflicted on insert but is not readable")
    return reread.id


def _normalize(brand_name: str | None) -> str | None:
    """Trim, collapse internal whitespace, cap at the column width.

    `"  Sony  "` and `"Sony"` are the same brand; so are `"Sony  India"` and
    `"Sony India"`, which is what marketplace HTML produces when a line break
    lands mid-name. Case is *not* folded here — the stored name keeps the
    casing it first arrived in, and matching is case-insensitive in SQL.
    """
    if brand_name is None:
        return None
    collapsed = " ".join(brand_name.split())
    if not collapsed:
        return None
    return collapsed[:MAX_NAME_LENGTH]
