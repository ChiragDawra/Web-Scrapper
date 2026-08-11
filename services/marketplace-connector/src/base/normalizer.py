"""`VALIDATION_RULES.md` §1, enforced on every `normalize()` return — Sprint 2 Task 2.2.

§1's preamble sets where this runs: validation happens "at the boundary where
data enters the system ... never re-validated deeper in the pipeline. A service
downstream of a validated boundary trusts the shape." A connector's
`normalize()` is that boundary for ingested listings, so every connector calls
`validate()` on the product it is about to return, and no Deal Engine code ever
re-checks `price > 0`.

Two entry points, because the two callers want different things:

- `check()` is pure and returns the failures as a `{field_path: reason}` map.
  §1 keys failures by field path (`DTOS.md` §2 `ErrorResponse.details`), and a
  map is that keying. It reports *all* broken rules, not the first — a fixture
  with three problems should say three, or fixing them turns into three runs.
- `validate()` is what connectors call: it raises `ParseFailedError`
  (`CONN_PARSE_FAILED`) when `check()` is non-empty, per §1's closing line, "A
  product failing any required-field rule is dropped (`CONN_PARSE_FAILED`), not
  partially emitted."

`validate()` returns a product rather than `None` because one rule is a
normalization, not a predicate: `canonical_title` is specified "trimmed". The
trimmed title has to reach the caller somehow, and `CanonicalProduct` is frozen,
so the return value is a `replace()`d copy. Connectors must use the returned
product — `validate(p)`'s result, not `p`.

Not enforced here: `external_listing_id`'s "unique per marketplace". That is a
statement about the set of listings already persisted, not about the product in
hand, and the dedup key is enforced by the `listings` unique constraint
(`DATABASE_SCHEMA.md` §4) plus the Deal Engine's dedup guard (Sprint 3 Task
3.4). A single-product validator cannot see the other rows; pretending to check
it here would be a lie that lets a real duplicate through.
"""

from __future__ import annotations

import dataclasses
from urllib.parse import urlparse

from libs.canonical_models import CanonicalProduct
from libs.enums import MarketplaceCode
from src.base.connector_interface import ParseFailedError

__all__ = ["MARKETPLACE_DOMAINS", "check", "validate"]

TITLE_MAX_LEN = 500
RATING_MIN = 0.0
RATING_MAX = 5.0

#: Rule 6 is "host must match the marketplace's known domain(s)", and no
#: contract in `ZIP_13_ENGINEERING_CONTRACTS` says what those domains are, so
#: this map is an assumption, not a transcription. The `.in` TLDs follow from
#: `CanonicalProduct.currency` defaulting to `INR` — this is an India-market
#: build. Correct a row here and every connector's URL check follows; the value
#: is deliberately not duplicated into the per-marketplace connector packages.
MARKETPLACE_DOMAINS: dict[MarketplaceCode, frozenset[str]] = {
    MarketplaceCode.AMAZON: frozenset({"amazon.in"}),
    MarketplaceCode.FLIPKART: frozenset({"flipkart.com"}),
    MarketplaceCode.MYNTRA: frozenset({"myntra.com"}),
    MarketplaceCode.NYKAA: frozenset({"nykaa.com"}),
}


def _is_int(value: object) -> bool:
    """`bool` is a subclass of `int`, and `True` is not a price. Excluded explicitly."""
    return isinstance(value, int) and not isinstance(value, bool)


def _host_matches(host: str, domains: frozenset[str]) -> bool:
    """Exact host or any subdomain of a known domain.

    Suffix-matched on a leading dot so `notamazon.in` fails where `www.amazon.in`
    passes; a bare `endswith("amazon.in")` would accept the first.
    """
    return any(host == domain or host.endswith(f".{domain}") for domain in domains)


def _check_url(product: CanonicalProduct, failures: dict[str, str]) -> None:
    """Rule 6: required, valid URL, host must match the marketplace's known domain(s)."""
    if not isinstance(product.url, str) or not product.url.strip():
        failures["url"] = "required, must be a non-empty string"
        return

    parsed = urlparse(product.url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        failures["url"] = f"not a valid absolute http(s) URL: {product.url!r}"
        return

    # An unknown marketplace already failed rule 4; skip rather than report the
    # host as wrong, since there is no domain set to judge it against.
    domains = MARKETPLACE_DOMAINS.get(product.marketplace)
    if domains is None:
        return

    host = parsed.hostname.lower()
    if not _host_matches(host, domains):
        failures["url"] = f"host {host!r} is not a known {product.marketplace} domain"


def check(product: CanonicalProduct) -> dict[str, str]:
    """Return every `VALIDATION_RULES.md` §1 rule the product breaks, keyed by field path.

    Empty dict means valid. Pure: no raising, no mutation — `validate()` owns
    the raise so that a caller wanting to log or count failures (the Task 2.5
    skip path) does not have to catch an exception to see them.
    """
    failures: dict[str, str] = {}

    # Rule 1 — canonical_title: required, 1-500 chars, trimmed, non-empty after trim.
    if not isinstance(product.canonical_title, str):
        failures["canonical_title"] = "required, must be a string"
    else:
        trimmed = product.canonical_title.strip()
        if not trimmed:
            failures["canonical_title"] = "required, non-empty after trim"
        elif len(trimmed) > TITLE_MAX_LEN:
            failures["canonical_title"] = f"{len(trimmed)} chars, max {TITLE_MAX_LEN}"

    # Rule 2 — price: required, integer, > 0.
    if not _is_int(product.price):
        failures["price"] = "required, must be an integer"
    elif product.price <= 0:
        failures["price"] = f"must be > 0, got {product.price}"

    # Rule 3 — mrp: nullable, integer, if present must be >= price.
    if product.mrp is not None:
        if not _is_int(product.mrp):
            failures["mrp"] = "must be an integer when present"
        elif _is_int(product.price) and product.mrp < product.price:
            failures["mrp"] = f"must be >= price, got mrp={product.mrp} price={product.price}"

    # Rule 4 — marketplace: required, must be a valid marketplace_code.
    if not isinstance(product.marketplace, MarketplaceCode):
        failures["marketplace"] = f"not a valid marketplace_code: {product.marketplace!r}"

    # Rule 5 — external_listing_id: required, non-empty. (Uniqueness: see module docstring.)
    if not isinstance(product.external_listing_id, str) or not product.external_listing_id.strip():
        failures["external_listing_id"] = "required, non-empty"

    # Rule 6 — url.
    _check_url(product, failures)

    # Rule 7 — rating: nullable, if present 0.0-5.0.
    if product.rating is not None:
        if isinstance(product.rating, bool) or not isinstance(product.rating, (int, float)):
            failures["rating"] = "must be a number when present"
        elif not RATING_MIN <= product.rating <= RATING_MAX:
            failures["rating"] = f"must be {RATING_MIN}-{RATING_MAX}, got {product.rating}"

    # Rule 8 — review_count: nullable, if present >= 0.
    if product.review_count is not None:
        if not _is_int(product.review_count):
            failures["review_count"] = "must be an integer when present"
        elif product.review_count < 0:
            failures["review_count"] = f"must be >= 0, got {product.review_count}"

    # Rule 9 — in_stock: required boolean; connectors must not omit, and must
    # infer `false` rather than leave null when there is no positive stock signal.
    if not isinstance(product.in_stock, bool):
        failures["in_stock"] = (
            "required boolean — infer False when the response gives no positive "
            f"stock signal, never null; got {product.in_stock!r}"
        )

    return failures


def validate(product: CanonicalProduct) -> CanonicalProduct:
    """Enforce §1 and return the normalized product. Connectors must use the return value.

    Raises `ParseFailedError` (`CONN_PARSE_FAILED`) listing every field path that
    failed. The only normalization applied is rule 1's trim.
    """
    failures = check(product)
    if failures:
        detail = "; ".join(f"{field}: {reason}" for field, reason in failures.items())
        raise ParseFailedError(detail)

    return dataclasses.replace(product, canonical_title=product.canonical_title.strip())
