"""Deal Engine configuration — Sprint 3 Task 3.5.

Reads the keys the root `.env.example` reserves. Unlike the connector this
service owns tables, so `DATABASE_URL` is required and has no local default
worth guessing at: a Deal Engine pointed at the wrong database writes deals
nobody reads.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Final

from libs.enums import EventProducerService

__all__ = ["CONSUMED_EVENT_TYPES", "PRODUCER_SERVICE", "Config"]

# `EVENT_SCHEMAS.md` §1 `producer_service` for `DEAL_SCORED`, and the consumer
# group name on every stream this service reads (`consumer.py`: the group *is*
# the service enum value, and the same string keys `processed_events`).
PRODUCER_SERVICE: Final = EventProducerService.DEAL_ENGINE

#: `SERVICE_INTERFACES.md` §2 "Handles". Both groups are created at startup
#: rather than on first delivery, so a tap arriving before the first listing
#: still finds a group to be read by.
CONSUMED_EVENT_TYPES: Final[tuple[str, ...]] = ("LISTING_DISCOVERED", "USER_INTERESTED")


def _redis_url() -> str:
    url = os.environ.get("REDIS_URL")
    if url:
        return url
    host = os.environ.get("REDIS_HOST", "127.0.0.1")
    port = os.environ.get("REDIS_PORT", "6379")
    return f"redis://{host}:{port}/0"


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        raise ValueError("DATABASE_URL is required")
    return url


@dataclass(frozen=True, slots=True)
class Config:
    """Everything this service needs to start."""

    database_url: str
    redis_url: str
    consumer_name: str
    log_level: str
    scoring_config_url: str | None = None

    @classmethod
    def from_env(cls) -> Config:
        """Read configuration from the process environment, applying the compose defaults."""
        return cls(
            database_url=_database_url(),
            redis_url=_redis_url(),
            # Identifies this worker within the consumer group, so a reclaim can
            # tell whose pending entries it is taking over. The container ID is
            # the natural value under compose; a hostname fallback keeps a local
            # run distinguishable from a second local run.
            consumer_name=os.environ.get("CONSUMER_NAME") or f"deal-engine-{os.getpid()}",
            log_level=os.environ.get("LOG_LEVEL", "INFO"),
            # Absent until the API Gateway exists (Sprint 13 Task 13.7); the
            # scorer falls back to its built-in weights and says so in every
            # `weights_version` it writes.
            scoring_config_url=os.environ.get("SCORING_CONFIG_URL") or None,
        )
