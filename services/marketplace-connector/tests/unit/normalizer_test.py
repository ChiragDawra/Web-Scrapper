"""Shared `normalize()` validator — Sprint 2 Task 2.2.

Definition of Done: "Each of the 9 rules has one pass + one fail unit test."
`RULE_CASES` is that table, one entry per numbered row of `VALIDATION_RULES.md`
§1, and the pass/fail pair is generated from it — so a tenth rule added to the
validator without a row here shows up as a missing test, not as silence.

Cases mutate one field of `VALID` at a time. Anything asserted about a fail case
is therefore attributable to that field, and a pass case proves the rule accepts
the legal value rather than that the whole product happens to be fine.
"""

from __future__ import annotations

from typing import Any, NamedTuple

import pytest
from src.base.connector_interface import ParseFailedError
from src.base.normalizer import MARKETPLACE_DOMAINS, check, validate

from libs.canonical_models import CanonicalProduct
from libs.enums import MarketplaceCode

VALID = CanonicalProduct(
    canonical_title="Noise ColorFit Pro 5 Smartwatch",
    marketplace=MarketplaceCode.AMAZON,
    external_listing_id="B0CTEST123",
    url="https://www.amazon.in/dp/B0CTEST123",
    price=249900,
    in_stock=True,
    mrp=499900,
    rating=4.3,
    review_count=1820,
)


class RuleCase(NamedTuple):
    """One row of `VALIDATION_RULES.md` §1: a field, a legal value, an illegal one."""

    field: str
    passing: Any
    failing: Any


RULE_CASES = [
    # 1 — required, 1-500 chars, trimmed, non-empty after trim.
    RuleCase("canonical_title", "  Trimmed Title  ", "   "),
    # 2 — required, integer, > 0.
    RuleCase("price", 1, 0),
    # 3 — nullable, integer, if present must be >= price.
    RuleCase("mrp", VALID.price, VALID.price - 1),
    # 4 — required, must be a valid marketplace_code.
    RuleCase("marketplace", MarketplaceCode.AMAZON, "AMAZONN"),
    # 5 — required, non-empty.
    RuleCase("external_listing_id", "B0OTHER456", ""),
    # 6 — required, valid URL, host must match the marketplace's known domain(s).
    RuleCase("url", "https://amazon.in/dp/B0CTEST123", "https://www.flipkart.com/p/B0CTEST123"),
    # 7 — nullable, if present 0.0-5.0.
    RuleCase("rating", 5.0, 5.1),
    # 8 — nullable, if present >= 0.
    RuleCase("review_count", 0, -1),
    # 9 — required boolean; never null.
    RuleCase("in_stock", False, None),
]

RULE_IDS = [case.field for case in RULE_CASES]


def _with(field: str, value: Any) -> CanonicalProduct:
    """`dataclasses.replace` equivalent that also accepts values the type rejects.

    Several fail cases are deliberately wrongly-typed (`marketplace="AMAZONN"`,
    `in_stock=None`) because the validator's job is to catch a connector that
    returns them. `CanonicalProduct` is frozen *and* slotted, so this rebuilds
    through `from_dict`-shaped kwargs rather than assigning.
    """
    kwargs: dict[str, Any] = {
        "canonical_title": VALID.canonical_title,
        "marketplace": VALID.marketplace,
        "external_listing_id": VALID.external_listing_id,
        "url": VALID.url,
        "price": VALID.price,
        "in_stock": VALID.in_stock,
        "mrp": VALID.mrp,
        "rating": VALID.rating,
        "review_count": VALID.review_count,
    }
    kwargs[field] = value
    return CanonicalProduct(**kwargs)


def test_valid_product_passes() -> None:
    assert check(VALID) == {}


@pytest.mark.parametrize("case", RULE_CASES, ids=RULE_IDS)
def test_rule_accepts_legal_value(case: RuleCase) -> None:
    assert check(_with(case.field, case.passing)) == {}


@pytest.mark.parametrize("case", RULE_CASES, ids=RULE_IDS)
def test_rule_rejects_illegal_value(case: RuleCase) -> None:
    failures = check(_with(case.field, case.failing))
    assert case.field in failures, f"rule for {case.field} did not fire: {failures}"


def test_all_nine_rules_are_covered() -> None:
    """§1 has nine rows; a tenth rule without a case here is a coverage hole."""
    assert len(RULE_CASES) == 9
    assert len(set(RULE_IDS)) == 9


def test_nullable_fields_may_be_absent() -> None:
    """Rules 3, 7 and 8 are nullable — `None` is legal, and must not be reported."""
    product = CanonicalProduct(
        canonical_title=VALID.canonical_title,
        marketplace=VALID.marketplace,
        external_listing_id=VALID.external_listing_id,
        url=VALID.url,
        price=VALID.price,
        in_stock=False,
    )
    assert product.mrp is None
    assert check(product) == {}


def test_check_reports_every_broken_rule_at_once() -> None:
    """A three-problem fixture reports three field paths, not the first one."""
    product = _with("price", 0)
    product = CanonicalProduct(
        canonical_title="",
        marketplace=product.marketplace,
        external_listing_id=product.external_listing_id,
        url=product.url,
        price=0,
        in_stock=True,
        rating=9.9,
    )
    assert set(check(product)) == {"canonical_title", "price", "rating"}


def test_validate_returns_trimmed_title() -> None:
    """Rule 1 says "trimmed", so the trim has to reach the caller via the return value."""
    result = validate(_with("canonical_title", "  Padded Title  "))
    assert result.canonical_title == "Padded Title"


def test_validate_leaves_a_clean_product_otherwise_unchanged() -> None:
    assert validate(VALID) == VALID


def test_validate_raises_parse_failed_with_field_paths() -> None:
    with pytest.raises(ParseFailedError) as exc_info:
        validate(_with("price", -1))

    error = exc_info.value
    assert error.code == "CONN_PARSE_FAILED"
    assert "price" in str(error)


@pytest.mark.parametrize(
    "url",
    [
        "https://amazon.in/dp/X",
        "https://www.amazon.in/dp/X",
        "https://smile.amazon.in/dp/X",
        "http://amazon.in/dp/X",
    ],
)
def test_url_accepts_known_host_and_subdomains(url: str) -> None:
    assert check(_with("url", url)) == {}


@pytest.mark.parametrize(
    "url",
    [
        "https://notamazon.in/dp/X",  # suffix match without the dot boundary
        "https://amazon.in.evil.com/dp/X",  # known domain as a subdomain of another
        "https://www.amazon.com/dp/X",  # right brand, wrong market
        "/dp/X",  # relative, no host
        "notaurl",
        "",
    ],
)
def test_url_rejects_foreign_or_malformed_hosts(url: str) -> None:
    assert "url" in check(_with("url", url))


def test_every_marketplace_has_known_domains() -> None:
    """Rule 6 is unenforceable for a marketplace with no domain set."""
    assert set(MARKETPLACE_DOMAINS) == set(MarketplaceCode)
    assert all(domains for domains in MARKETPLACE_DOMAINS.values())


@pytest.mark.parametrize("marketplace", list(MarketplaceCode))
def test_url_is_checked_against_the_products_own_marketplace(
    marketplace: MarketplaceCode,
) -> None:
    domain = next(iter(MARKETPLACE_DOMAINS[marketplace]))
    product = CanonicalProduct(
        canonical_title=VALID.canonical_title,
        marketplace=marketplace,
        external_listing_id=VALID.external_listing_id,
        url=f"https://www.{domain}/p/item",
        price=VALID.price,
        in_stock=True,
    )
    assert check(product) == {}


def test_booleans_are_not_accepted_as_numbers() -> None:
    """`bool` subclasses `int`, so `True` would otherwise pass as a price of 1."""
    assert "price" in check(_with("price", True))
    assert "review_count" in check(_with("review_count", True))


def test_title_at_the_length_boundary() -> None:
    assert check(_with("canonical_title", "x" * 500)) == {}
    assert "canonical_title" in check(_with("canonical_title", "x" * 501))


def test_title_length_is_measured_after_trimming() -> None:
    """500 characters plus surrounding whitespace is a legal 500-char title."""
    assert check(_with("canonical_title", f"  {'x' * 500}  ")) == {}
