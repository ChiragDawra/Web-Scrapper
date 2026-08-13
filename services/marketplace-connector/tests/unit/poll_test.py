"""The poll loop survives what a marketplace throws at it — Sprint 2 Task 2.5.

"No crash of the poll loop" is the requirement, so these tests are mostly about
what does *not* stop the process: a malformed listing (skipped per item), a 429
(ends the cycle, retried next one). And one about what does — a defect must not
be swallowed into a process that looks healthy while publishing nothing.

`sleep` is injected everywhere so the suite never waits an interval.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Any, ClassVar, cast

import pytest
from redis import Redis
from src.base.connector_interface import (
    ConnectorInterface,
    ConnectorTimeoutError,
    RateLimitedError,
)
from src.connectors.amazon.connector import AmazonConnector
from src.main import poll
from tests.recording_redis import RecordingRedis

from libs.canonical_models import CanonicalProduct
from libs.enums import MarketplaceCode
from libs.event_bus.publisher import EventPublisher

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
MIXED_FIXTURE_DIR = FIXTURES / "amazon_mixed"


@pytest.fixture
def bus() -> RecordingRedis:
    return RecordingRedis()


@pytest.fixture
def publisher(bus: RecordingRedis) -> EventPublisher:
    return EventPublisher(cast(Redis, bus))


class RecordingSleep:
    """Records how long the loop would have waited, without waiting."""

    def __init__(self) -> None:
        self.calls: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


class FlakyConnector(ConnectorInterface):
    """Fails the fetch on the first `failures` cycles, then reads the mixed batch."""

    marketplace: ClassVar[MarketplaceCode] = MarketplaceCode.AMAZON

    def __init__(self, failures: int, error: Exception) -> None:
        self._remaining = failures
        self._error = error
        self._inner = AmazonConnector(fixture_dir=MIXED_FIXTURE_DIR)
        self.cycles = 0

    def fetch_raw(self) -> Iterator[dict[str, Any]]:
        self.cycles += 1
        if self._remaining > 0:
            self._remaining -= 1
            raise self._error
        yield from self._inner.fetch_raw()

    def normalize(self, raw_marketplace_response: Any) -> CanonicalProduct:
        return self._inner.normalize(raw_marketplace_response)


def test_a_cycle_publishes_the_valid_listings_and_skips_the_rest(
    bus: RecordingRedis, publisher: EventPublisher
) -> None:
    connector = AmazonConnector(fixture_dir=MIXED_FIXTURE_DIR)

    result = poll(connector, publisher, interval_seconds=300, max_cycles=1, sleep=lambda _s: None)

    assert (result.published, result.skipped) == (2, 1)
    assert len(bus.entries) == 2


def test_the_loop_runs_every_cycle_and_totals_them(
    bus: RecordingRedis, publisher: EventPublisher
) -> None:
    """Poll means poll: the same batch re-read on a schedule. Dedup on
    `(marketplace, external_listing_id)` is the Deal Engine's job, not this loop's."""
    connector = AmazonConnector(fixture_dir=MIXED_FIXTURE_DIR)

    result = poll(connector, publisher, interval_seconds=300, max_cycles=3, sleep=lambda _s: None)

    assert (result.published, result.skipped) == (6, 3)
    assert len(bus.entries) == 6


def test_the_loop_waits_the_configured_interval_between_cycles(
    publisher: EventPublisher,
) -> None:
    """Two waits for three cycles — no pointless sleep after the last one."""
    sleep = RecordingSleep()

    poll(
        AmazonConnector(fixture_dir=MIXED_FIXTURE_DIR),
        publisher,
        interval_seconds=45,
        max_cycles=3,
        sleep=sleep,
    )

    assert sleep.calls == [45, 45]


@pytest.mark.parametrize(
    "error",
    [RateLimitedError("429 from marketplace"), ConnectorTimeoutError("read timed out")],
)
def test_a_retryable_fetch_failure_ends_the_cycle_not_the_process(
    bus: RecordingRedis, publisher: EventPublisher, error: Exception
) -> None:
    """A connector that exits on the first 429 stops ingesting until something
    restarts it. The next cycle publishes normally."""
    connector = FlakyConnector(failures=1, error=error)

    result = poll(connector, publisher, interval_seconds=1, max_cycles=2, sleep=lambda _s: None)

    assert connector.cycles == 2
    assert (result.published, result.skipped) == (2, 1)
    assert len(bus.entries) == 2


def test_a_retryable_failure_is_logged_with_its_code(
    publisher: EventPublisher, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.WARNING, logger="src.main"):
        poll(
            FlakyConnector(failures=1, error=RateLimitedError("429 from marketplace")),
            publisher,
            interval_seconds=1,
            max_cycles=1,
            sleep=lambda _s: None,
        )

    assert any("CONN_RATE_LIMITED" in record.getMessage() for record in caplog.records)


def test_a_failing_cycle_still_waits_before_retrying(publisher: EventPublisher) -> None:
    """Retrying a 429 immediately is how a soft throttle becomes a hard ban."""
    sleep = RecordingSleep()

    poll(
        FlakyConnector(failures=1, error=RateLimitedError("429")),
        publisher,
        interval_seconds=30,
        max_cycles=2,
        sleep=sleep,
    )

    assert sleep.calls == [30]


def test_a_defect_is_not_swallowed_by_the_loop(publisher: EventPublisher) -> None:
    """Only `ConnectorError` is marketplace noise. A `KeyError` from a broken
    mapping must surface, not become an endlessly retried silent no-op."""

    class BrokenConnector(ConnectorInterface):
        marketplace: ClassVar[MarketplaceCode] = MarketplaceCode.AMAZON

        def fetch_raw(self) -> Iterator[dict[str, Any]]:
            raise KeyError("Offers")
            yield  # pragma: no cover - unreachable, makes this a generator

        def normalize(self, raw_marketplace_response: Any) -> CanonicalProduct:
            raise AssertionError("normalize must not be reached")

    with pytest.raises(KeyError):
        poll(BrokenConnector(), publisher, interval_seconds=1, max_cycles=2, sleep=lambda _s: None)
