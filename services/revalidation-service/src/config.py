"""Revalidation Service configuration — Sprint 5 Task 5.4.

Reads the keys the root `.env.example` reserves, plus `REVALIDATION_FIXTURE_DIR`,
which exists only while the live read path is the recorded-fixture stub
(`INPUTS_NEEDED.md` item 1) and goes away with it.

`DATABASE_URL` is required even though `SERVICE_INTERFACES.md` §3 says this
service "owns no tables (stateless)". The one table it touches is
`processed_events`, which `DATABASE_SCHEMA.md` §18 owns per-row by
`consumer_service` — dedup is a bus-wide obligation (`EVENT_SCHEMAS.md` §1: "an
event with an `event_id` already present for that consumer is skipped"), not a
table this service models. Stateless means it holds no deal or listing state of
its own, and it does not: everything it needs to answer one request is either in
the request, in the `DEAL_SCORED` projection it rebuilds from the stream on
boot, or read live from the marketplace.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from libs.enums import EventProducerService
from libs.validation_rules import REVALIDATION_TIMEOUT_SECONDS

__all__ = ["CONSUMED_EVENT_TYPES", "PRODUCER_SERVICE", "Config"]

# `EVENT_SCHEMAS.md` §1 `producer_service` on `DEAL_REVALIDATED`, and the
# consumer group name on every stream this service reads (`consumer.py`: the
# group *is* the service enum value, the same string written to
# `processed_events.consumer_service`).
PRODUCER_SERVICE: Final = EventProducerService.REVALIDATION_SERVICE

#: `DEAL_REVALIDATION_REQUEST` is the handled event (`SERVICE_INTERFACES.md` §3).
#: `DEAL_SCORED` is not: this service produces no side effect from it and the Bot
#: remains its consumer. It is read only to learn each deal's `detected_price`,
#: which the request payload does not carry and which §5's tolerance is measured
#: against — see `deal_reference.py` on why that is a stream read and not a
#: cross-service query into Deal-Engine-owned `deals` (ADR-009).
CONSUMED_EVENT_TYPES: Final[tuple[str, ...]] = ("DEAL_SCORED", "DEAL_REVALIDATION_REQUEST")


def _redis_url() -> str:
    url = os.environ.get("REDIS_URL")
    if url:
        return url
    host = os.environ.get("REDIS_HOST", "127.0.0.1")
    port = os.environ.get("REDIS_PORT", "6379")
    return f"redis://{host}:{port}/0"


#: The dialect prefix SQLAlchemy needs and libpq rejects. `.env.example`
#: documents `DATABASE_URL` in SQLAlchemy form (it is also Alembic's variable),
#: so one value serves both and stripping the prefix here is cheaper than making
#: a deployment carry two spellings of one URL.
_SQLALCHEMY_PREFIX: Final = "postgresql+psycopg://"
_LIBPQ_PREFIX: Final = "postgresql://"


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        raise ValueError("DATABASE_URL is required (processed_events dedup, EVENT_SCHEMAS.md §1)")
    if url.startswith(_SQLALCHEMY_PREFIX):
        return _LIBPQ_PREFIX + url[len(_SQLALCHEMY_PREFIX) :]
    return url


@dataclass(frozen=True, slots=True)
class Config:
    """Everything this service needs to start."""

    database_url: str
    redis_url: str
    consumer_name: str
    log_level: str
    timeout_budget_seconds: int
    fixture_dir: Path | None = None

    @classmethod
    def from_env(cls) -> Config:
        """Read configuration from the process environment, applying the compose defaults."""
        fixture_dir = os.environ.get("REVALIDATION_FIXTURE_DIR")
        return cls(
            database_url=_database_url(),
            redis_url=_redis_url(),
            # Identifies this worker within the consumer group so a reclaim can
            # tell pending entries apart. The container ID is the natural value
            # under compose; the pid fallback keeps two local runs distinct.
            consumer_name=os.environ.get("CONSUMER_NAME") or f"revalidation-service-{os.getpid()}",
            log_level=os.environ.get("LOG_LEVEL", "INFO"),
            # Overridable but not upward: `STATE_TRANSITIONS.md` §1 fixes the
            # Bot's timeout at 30s, and a service granting itself a longer budget
            # would emit into a window the Bot has already given up on. Lower is
            # legal (it only makes this side give up first); higher is clamped.
            timeout_budget_seconds=min(
                int(os.environ.get("REVALIDATION_TIMEOUT_SECONDS", REVALIDATION_TIMEOUT_SECONDS)),
                REVALIDATION_TIMEOUT_SECONDS,
            ),
            # Only meaningful while the live read is the recorded-fixture stub
            # (`INPUTS_NEEDED.md` item 1). Unset means the service's own default
            # directory.
            fixture_dir=Path(fixture_dir) if fixture_dir else None,
        )
