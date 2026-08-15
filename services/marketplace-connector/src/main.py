"""Marketplace Connector entry point — Sprint 2 Task 2.4.

Fetch, normalize, publish. One `LISTING_DISCOVERED` per valid listing
(`EVENT_SCHEMAS.md` §2, payload `{"product": CanonicalProduct}`), produced by
`marketplace-connector` and consumed by `deal-engine`.

Nothing is emitted before `VALIDATION_RULES.md` §1 has passed: `normalize()`
raises `CONN_PARSE_FAILED` for anything that fails a rule (Task 2.2/2.3), and
`EventPublisher.publish` validates envelope *and* payload against the JSON
Schemas before the `XADD`. A partial product therefore cannot reach the bus by
either route, which is the Sprint 2 Definition of Done.

A malformed listing is skipped, not fatal (Task 2.5): `iter_products` drops it
with a `CONN_PARSE_FAILED` log and the batch continues, and a whole-batch
`ConnectorError` ends only the current poll cycle. The process keeps ingesting.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Final

from redis import Redis

from libs.canonical_models import CanonicalProduct
from libs.enums import MarketplaceCode
from libs.event_bus import Envelope
from libs.event_bus.publisher import EventPublisher
from src.base.connector_interface import (
    ConnectorError,
    ConnectorInterface,
    ParseFailedError,
    iter_products,
)
from src.config import PRODUCER_SERVICE, Config
from src.connectors.amazon.connector import AmazonConnector
from src.connectors.flipkart.connector import FlipkartConnector
from src.connectors.myntra.connector import MyntraConnector
from src.connectors.nykaa.connector import NykaaConnector

__all__ = [
    "CONNECTORS",
    "EVENT_TYPE",
    "BatchResult",
    "build_connector",
    "listing_event",
    "main",
    "poll",
    "publish_batch",
]

logger: Final = logging.getLogger(__name__)

#: `EVENT_SCHEMAS.md` §2. Also the Redis stream name — `publisher.stream_name()`
#: is 1:1 with the event type.
EVENT_TYPE: Final = "LISTING_DISCOVERED"

#: How each deployable builds its connector, keyed by `MARKETPLACE_CODE`. Values
#: are factories rather than classes because `ConnectorInterface` constrains
#: `fetch_raw`/`normalize` and deliberately not `__init__` — what a connector
#: needs to be constructed with is its own business.
#:
#: All four marketplaces as of Sprint 4 (Tasks 4.1.2, 4.2.2, 4.3.2). A code with
#: no entry stays absent rather than mapped to a placeholder, so a misconfigured
#: deployable fails at startup instead of running as a connector that emits
#: nothing.
#:
#: `config.fixture_dir` is `None` unless `MARKETPLACE_FIXTURE_DIR` is set, and
#: each connector then falls back to its own recorded directory — one env var
#: for four deployables, and no deployable reading another marketplace's
#: recordings by default.
CONNECTORS: Final[Mapping[MarketplaceCode, Callable[[Config], ConnectorInterface]]] = {
    MarketplaceCode.AMAZON: lambda config: AmazonConnector(fixture_dir=config.fixture_dir),
    MarketplaceCode.FLIPKART: lambda config: FlipkartConnector(fixture_dir=config.fixture_dir),
    MarketplaceCode.MYNTRA: lambda config: MyntraConnector(fixture_dir=config.fixture_dir),
    MarketplaceCode.NYKAA: lambda config: NykaaConnector(fixture_dir=config.fixture_dir),
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


@dataclass(frozen=True, slots=True)
class BatchResult:
    """What one fetch batch produced. `skipped` is `CONN_PARSE_FAILED` drops."""

    published: int
    skipped: int


def publish_batch(connector: ConnectorInterface, publisher: EventPublisher) -> BatchResult:
    """Normalize and publish one fetch batch, skipping unparseable listings.

    Published one at a time as each item is normalized rather than after
    collecting the batch: `fetch_raw()` is a generator over a paged source, and
    holding every listing in memory to publish at the end would buy nothing and
    lose everything already fetched if a later page failed.
    """
    skipped = 0

    def count_skip(_raw: Any, _exc: ParseFailedError) -> None:
        nonlocal skipped
        skipped += 1

    published = 0
    for product in iter_products(connector, on_skip=count_skip):
        publisher.publish(listing_event(product))
        published += 1
        logger.debug(
            "published %s for %s/%s", EVENT_TYPE, product.marketplace, product.external_listing_id
        )
    return BatchResult(published=published, skipped=skipped)


def poll(
    connector: ConnectorInterface,
    publisher: EventPublisher,
    *,
    interval_seconds: int,
    max_cycles: int | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> BatchResult:
    """Fetch-and-publish forever, one batch per interval — `SERVICE_INTERFACES.md` §1
    ("runs on a schedule/poll"). Returns the totals across every cycle run.

    A whole-batch `ConnectorError` — rate limiting, a timeout, an expired
    session — ends that cycle and is retried on the next one instead of killing
    the process: those conditions are transient by definition
    (`ERROR_CODES.md` marks them retryable), and a connector that exits on the
    first 429 stops ingesting until something restarts it. Per-item
    `CONN_PARSE_FAILED` never reaches here; `iter_products` has already skipped
    it.

    Anything that is *not* a `ConnectorError` propagates. A schema-invalid
    publish or a lost Redis connection is a defect or an outage, not marketplace
    noise, and swallowing it would leave a process that looks healthy while
    emitting nothing. `max_cycles` bounds the loop for tests and one-shot runs;
    `sleep` is injected so a test does not spend the interval waiting.
    """
    published = skipped = 0
    cycle = 0
    while max_cycles is None or cycle < max_cycles:
        cycle += 1
        try:
            result = publish_batch(connector, publisher)
        except ConnectorError as exc:
            logger.warning(
                "%s: batch failed, retrying in %ds (retryable=%s): %s",
                exc.code,
                interval_seconds,
                exc.retryable,
                exc.detail or "no detail",
            )
        else:
            published += result.published
            skipped += result.skipped
            logger.info(
                "cycle %d: published %d %s, skipped %d",
                cycle,
                result.published,
                EVENT_TYPE,
                result.skipped,
            )
        if max_cycles is None or cycle < max_cycles:
            sleep(interval_seconds)
    return BatchResult(published=published, skipped=skipped)


def main() -> None:
    config = Config.from_env()
    logging.basicConfig(level=config.log_level)

    connector = build_connector(config)
    publisher = EventPublisher(Redis.from_url(config.redis_url))
    logger.info(
        "marketplace-connector starting for %s, polling every %ds",
        config.marketplace,
        config.poll_interval_seconds,
    )

    poll(connector, publisher, interval_seconds=config.poll_interval_seconds)


if __name__ == "__main__":
    main()
