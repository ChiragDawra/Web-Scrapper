"""`ConnectorInterface` — Sprint 2 Task 2.1.

Definition of Done: "Signature matches `SERVICE_INTERFACES.md` §1 exactly." That
is a claim about a signature, so most of this file inspects one rather than
calling it: `normalize`, one positional parameter named
`raw_marketplace_response`, returning `CanonicalProduct`.
"""

from __future__ import annotations

import inspect
from collections.abc import Iterable
from typing import Any, ClassVar

import pytest
from src.base.connector_interface import (
    ConnectorError,
    ConnectorInterface,
    ParseFailedError,
    RateLimitedError,
)

from libs.canonical_models import CanonicalProduct
from libs.enums import ErrorSeverity, MarketplaceCode

RAW: dict[str, Any] = {"id": "B0TEST", "title": "Test", "price": 49900}


class StubConnector(ConnectorInterface):
    """Minimal legal implementation. The Amazon one lands in Task 2.3."""

    marketplace: ClassVar[MarketplaceCode] = MarketplaceCode.AMAZON

    def fetch_raw(self) -> Iterable[dict[str, Any]]:
        return [RAW]

    def normalize(self, raw_marketplace_response: Any) -> CanonicalProduct:
        if "title" not in raw_marketplace_response:
            raise ParseFailedError("no title")
        return CanonicalProduct(
            canonical_title=raw_marketplace_response["title"],
            marketplace=self.marketplace,
            external_listing_id=raw_marketplace_response["id"],
            url=f"https://www.amazon.in/dp/{raw_marketplace_response['id']}",
            price=raw_marketplace_response["price"],
            in_stock=True,
        )


def test_normalize_signature_matches_the_contract() -> None:
    """§1: `normalize(raw_marketplace_response) -> CanonicalProduct`."""
    signature = inspect.signature(ConnectorInterface.normalize)
    parameters = list(signature.parameters)

    assert parameters == ["self", "raw_marketplace_response"]
    assert signature.return_annotation == "CanonicalProduct"


def test_normalize_and_fetch_raw_are_abstract() -> None:
    assert ConnectorInterface.__abstractmethods__ == frozenset({"fetch_raw", "normalize"})


def test_the_base_class_cannot_be_instantiated() -> None:
    with pytest.raises(TypeError):
        ConnectorInterface()  # type: ignore[abstract]


def test_a_subclass_without_a_marketplace_is_rejected() -> None:
    """A connector that cannot say which marketplace it reads produces unkeyable listings."""

    class Nameless(ConnectorInterface):
        def fetch_raw(self) -> Iterable[Any]:
            return []

        def normalize(self, raw_marketplace_response: Any) -> CanonicalProduct:
            raise NotImplementedError

    with pytest.raises(TypeError, match="marketplace"):
        Nameless()


def test_a_complete_subclass_normalizes() -> None:
    product = StubConnector().normalize(RAW)

    assert isinstance(product, CanonicalProduct)
    assert product.marketplace is MarketplaceCode.AMAZON
    assert product.external_listing_id == "B0TEST"


def test_an_unparseable_item_raises_rather_than_returning_a_partial() -> None:
    """§1: "does not emit a partial/malformed `LISTING_DISCOVERED`"."""
    with pytest.raises(ParseFailedError) as raised:
        StubConnector().normalize({"id": "B0TEST", "price": 49900})

    assert raised.value.code == "CONN_PARSE_FAILED"
    assert "no title" in str(raised.value)


def test_errors_carry_the_registry_row_not_an_ad_hoc_string() -> None:
    """Roadmap §5: error paths emit only `ERROR_CODES.md` codes with documented values."""
    assert issubclass(ParseFailedError, ConnectorError)
    assert ParseFailedError.error.severity is ErrorSeverity.ERROR
    assert ParseFailedError.error.retryable is False
    assert RateLimitedError.error.retryable is True
    assert RateLimitedError("slow down").retryable is True
