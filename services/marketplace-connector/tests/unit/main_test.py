"""Entry point: fetch, normalize, publish — Sprint 2 Task 2.4.

Definition of Done: "One `LISTING_DISCOVERED` per valid fixture appears on the
bus." The bus here is a recording stand-in for `Redis`, so these run without a
server — but they run the *real* `EventPublisher`, which validates envelope and
payload against the JSON Schemas before its `XADD`. A payload this service could
not actually publish therefore fails here, not only in the integration test.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any, cast

import pytest
from redis import Redis
from src.base.connector_interface import ParseFailedError
from src.config import Config
from src.connectors.amazon.connector import AmazonConnector
from src.main import EVENT_TYPE, build_connector, listing_event, publish_batch

from libs.canonical_models import CanonicalProduct
from libs.enums import EventProducerService, MarketplaceCode
from libs.event_bus import Envelope, EventSchemaInvalidError
from libs.event_bus.publisher import ENVELOPE_FIELD, EventPublisher

INVALID_FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "amazon_invalid"

VALID_CONFIG = Config(
    redis_url="redis://127.0.0.1:6379/0",
    marketplace=MarketplaceCode.AMAZON,
    poll_interval_seconds=300,
    log_level="INFO",
)


class RecordingRedis:
    """Captures what would have been `XADD`ed, in order.

    A stand-in rather than a mock: the assertions are about the events on the
    stream, so the double records them and does nothing else.
    """

    def __init__(self) -> None:
        self.entries: list[tuple[str, dict[str, str]]] = []

    def xadd(
        self,
        name: str,
        fields: dict[str, str],
        maxlen: int | None = None,
        approximate: bool = True,
    ) -> bytes:
        self.entries.append((name, fields))
        return f"{len(self.entries)}-0".encode()

    def envelopes(self) -> list[dict[str, Any]]:
        return [json.loads(fields[ENVELOPE_FIELD]) for _, fields in self.entries]


@pytest.fixture
def bus() -> RecordingRedis:
    return RecordingRedis()


@pytest.fixture
def publisher(bus: RecordingRedis) -> EventPublisher:
    return EventPublisher(cast(Redis, bus))


def test_one_event_per_valid_fixture_reaches_the_bus(
    bus: RecordingRedis, publisher: EventPublisher
) -> None:
    """The Task 2.4 Definition of Done, stated directly."""
    published = publish_batch(AmazonConnector(), publisher)

    assert published == 5
    assert len(bus.entries) == 5


def test_every_event_lands_on_the_listing_discovered_stream(
    bus: RecordingRedis, publisher: EventPublisher
) -> None:
    """Stream naming is 1:1 with `event_type` (`publisher.stream_name`)."""
    publish_batch(AmazonConnector(), publisher)

    assert {name for name, _ in bus.entries} == {EVENT_TYPE}


def test_each_envelope_is_a_well_formed_listing_discovered(
    bus: RecordingRedis, publisher: EventPublisher
) -> None:
    """`EVENT_SCHEMAS.md` §1: producer is the emitting service, version starts at 1."""
    publish_batch(AmazonConnector(), publisher)

    for raw in bus.envelopes():
        envelope = Envelope.from_dict(raw)
        assert envelope.event_type == EVENT_TYPE
        assert envelope.producer_service is EventProducerService.MARKETPLACE_CONNECTOR
        assert envelope.version == 1
        # Discovery starts the chain — nothing upstream to correlate with.
        assert envelope.correlation_id is None
        assert envelope.produced_at.tzinfo is not None


def test_each_payload_carries_the_normalized_product(
    bus: RecordingRedis, publisher: EventPublisher
) -> None:
    """§2 payload is `{"product": CanonicalProduct}` — and it round-trips, so the
    Deal Engine reconstructs exactly what the connector normalized."""
    connector = AmazonConnector()
    normalized = {
        product.external_listing_id: product
        for product in (connector.normalize(raw) for raw in connector.fetch_raw())
    }

    publish_batch(AmazonConnector(), publisher)
    published = [CanonicalProduct.from_dict(raw["payload"]["product"]) for raw in bus.envelopes()]

    assert {product.external_listing_id: product for product in published} == normalized
    assert all(product.marketplace is MarketplaceCode.AMAZON for product in published)


def test_every_event_id_is_distinct(bus: RecordingRedis, publisher: EventPublisher) -> None:
    """Five listings are five events, not one event published five times."""
    publish_batch(AmazonConnector(), publisher)

    assert len({raw["event_id"] for raw in bus.envelopes()}) == 5


def test_a_malformed_fixture_produces_zero_events(
    bus: RecordingRedis, publisher: EventPublisher
) -> None:
    """Sprint 2 acceptance criteria: "a fixture missing a required field produces
    zero events." Skipping it and carrying on is Task 2.5; refusing to emit it is
    this task's half of that guarantee."""
    connector = AmazonConnector(fixture_dir=INVALID_FIXTURE_DIR)

    with pytest.raises(ParseFailedError):
        publish_batch(connector, publisher)

    assert bus.entries == []


def test_listing_event_payload_passes_schema_validation(publisher: EventPublisher) -> None:
    """The guard behind the emit: publish validates §2 before the XADD."""
    product = AmazonConnector().normalize(next(iter(AmazonConnector().fetch_raw())))

    publisher.publish(listing_event(product))


def test_a_product_that_breaks_the_schema_is_rejected_before_the_bus(
    bus: RecordingRedis, publisher: EventPublisher
) -> None:
    """A partial product cannot reach the bus even if it somehow bypasses §1 —
    `EventPublisher` validates the payload, so nothing is XADDed."""
    product = AmazonConnector().normalize(next(iter(AmazonConnector().fetch_raw())))
    broken = replace(product, price=0)

    with pytest.raises(EventSchemaInvalidError):
        publisher.publish(listing_event(broken))

    assert bus.entries == []


def test_build_connector_returns_the_configured_marketplaces_connector() -> None:
    assert isinstance(build_connector(VALID_CONFIG), AmazonConnector)


def test_build_connector_passes_the_configured_fixture_directory() -> None:
    connector = build_connector(replace(VALID_CONFIG, fixture_dir=INVALID_FIXTURE_DIR))

    assert isinstance(connector, AmazonConnector)
    assert connector.fixture_dir == INVALID_FIXTURE_DIR


def test_an_unimplemented_marketplace_fails_at_startup() -> None:
    """Sprint 10 builds the other three. Until then a deployable configured for
    one must not start and publish nothing."""
    with pytest.raises(ValueError, match="no connector implemented"):
        build_connector(replace(VALID_CONFIG, marketplace=MarketplaceCode.FLIPKART))
