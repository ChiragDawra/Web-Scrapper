"""The reference-price projection — Sprint 5 Task 5.1.

Why this exists at all is argued in `deal_reference.py`: the tolerance needs
`detected_price`, the request does not carry it, and `deals` belongs to another
service. What is tested here is that the projection never *invents* one — a miss
returns `None` so the handler can refuse, rather than defaulting to something
plausible.
"""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from src.services.deal_reference import DealReferenceStore

from libs.enums import MarketplaceCode
from libs.event_bus.envelope import EventSchemaInvalidError


def scored(deal_id: str, listing_id: str, *, price: int = 100_000) -> dict[str, Any]:
    """A `DEAL_SCORED` payload, trimmed to the keys this projection reads."""
    return {
        "deal_id": deal_id,
        "listing_id": listing_id,
        "marketplace": "AMAZON",
        "detected_price": price,
    }


def test_a_recorded_deal_is_retrievable() -> None:
    deal_id, listing_id = uuid4(), uuid4()
    store = DealReferenceStore()

    store.record(scored(str(deal_id), str(listing_id), price=799_900))
    reference = store.get(deal_id)

    assert reference is not None
    assert reference.listing_id == listing_id
    assert reference.marketplace is MarketplaceCode.AMAZON
    assert reference.detected_price == 799_900


def test_an_unseen_deal_returns_none_rather_than_a_guess() -> None:
    """The handler turns this into a refusal; a default here would price a purchase."""
    assert DealReferenceStore().get(uuid4()) is None


def test_a_redelivered_deal_scored_is_idempotent() -> None:
    """No in-place rescoring (`STATE_TRANSITIONS.md` §1), so a repeat carries the same facts."""
    deal_id, listing_id = uuid4(), uuid4()
    store = DealReferenceStore()

    first = store.record(scored(str(deal_id), str(listing_id)))
    second = store.record(scored(str(deal_id), str(listing_id)))

    assert first == second
    assert len(store) == 1


def test_the_oldest_reference_is_evicted_at_the_cap() -> None:
    """A long-lived process must not grow without bound on a stream it does not control."""
    store = DealReferenceStore(max_deals=2)
    first, second, third = uuid4(), uuid4(), uuid4()

    for deal_id in (first, second, third):
        store.record(scored(str(deal_id), str(uuid4())))

    assert len(store) == 2
    assert store.get(first) is None
    assert store.get(third) is not None


def test_touching_a_reference_again_keeps_it_from_eviction() -> None:
    """Re-recording marks it most-recent, so a redelivered deal is not the one dropped."""
    store = DealReferenceStore(max_deals=2)
    first, second, third = uuid4(), uuid4(), uuid4()
    listing = str(uuid4())

    store.record(scored(str(first), listing))
    store.record(scored(str(second), str(uuid4())))
    store.record(scored(str(first), listing))
    store.record(scored(str(third), str(uuid4())))

    assert store.get(first) is not None
    assert store.get(second) is None


def test_a_malformed_uuid_is_rejected() -> None:
    """Same parser the envelope uses, so a bad id fails here rather than at the live read."""
    with pytest.raises(EventSchemaInvalidError):
        DealReferenceStore().record(scored("not-a-uuid", str(uuid4())))


def test_an_unknown_marketplace_is_rejected() -> None:
    """`ENUMS.md` is closed: a code with no member is a contract gap, not a new marketplace."""
    payload = scored(str(uuid4()), str(uuid4()))
    payload["marketplace"] = "EBAY"

    with pytest.raises(ValueError):
        DealReferenceStore().record(payload)
