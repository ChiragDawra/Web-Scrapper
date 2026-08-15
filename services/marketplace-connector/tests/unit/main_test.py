"""Entry point: fetch, normalize, publish — Sprint 2 Task 2.4.

Definition of Done: "One `LISTING_DISCOVERED` per valid fixture appears on the
bus." The bus here is a recording stand-in for `Redis`, so these run without a
server — but they run the *real* `EventPublisher`, which validates envelope and
payload against the JSON Schemas before its `XADD`. A payload this service could
not actually publish therefore fails here, not only in the integration test.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import cast

import pytest
from redis import Redis
from src import main
from src.base.connector_interface import ConnectorInterface
from src.config import Config
from src.connectors.amazon.connector import AmazonConnector
from src.connectors.flipkart.connector import FlipkartConnector
from src.connectors.myntra.connector import MyntraConnector
from src.connectors.nykaa.connector import NykaaConnector
from src.main import EVENT_TYPE, build_connector, listing_event, publish_batch
from tests.recording_redis import RecordingRedis

from libs.canonical_models import CanonicalProduct
from libs.enums import EventProducerService, MarketplaceCode
from libs.event_bus import Envelope, EventSchemaInvalidError
from libs.event_bus.publisher import EventPublisher

INVALID_FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "amazon_invalid"

VALID_CONFIG = Config(
    redis_url="redis://127.0.0.1:6379/0",
    marketplace=MarketplaceCode.AMAZON,
    poll_interval_seconds=300,
    log_level="INFO",
)


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
    result = publish_batch(AmazonConnector(), publisher)

    assert result.published == 5
    assert result.skipped == 0
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
    zero events." Counted as skipped rather than raised (Task 2.5), but the number
    that matters is the same either way: nothing on the bus."""
    result = publish_batch(AmazonConnector(fixture_dir=INVALID_FIXTURE_DIR), publisher)

    assert result.published == 0
    assert result.skipped == 4
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


@pytest.mark.parametrize(
    ("marketplace", "connector_type"),
    [
        (MarketplaceCode.AMAZON, AmazonConnector),
        (MarketplaceCode.FLIPKART, FlipkartConnector),
        (MarketplaceCode.MYNTRA, MyntraConnector),
        (MarketplaceCode.NYKAA, NykaaConnector),
    ],
)
def test_every_marketplace_code_builds_its_own_connector(
    marketplace: MarketplaceCode, connector_type: type[ConnectorInterface]
) -> None:
    """Sprint 4 completes the set. One deployable per marketplace, and the code it
    is configured with is the one it reads — a container named for Flipkart that
    built the Amazon connector would publish Amazon listings under a Flipkart
    service name."""
    connector = build_connector(replace(VALID_CONFIG, marketplace=marketplace))

    assert isinstance(connector, connector_type)
    assert connector.marketplace is marketplace


def test_no_marketplace_code_is_left_without_a_connector() -> None:
    """A new `marketplace_code` with no entry here is a deployable that starts and
    publishes nothing, which looks exactly like a quiet marketplace."""
    for marketplace in MarketplaceCode:
        assert marketplace in main.CONNECTORS


def test_an_unimplemented_marketplace_fails_at_startup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every code is mapped today, so this pins the behaviour rather than the gap:
    a deployable configured for a marketplace with no connector must fail at
    startup instead of running and emitting nothing."""
    monkeypatch.setattr(main, "CONNECTORS", {})

    with pytest.raises(ValueError, match="no connector implemented"):
        build_connector(replace(VALID_CONFIG, marketplace=MarketplaceCode.FLIPKART))
