"""The `DEAL_SCORED` envelope — Sprint 3 Task 3.5.

No broker needed: the event's shape is fixed by `EVENT_SCHEMAS.md` §2 and by
the JSON Schemas in `libs/event_bus/schema/`, and `validate_event()` is the
same check the publisher runs before the `XADD`. Asserting it here means a
missing field fails in milliseconds rather than at the far end of a stream.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from src.handlers.event_handlers import DEAL_SCORED, deal_scored_event
from src.main import HANDLERS, handle_event

from libs.canonical_models.scored_deal import ScoreBreakdown, ScoredDeal
from libs.enums import EventProducerService, MarketplaceCode
from libs.event_bus.consumer import ReceivedEvent
from libs.event_bus.envelope import Envelope
from libs.event_bus.payloads import validate_event

BREAKDOWN = ScoreBreakdown(
    discount_score=31.25,
    brand_score=18.75,
    rating_score=14.06,
    velocity_score=25.0,
    weights_version="builtin-v1",
)


def scored_deal(listing_id: object = None) -> ScoredDeal:
    return ScoredDeal(
        listing_id=listing_id or uuid4(),  # type: ignore[arg-type]
        marketplace=MarketplaceCode.AMAZON,
        score=89.06,
        score_breakdown=BREAKDOWN,
        detected_price=100000,
        reference_price=200000,
        discount_pct=50.0,
        expires_at=datetime.now(UTC) + timedelta(hours=6),
    )


def test_event_passes_the_published_schema() -> None:
    """The same validation the publisher runs before the XADD."""
    envelope = deal_scored_event(uuid4(), scored_deal())

    validate_event(envelope.to_dict())


def test_payload_carries_every_contract_field() -> None:
    deal_id = uuid4()
    scored = scored_deal()

    payload = deal_scored_event(deal_id, scored).payload

    assert payload["deal_id"] == str(deal_id)
    assert payload["listing_id"] == str(scored.listing_id)
    assert payload["marketplace"] == str(MarketplaceCode.AMAZON)
    assert payload["score"] == 89.06
    assert payload["score_breakdown"] == BREAKDOWN.to_dict()
    assert payload["detected_price"] == 100000
    assert payload["reference_price"] == 200000
    assert payload["discount_pct"] == 50.0
    assert payload["expires_at"] == scored.expires_at.isoformat()


def test_marketplace_is_carried_not_re_derived() -> None:
    """ADR-009: downstream consumers read it off the event, never join for it."""
    for code in (MarketplaceCode.AMAZON, MarketplaceCode.FLIPKART):
        scored = ScoredDeal(
            listing_id=uuid4(),
            marketplace=code,
            score=50.0,
            score_breakdown=BREAKDOWN,
            detected_price=1,
            reference_price=2,
            discount_pct=50.0,
            expires_at=datetime.now(UTC),
        )

        assert deal_scored_event(uuid4(), scored).payload["marketplace"] == str(code)


def test_producer_is_the_deal_engine() -> None:
    envelope = deal_scored_event(uuid4(), scored_deal())

    assert envelope.event_type == DEAL_SCORED
    assert envelope.producer_service is EventProducerService.DEAL_ENGINE


def test_correlation_id_is_carried_when_given() -> None:
    """Ties the deal to the causal chain that produced it (`EVENT_SCHEMAS.md` §1)."""
    correlation_id = uuid4()

    envelope = deal_scored_event(uuid4(), scored_deal(), correlation_id=correlation_id)

    assert envelope.correlation_id == correlation_id


def test_an_unregistered_event_type_raises() -> None:
    """A wiring bug, not a data problem — acknowledging it away would hide it."""
    event = ReceivedEvent(
        stream="SOMETHING_ELSE",
        entry_id="1-0",
        envelope=Envelope.new(
            event_type="SOMETHING_ELSE",
            producer_service=EventProducerService.DEAL_ENGINE,
            payload={},
        ),
    )

    with pytest.raises(KeyError, match="no handler registered"):
        handle_event(None, None, event, scoring_config=None)  # type: ignore[arg-type]


def test_listing_discovered_is_wired() -> None:
    assert "LISTING_DISCOVERED" in HANDLERS
