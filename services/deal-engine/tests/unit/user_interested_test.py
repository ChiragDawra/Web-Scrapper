"""The `USER_INTERESTED` guards — Sprint 3 Task 3.6.

Every branch of `STATE_TRANSITIONS.md` §1's tap edge, against a fake repository:
the rules are about statuses and clocks, and neither needs a database to be
wrong. The Postgres-backed half — that the row really moves, and that two
concurrent taps do not both apply — is in the integration suite.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

import pytest
from src.handlers import event_handlers
from src.handlers.event_handlers import (
    USER_INTERESTED,
    HandledInterest,
    InterestRejection,
    handle_user_interested,
)
from src.repositories.deal_repo import Deal

from libs.canonical_models.scored_deal import ScoreBreakdown
from libs.enums import DealStatus, EventProducerService
from libs.event_bus.consumer import ReceivedEvent
from libs.event_bus.envelope import Envelope

BREAKDOWN = ScoreBreakdown(
    discount_score=31.25,
    brand_score=18.75,
    rating_score=14.06,
    velocity_score=25.0,
    weights_version="builtin-v1",
)


def deal(status: DealStatus = DealStatus.DEAL_SENT, *, expires_in: timedelta | None = None) -> Deal:
    now = datetime.now(UTC)
    return Deal(
        id=uuid4(),
        listing_id=uuid4(),
        status=status,
        score=Decimal("89.06"),
        score_breakdown=BREAKDOWN,
        detected_price=100000,
        reference_price=200000,
        discount_pct=Decimal("50.00"),
        notified_at=now,
        expires_at=now + (expires_in if expires_in is not None else timedelta(hours=6)),
        created_at=now,
        updated_at=now,
    )


class FakeDealRepository:
    """Records what was asked of it; `calls` is what the guards are asserted on."""

    def __init__(self, stored: Deal | None) -> None:
        self._deal = stored
        self.calls: list[tuple[str, Any, ...]] = []  # type: ignore[misc]

    def get_by_id(self, deal_id: UUID, *, for_update: bool = False) -> Deal | None:
        self.calls.append(("get_by_id", deal_id, for_update))
        if self._deal is None or self._deal.id != deal_id:
            return None
        return self._deal

    def update_status(self, deal_id: UUID, status: DealStatus) -> Deal | None:
        self.calls.append(("update_status", deal_id, status))
        if self._deal is None or self._deal.id != deal_id:
            return None
        self._deal = replace(self._deal, status=status)
        return self._deal


@pytest.fixture
def repo_factory(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Swap the repository the handler builds from its connection."""

    def install(stored: Deal | None) -> FakeDealRepository:
        repo = FakeDealRepository(stored)
        monkeypatch.setattr(event_handlers, "DealRepository", lambda conn: repo)
        return repo

    return install


def tap(deal_id: UUID) -> ReceivedEvent:
    """The Bot's event (`EVENT_SCHEMAS.md` §3)."""
    return ReceivedEvent(
        stream=USER_INTERESTED,
        entry_id="1-0",
        envelope=Envelope.new(
            event_type=USER_INTERESTED,
            producer_service=EventProducerService.TELEGRAM_BOT,
            payload={"deal_id": str(deal_id), "telegram_user_id": str(uuid4())},
        ),
    )


def handle(repo: FakeDealRepository, deal_id: UUID) -> HandledInterest:
    return handle_user_interested(None, None, tap(deal_id))  # type: ignore[arg-type]


def test_a_sent_deal_moves_to_interested(repo_factory: Any) -> None:
    sent = deal(DealStatus.DEAL_SENT)
    repo = repo_factory(sent)

    result = handle(repo, sent.id)

    assert result.applied is True
    assert result.status is DealStatus.INTERESTED
    assert result.rejection is None
    assert ("update_status", sent.id, DealStatus.INTERESTED) in repo.calls


def test_an_interest_event_on_an_expired_deal_is_rejected(repo_factory: Any) -> None:
    """Task 3.6's Definition of Done, in the status the sweeper already wrote."""
    expired = deal(DealStatus.EXPIRED)
    repo = repo_factory(expired)

    result = handle(repo, expired.id)

    assert result.applied is False
    assert result.rejection is InterestRejection.EXPIRED
    assert not any(call[0] == "update_status" for call in repo.calls)


def test_a_tap_after_expires_at_is_rejected_and_expires_the_deal(repo_factory: Any) -> None:
    """The same guard when nothing has swept the row yet: reject, and record why."""
    stale = deal(DealStatus.DEAL_SENT, expires_in=timedelta(seconds=-1))
    repo = repo_factory(stale)

    result = handle(repo, stale.id)

    assert result.applied is False
    assert result.rejection is InterestRejection.EXPIRED
    assert result.status is DealStatus.EXPIRED
    assert ("update_status", stale.id, DealStatus.EXPIRED) in repo.calls
    assert not any(call[1:] == (stale.id, DealStatus.INTERESTED) for call in repo.calls)


def test_a_deal_expiring_in_a_moment_is_still_tappable(repo_factory: Any) -> None:
    """The boundary is `expires_at`, not a margin before it."""
    live = deal(DealStatus.DEAL_SENT, expires_in=timedelta(seconds=5))
    repo = repo_factory(live)

    assert handle(repo, live.id).applied is True


def test_a_second_tap_is_a_no_op(repo_factory: Any) -> None:
    already = deal(DealStatus.INTERESTED)
    repo = repo_factory(already)

    result = handle(repo, already.id)

    assert result.applied is False
    assert result.rejection is InterestRejection.ALREADY_INTERESTED
    assert not any(call[0] == "update_status" for call in repo.calls)


@pytest.mark.parametrize(
    "status",
    [
        DealStatus.SCORED,
        DealStatus.NOTIFIED,
        DealStatus.WATCHING,
        DealStatus.REVALIDATING,
        DealStatus.CONFIRMED,
        DealStatus.PRICE_CHANGED,
        DealStatus.SOLD_OUT,
        DealStatus.ORDERED,
        DealStatus.IGNORED,
        DealStatus.PRICE_CHANGED_REJECTED,
        DealStatus.SOLD_OUT_REJECTED,
    ],
)
def test_only_deal_sent_is_a_legal_source(status: DealStatus, repo_factory: Any) -> None:
    """§1 draws exactly one arrow into `INTERESTED`, and it starts at `DEAL_SENT`."""
    wrong = deal(status)
    repo = repo_factory(wrong)

    result = handle(repo, wrong.id)

    assert result.applied is False
    assert result.rejection is InterestRejection.WRONG_STATUS
    assert not any(call[0] == "update_status" for call in repo.calls)


def test_an_unknown_deal_is_rejected_not_raised(repo_factory: Any) -> None:
    """A deal the Bot knows about and this database does not is not retryable."""
    repo = repo_factory(None)

    result = handle(repo, uuid4())

    assert result.applied is False
    assert result.rejection is InterestRejection.NO_SUCH_DEAL
    assert result.status is None


def test_the_deal_is_read_under_a_row_lock(repo_factory: Any) -> None:
    """Read-decide-write: without `FOR UPDATE` two taps both pass the guard."""
    sent = deal(DealStatus.DEAL_SENT)
    repo = repo_factory(sent)

    handle(repo, sent.id)

    assert repo.calls[0] == ("get_by_id", sent.id, True)


def test_no_event_is_published(repo_factory: Any) -> None:
    """The Bot emits `DEAL_REVALIDATION_REQUEST`; publishing here would double it."""

    class ExplodingPublisher:
        def publish(self, envelope: object) -> None:
            raise AssertionError("the interest edge publishes nothing")

    sent = deal(DealStatus.DEAL_SENT)
    repo_factory(sent)

    handle_user_interested(None, ExplodingPublisher(), tap(sent.id))  # type: ignore[arg-type]
