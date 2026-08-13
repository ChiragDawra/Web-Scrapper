"""Marketplace Connector entry point — Sprint 2 Task 2.4.

Fetch, normalize, publish. One `LISTING_DISCOVERED` per valid listing
(`EVENT_SCHEMAS.md` §2, payload `{"product": CanonicalProduct}`), produced by
`marketplace-connector` and consumed by `deal-engine`.

Nothing is emitted before `VALIDATION_RULES.md` §1 has passed: `normalize()`
raises `CONN_PARSE_FAILED` for anything that fails a rule (Task 2.2/2.3), and
`EventPublisher.publish` validates envelope *and* payload against the JSON
Schemas before the `XADD`. A partial product therefore cannot reach the bus by
either route, which is the Sprint 2 Definition of Done.

The skip-and-continue behaviour for a malformed listing is Task 2.5 — here a
`ParseFailedError` still propagates, so this commit does not silently swallow
one before the path that handles it deliberately exists.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Mapping
from typing import Final

from redis import Redis

from libs.canonical_models import CanonicalProduct
from libs.enums import MarketplaceCode
from libs.event_bus import Envelope
from libs.event_bus.publisher import EventPublisher
from src.base.connector_interface import ConnectorInterface
from src.config import PRODUCER_SERVICE, Config
from src.connectors.amazon.connector import AmazonConnector

__all__ = ["CONNECTORS", "EVENT_TYPE", "build_connector", "listing_event", "main", "publish_batch"]

logger: Final = logging.getLogger(__name__)

#: `EVENT_SCHEMAS.md` §2. Also the Redis stream name — `publisher.stream_name()`
#: is 1:1 with the event type.
EVENT_TYPE: Final = "LISTING_DISCOVERED"

#: How each deployable builds its connector, keyed by `MARKETPLACE_CODE`. Values
#: are factories rather than classes because `ConnectorInterface` constrains
#: `fetch_raw`/`normalize` and deliberately not `__init__` — what a connector
#: needs to be constructed with is its own business.
#:
#: Flipkart, Myntra and Nykaa arrive in Sprint 10; until then their key is absent
#: rather than mapped to a placeholder, so a misconfigured deployable fails at
#: startup instead of running as a connector that emits nothing.
CONNECTORS: Final[Mapping[MarketplaceCode, Callable[[Config], ConnectorInterface]]] = {
    MarketplaceCode.AMAZON: lambda config: AmazonConnector(fixture_dir=config.fixture_dir),
}


def build_connector(config: Config) -> ConnectorInterface:
    """The connector for the configured marketplace. Raises `ValueError` if unimplemented."""
    try:
        factory = CONNECTORS[config.marketplace]
    except KeyError:
        implemented = ", ".join(str(code) for code in CONNECTORS)
        raise ValueError(
            f"no connector implemented for {config.marketplace}; have: {implemented}"
        ) from None
    return factory(config)


def listing_event(product: CanonicalProduct) -> Envelope:
    """Wrap one product in a `LISTING_DISCOVERED` envelope.

    No `correlation_id`: discovery starts the chain, so there is no upstream
    event to correlate with. The Deal Engine sets one when it scores.
    """
    return Envelope.new(
        event_type=EVENT_TYPE,
        producer_service=PRODUCER_SERVICE,
        payload={"product": product.to_dict()},
    )


def publish_batch(connector: ConnectorInterface, publisher: EventPublisher) -> int:
    """Normalize and publish one fetch batch. Returns the number of events published.

    Published one at a time as each item is normalized rather than after
    collecting the batch: `fetch_raw()` is a generator over a paged source, and
    holding every listing in memory to publish at the end would buy nothing and
    lose everything already fetched if a later page failed.
    """
    published = 0
    for raw in connector.fetch_raw():
        product = connector.normalize(raw)
        publisher.publish(listing_event(product))
        published += 1
        logger.debug(
            "published %s for %s/%s", EVENT_TYPE, product.marketplace, product.external_listing_id
        )
    return published


def main() -> None:
    config = Config.from_env()
    logging.basicConfig(level=config.log_level)

    connector = build_connector(config)
    publisher = EventPublisher(Redis.from_url(config.redis_url))
    logger.info("marketplace-connector starting for %s", config.marketplace)

    published = publish_batch(connector, publisher)
    logger.info("published %d %s events", published, EVENT_TYPE)


if __name__ == "__main__":
    main()
