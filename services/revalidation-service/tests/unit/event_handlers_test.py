"""`DEAL_REVALIDATION_REQUEST` in, `DEAL_REVALIDATED` out — Sprint 5 Tasks 5.2 and 5.3.

No broker: the event's shape is fixed by `EVENT_SCHEMAS.md` §3 and the JSON
Schemas, and `EventPublisher` runs the same `validate_event()` before every
`XADD`, so a `RecordingRedis` proves both what was published and that it was
publishable.

The negative assertions carry most of the weight. Task 5.3's Definition of Done
is an absence — "no event published" — and an absence is only worth asserting
against a publisher that would really have published.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from src.handlers.event_handlers import (
    DEAL_REVALIDATED,
    DEAL_REVALIDATION_REQUEST,
    DEAL_SCORED,
    UnknownDealError,
    handle_deal_revalidation_request,
    handle_deal_scored,
    revalidated_event,
)
from src.services.deal_reference import DealReferenceStore
from src.services.listing_source import ListingSnapshot, ListingUnreadableError
from src.services.revalidator import TimeoutBudget

from libs.canonical_models import RevalidationResult
from libs.enums import EventProducerService
from libs.event_bus.consumer import ReceivedEvent
from libs.event_bus.envelope import Envelope
from libs.event_bus.payloads import validate_event
from libs.event_bus.publisher import EventPublisher
from libs.validation_rules import REVALIDATION_TIMEOUT_SECONDS
from tests.recording_redis import RecordingRedis

SCORED_PRICE = 100_000


class FakeClock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class StubSource:
    def __init__(self, *, current_price: int = SCORED_PRICE, in_stock: bool = True) -> None:
        self.current_price = current_price
        self.in_stock = in_stock

    def read(self, listing_id: UUID) -> ListingSnapshot:
        return ListingSnapshot(
            listing_id=listing_id,
            current_price=self.current_price,
            in_stock=self.in_stock,
            observed_at=datetime.now(UTC),
        )


class UnreadableSource:
    def read(self, listing_id: UUID) -> ListingSnapshot:
        raise ListingUnreadableError(f"listing {listing_id} gave no price")


def received(
    event_type: str, payload: dict[str, Any], producer: EventProducerService
) -> ReceivedEvent:
    envelope = Envelope.new(event_type=event_type, producer_service=producer, payload=payload)
    return ReceivedEvent(stream=event_type, entry_id="1-0", envelope=envelope)


def scored_event(deal_id: UUID, listing_id: UUID, *, price: int = SCORED_PRICE) -> ReceivedEvent:
    return received(
        DEAL_SCORED,
        {
            "deal_id": str(deal_id),
            "listing_id": str(listing_id),
            "marketplace": "AMAZON",
            "score": 88.0,
            "score_breakdown": {
                "discount_score": 40.0,
                "brand_score": 20.0,
                "rating_score": 15.0,
                "velocity_score": 13.0,
                "weights_version": "builtin-v1",
            },
            "detected_price": price,
            "reference_price": price * 2,
            "discount_pct": 50.0,
            "expires_at": "2026-01-02T12:00:00+00:00",
        },
        EventProducerService.DEAL_ENGINE,
    )


def request_event(
    deal_id: UUID, listing_id: UUID, *, correlation_id: UUID | None = None
) -> ReceivedEvent:
    return received(
        DEAL_REVALIDATION_REQUEST,
        {
            "deal_id": str(deal_id),
            "listing_id": str(listing_id),
            # Q15: the request's correlation_id *is* the deal_id.
            "correlation_id": str(correlation_id or deal_id),
        },
        EventProducerService.TELEGRAM_BOT,
    )


@pytest.fixture
def redis() -> RecordingRedis:
    return RecordingRedis()


@pytest.fixture
def publisher(redis: RecordingRedis) -> EventPublisher:
    return EventPublisher(redis)  # type: ignore[arg-type]


@pytest.fixture
def references() -> DealReferenceStore:
    return DealReferenceStore()


def warmed(references: DealReferenceStore, deal_id: UUID, listing_id: UUID) -> None:
    handle_deal_scored(scored_event(deal_id, listing_id), references=references)


def test_deal_scored_only_feeds_the_projection(
    redis: RecordingRedis, references: DealReferenceStore
) -> None:
    """This service emits nothing from `DEAL_SCORED`; the Bot remains its consumer."""
    deal_id, listing_id = uuid4(), uuid4()

    reference = handle_deal_scored(scored_event(deal_id, listing_id), references=references)

    assert reference.detected_price == SCORED_PRICE
    assert redis.entries == []


def test_a_request_publishes_deal_revalidated(
    publisher: EventPublisher, redis: RecordingRedis, references: DealReferenceStore
) -> None:
    """Task 5.2's happy path, end to end through the real publisher."""
    deal_id, listing_id = uuid4(), uuid4()
    warmed(references, deal_id, listing_id)

    handled = handle_deal_revalidation_request(
        publisher,
        request_event(deal_id, listing_id),
        references=references,
        source=StubSource(current_price=101_000),
        budget=TimeoutBudget(clock=FakeClock()),
    )

    assert handled.published is True
    assert handled.result is not None
    assert handled.result.changed is False
    [(stream, _)] = redis.entries
    assert stream == DEAL_REVALIDATED


def test_the_published_payload_carries_the_result_flat(
    publisher: EventPublisher, redis: RecordingRedis, references: DealReferenceStore
) -> None:
    deal_id, listing_id = uuid4(), uuid4()
    warmed(references, deal_id, listing_id)

    handle_deal_revalidation_request(
        publisher,
        request_event(deal_id, listing_id),
        references=references,
        source=StubSource(current_price=150_000),
        budget=TimeoutBudget(clock=FakeClock()),
    )

    [envelope] = redis.envelopes()
    assert envelope["payload"]["deal_id"] == str(deal_id)
    assert envelope["payload"]["listing_id"] == str(listing_id)
    assert envelope["payload"]["current_price"] == 150_000
    assert envelope["payload"]["changed"] is True
    assert envelope["producer_service"] == str(EventProducerService.REVALIDATION_SERVICE)


def test_the_correlation_id_threads_through_unchanged(
    publisher: EventPublisher, redis: RecordingRedis, references: DealReferenceStore
) -> None:
    """Q15: set to `deal_id` by the request, "propagated unchanged" by the answer."""
    deal_id, listing_id = uuid4(), uuid4()
    warmed(references, deal_id, listing_id)

    handle_deal_revalidation_request(
        publisher,
        request_event(deal_id, listing_id),
        references=references,
        source=StubSource(),
        budget=TimeoutBudget(clock=FakeClock()),
    )

    [envelope] = redis.envelopes()
    assert envelope["correlation_id"] == str(deal_id)


def test_a_correlation_id_that_is_not_the_deal_id_is_refused(
    publisher: EventPublisher, redis: RecordingRedis, references: DealReferenceStore
) -> None:
    """Accepting it would scatter one deal's rounds across two correlation ids."""
    deal_id, listing_id = uuid4(), uuid4()
    warmed(references, deal_id, listing_id)

    with pytest.raises(ValueError, match="must equal deal_id"):
        handle_deal_revalidation_request(
            publisher,
            request_event(deal_id, listing_id, correlation_id=uuid4()),
            references=references,
            source=StubSource(),
            budget=TimeoutBudget(clock=FakeClock()),
        )

    assert redis.entries == []


def test_a_closed_budget_publishes_nothing(
    publisher: EventPublisher, redis: RecordingRedis, references: DealReferenceStore
) -> None:
    """Task 5.3's Definition of Done: a forced-slow request results in no event."""
    deal_id, listing_id = uuid4(), uuid4()
    warmed(references, deal_id, listing_id)
    clock = FakeClock()
    budget = TimeoutBudget(clock=clock)
    clock.advance(REVALIDATION_TIMEOUT_SECONDS + 1)

    handled = handle_deal_revalidation_request(
        publisher,
        request_event(deal_id, listing_id),
        references=references,
        source=StubSource(),
        budget=budget,
    )

    assert handled.published is False
    assert handled.result is None
    assert redis.entries == []


def test_a_read_that_overruns_the_budget_publishes_nothing(
    publisher: EventPublisher, redis: RecordingRedis, references: DealReferenceStore
) -> None:
    """The slow part is the live read, which is the realistic shape of the timeout."""
    deal_id, listing_id = uuid4(), uuid4()
    warmed(references, deal_id, listing_id)
    clock = FakeClock()

    class SlowSource(StubSource):
        def read(self, listing_id: UUID) -> ListingSnapshot:
            clock.advance(REVALIDATION_TIMEOUT_SECONDS + 0.5)
            return super().read(listing_id)

    handled = handle_deal_revalidation_request(
        publisher,
        request_event(deal_id, listing_id),
        references=references,
        source=SlowSource(),
        budget=TimeoutBudget(clock=clock),
    )

    assert handled.published is False
    assert redis.entries == []


def test_an_unknown_deal_raises_so_the_event_is_redelivered(
    publisher: EventPublisher, redis: RecordingRedis, references: DealReferenceStore
) -> None:
    """A cold projection is the ordinary cause, and one redelivery fixes it."""
    deal_id, listing_id = uuid4(), uuid4()

    with pytest.raises(UnknownDealError):
        handle_deal_revalidation_request(
            publisher,
            request_event(deal_id, listing_id),
            references=references,
            source=StubSource(),
            budget=TimeoutBudget(clock=FakeClock()),
        )

    assert redis.entries == []


def test_a_request_naming_another_listing_is_refused(
    publisher: EventPublisher, redis: RecordingRedis, references: DealReferenceStore
) -> None:
    """Comparing two listings' prices is not a tolerance check."""
    deal_id, listing_id = uuid4(), uuid4()
    warmed(references, deal_id, listing_id)

    with pytest.raises(ValueError, match="was scored against listing"):
        handle_deal_revalidation_request(
            publisher,
            request_event(deal_id, uuid4()),
            references=references,
            source=StubSource(),
            budget=TimeoutBudget(clock=FakeClock()),
        )

    assert redis.entries == []


def test_an_unreadable_listing_publishes_nothing(
    publisher: EventPublisher, redis: RecordingRedis, references: DealReferenceStore
) -> None:
    """No price was observed, so there is no honest `RevalidationResult` to send."""
    deal_id, listing_id = uuid4(), uuid4()
    warmed(references, deal_id, listing_id)

    handled = handle_deal_revalidation_request(
        publisher,
        request_event(deal_id, listing_id),
        references=references,
        source=UnreadableSource(),
        budget=TimeoutBudget(clock=FakeClock()),
    )

    assert handled.published is False
    assert redis.entries == []


def test_the_event_passes_the_published_schema() -> None:
    """The same validation the publisher runs before the XADD."""
    deal_id, listing_id = uuid4(), uuid4()
    result = RevalidationResult(
        deal_id=deal_id,
        listing_id=listing_id,
        current_price=99_000,
        in_stock=True,
        changed=False,
        checked_at=datetime.now(UTC),
    )

    validate_event(revalidated_event(result, correlation_id=deal_id).to_dict())
