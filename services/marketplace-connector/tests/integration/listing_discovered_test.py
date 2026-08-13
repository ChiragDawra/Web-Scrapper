"""`LISTING_DISCOVERED` on a real bus — Sprint 2 Task 2.4.

The unit tests prove what the publisher is handed; this proves it survives the
round trip through Redis Streams and comes back as an envelope the Deal Engine
can parse — the literal reading of "appears on the bus".

Runs against the compose Redis (`docker compose up redis`) on logical DB 15,
which is reserved for tests and flushed before each one — never DB 0, where a
running stack keeps its real streams. Skipped, not failed, when Redis is
unreachable, so a lint-and-unit-test-only CI job stays green.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator

import pytest
from redis import Redis
from redis.exceptions import RedisError
from src.connectors.amazon.connector import AmazonConnector
from src.main import EVENT_TYPE, publish_batch

from libs.canonical_models import CanonicalProduct
from libs.enums import EventProducerService, MarketplaceCode
from libs.event_bus import Envelope
from libs.event_bus.consumer import EventConsumer
from libs.event_bus.publisher import ENVELOPE_FIELD, EventPublisher, stream_name

REDIS_TEST_URL = os.environ.get("REDIS_TEST_URL", "redis://127.0.0.1:6379/15")

EXPECTED_ASINS = {"B0BXBQ7C4X", "B09NOMRP01", "B07NOSTOCK", "B0CRATED01", "B08OUTOFST"}


@pytest.fixture
def redis_client() -> Iterator[Redis]:
    client = Redis.from_url(REDIS_TEST_URL)
    try:
        client.ping()
    except RedisError as exc:
        pytest.skip(f"Redis unavailable at {REDIS_TEST_URL}: {exc}")
    client.flushdb()
    yield client
    client.flushdb()
    client.close()


def _envelopes_on_stream(redis_client: Redis) -> list[Envelope]:
    entries = redis_client.xrange(stream_name(EVENT_TYPE))
    return [
        Envelope.from_dict(json.loads(fields[ENVELOPE_FIELD.encode()])) for _, fields in entries
    ]


def test_one_listing_discovered_per_valid_fixture_lands_on_the_stream(
    redis_client: Redis,
) -> None:
    """Task 2.4 Definition of Done, against a real Redis."""
    result = publish_batch(AmazonConnector(), EventPublisher(redis_client))
    envelopes = _envelopes_on_stream(redis_client)

    assert result.published == 5
    assert result.skipped == 0
    assert len(envelopes) == 5
    assert {
        CanonicalProduct.from_dict(envelope.payload["product"]).external_listing_id
        for envelope in envelopes
    } == EXPECTED_ASINS


def test_the_deal_engine_reads_them_back_as_products(redis_client: Redis) -> None:
    """The consumer side of the contract: `deal-engine` is the declared consumer,
    so the test reads as that service, through the same consumer-group API it will use."""
    publish_batch(AmazonConnector(), EventPublisher(redis_client))

    consumer = EventConsumer(
        redis_client,
        consumer_service=EventProducerService.DEAL_ENGINE,
        event_types=[EVENT_TYPE],
        consumer_name="deal-engine-1",
        block_ms=200,
    )
    consumer.ensure_groups()

    received = consumer.read()
    products = [CanonicalProduct.from_dict(event.envelope.payload["product"]) for event in received]

    assert len(products) == 5
    assert all(product.marketplace is MarketplaceCode.AMAZON for product in products)
    assert all(product.price > 0 for product in products)
    assert all(product.in_stock in (True, False) for product in products)
