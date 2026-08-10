"""`processed_events` dedup helper against a real Postgres — Sprint 1 Task 1.5.

Definition of Done: "Replaying the same `event_id` for the same
`consumer_service` is skipped and logged as `SYS_DUPLICATE_EVENT`."
`test_replaying_the_same_event_is_skipped_and_logged` is that, verbatim.

Runs against the compose Postgres with `alembic upgrade head` applied; skipped,
not failed, when either is missing. Every test rolls its transaction back, so
the developer's database is left exactly as it was found.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Iterator
from uuid import UUID

import psycopg
import pytest

from libs.enums import EventProducerService
from libs.event_bus.consumer import ReceivedEvent
from libs.event_bus.dedup import (
    PROCESSED_EVENTS_RETENTION_DAYS,
    is_processed,
    mark_processed,
    process_once,
    purge_processed_events,
)
from libs.event_bus.envelope import Envelope

POSTGRES_TEST_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://businessscrapper:businessscrapper@127.0.0.1:5432/businessscrapper",
)

CONSUMER = EventProducerService.DEAL_ENGINE
OTHER_CONSUMER = EventProducerService.INVENTORY_SERVICE

DEAL_ID = "3f2504e0-4f89-41d3-9a0c-0305e82c3301"
USER_ID = "3f2504e0-4f89-41d3-9a0c-0305e82c3302"


@pytest.fixture
def conn() -> Iterator[psycopg.Connection]:
    try:
        connection = psycopg.connect(POSTGRES_TEST_URL, connect_timeout=3)
    except psycopg.Error as exc:
        pytest.skip(f"Postgres unavailable at {POSTGRES_TEST_URL}: {exc}")
    with connection:
        with connection.cursor() as cur:
            cur.execute("SELECT to_regclass('public.processed_events')")
            if cur.fetchone()[0] is None:  # type: ignore[index]
                pytest.skip("run `alembic upgrade head` in infra/postgres first")
        try:
            yield connection
        finally:
            # Never commit: the test database is the developer's, not the suite's.
            connection.rollback()


def _event() -> ReceivedEvent:
    envelope = Envelope.new(
        event_type="USER_INTERESTED",
        producer_service=EventProducerService.TELEGRAM_BOT,
        payload={"deal_id": DEAL_ID, "telegram_user_id": USER_ID},
    )
    return ReceivedEvent(stream="USER_INTERESTED", entry_id="1-0", envelope=envelope)


def test_unseen_event_is_not_processed(conn: psycopg.Connection) -> None:
    assert is_processed(conn, CONSUMER, _event().envelope.event_id) is False


def test_mark_then_check(conn: psycopg.Connection) -> None:
    event_id = _event().envelope.event_id

    assert mark_processed(conn, CONSUMER, event_id) is True
    assert is_processed(conn, CONSUMER, event_id) is True


def test_marking_twice_is_not_an_error(conn: psycopg.Connection) -> None:
    """Two workers of one service can race past the check on a redelivery."""
    event_id = _event().envelope.event_id
    mark_processed(conn, CONSUMER, event_id)

    assert mark_processed(conn, CONSUMER, event_id) is False


def test_mark_is_scoped_to_one_consumer_service(conn: psycopg.Connection) -> None:
    """Every service sees every event; one having handled it says nothing about another."""
    event_id = _event().envelope.event_id
    mark_processed(conn, CONSUMER, event_id)

    assert is_processed(conn, OTHER_CONSUMER, event_id) is False


def test_process_once_runs_the_handler_and_marks(conn: psycopg.Connection) -> None:
    event = _event()
    calls: list[UUID] = []

    result = process_once(conn, CONSUMER, event, lambda e: calls.append(e.envelope.event_id))

    assert result is None  # the handler's own return value
    assert calls == [event.envelope.event_id]
    assert is_processed(conn, CONSUMER, event.envelope.event_id) is True


def test_replaying_the_same_event_is_skipped_and_logged(
    conn: psycopg.Connection, caplog: pytest.LogCaptureFixture
) -> None:
    """The task's Definition of Done, verbatim."""
    event = _event()
    calls: list[UUID] = []

    def handler(received: ReceivedEvent) -> str:
        calls.append(received.envelope.event_id)
        return "handled"

    assert process_once(conn, CONSUMER, event, handler) == "handled"

    with caplog.at_level(logging.INFO, logger="libs.event_bus.dedup"):
        assert process_once(conn, CONSUMER, event, handler) is None

    assert calls == [event.envelope.event_id], "handler ran twice on a replay"
    assert "SYS_DUPLICATE_EVENT" in caplog.text
    assert str(event.envelope.event_id) in caplog.text


def test_failed_handler_is_not_marked_processed(conn: psycopg.Connection) -> None:
    """Write-after-act: a crash mid-handler must leave the event replayable."""
    event = _event()

    def failing(_: ReceivedEvent) -> None:
        raise RuntimeError("handler blew up")

    with pytest.raises(RuntimeError):
        process_once(conn, CONSUMER, event, failing)

    assert is_processed(conn, CONSUMER, event.envelope.event_id) is False


def test_purge_deletes_only_rows_past_the_retention_window(conn: psycopg.Connection) -> None:
    purge_processed_events(conn)  # rolled back later; clears anything already stale
    fresh = _event().envelope.event_id
    stale = _event().envelope.event_id
    mark_processed(conn, CONSUMER, fresh)
    mark_processed(conn, CONSUMER, stale)
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE processed_events SET processed_at = now() - make_interval(days => %s) "
            "WHERE event_id = %s",
            (PROCESSED_EVENTS_RETENTION_DAYS + 1, stale),
        )

    deleted = purge_processed_events(conn)

    assert deleted == 1
    assert is_processed(conn, CONSUMER, stale) is False
    assert is_processed(conn, CONSUMER, fresh) is True
