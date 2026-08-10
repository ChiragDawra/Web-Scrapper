"""Event Store Consumer configuration — Sprint 1 Task 1.8.

Reads the keys `.env.example` already reserves; nothing here invents a new
environment variable.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Final

from libs.enums import EventProducerService

__all__ = ["CONSUMER_SERVICE", "Config"]

# SERVICE_INTERFACES.md §9. Fixed, not configurable: this deployable *is* the
# event-store-consumer, and the value is written into the Redis consumer-group
# name, so making it an env var would only let a misconfiguration split the
# group in two.
CONSUMER_SERVICE: Final = EventProducerService.EVENT_STORE_CONSUMER


def _database_url() -> str:
    """Build the psycopg connection string from `DATABASE_URL` or the `POSTGRES_*` parts.

    `.env.example` documents `DATABASE_URL` in SQLAlchemy's
    `postgresql+psycopg://` form, which libpq does not accept — psycopg is given
    the bare `postgresql://` scheme, and the driver suffix is stripped rather
    than requiring two spellings of one URL in the environment.
    """
    url = os.environ.get("DATABASE_URL")
    if url:
        return url.replace("postgresql+psycopg://", "postgresql://", 1)
    user = os.environ.get("POSTGRES_USER", "businessscrapper")
    password = os.environ.get("POSTGRES_PASSWORD", "businessscrapper")
    host = os.environ.get("POSTGRES_HOST", "127.0.0.1")
    port = os.environ.get("POSTGRES_PORT", "5432")
    database = os.environ.get("POSTGRES_DB", "businessscrapper")
    return f"postgresql://{user}:{password}@{host}:{port}/{database}"


def _redis_url() -> str:
    url = os.environ.get("REDIS_URL")
    if url:
        return url
    host = os.environ.get("REDIS_HOST", "127.0.0.1")
    port = os.environ.get("REDIS_PORT", "6379")
    return f"redis://{host}:{port}/0"


@dataclass(frozen=True, slots=True)
class Config:
    """Everything this service needs to start."""

    database_url: str
    redis_url: str
    consumer_name: str
    log_level: str
    block_ms: int
    batch_size: int

    @classmethod
    def from_env(cls) -> Config:
        """Read configuration from the process environment, applying the compose defaults."""
        return cls(
            database_url=_database_url(),
            redis_url=_redis_url(),
            # One consumer group, many workers: each replica needs a distinct
            # name or Redis hands them the same pending entries. Defaults to the
            # container hostname, which is per-replica in both Compose and
            # Kubernetes.
            consumer_name=os.environ.get("CONSUMER_NAME") or os.uname().nodename,
            log_level=os.environ.get("LOG_LEVEL", "INFO"),
            block_ms=int(os.environ.get("EVENT_BUS_BLOCK_MS", "5000")),
            batch_size=int(os.environ.get("EVENT_BUS_BATCH_SIZE", "10")),
        )
