"""Marketplace Connector configuration — Sprint 2 Task 2.4.

Reads the keys `.env.example` reserves. `MARKETPLACE_FIXTURE_DIR` is the one
addition, documented there alongside the rest: it exists only while `fetch_raw()`
is the recorded-fixture stub and goes away with it.

One deployable per marketplace (`SERVICE_INTERFACES.md` §1), so `MARKETPLACE_CODE`
selects which connector this process runs and there is no default: a connector
that quietly falls back to Amazon when the variable is missing would publish
Amazon listings from a container named for Flipkart.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from libs.enums import EventProducerService, MarketplaceCode

__all__ = ["PRODUCER_SERVICE", "Config"]

# `EVENT_SCHEMAS.md` §1 `producer_service` for everything this deployable emits.
# Fixed, not configurable — the deployable *is* the marketplace-connector; only
# which marketplace it reads varies.
PRODUCER_SERVICE: Final = EventProducerService.MARKETPLACE_CONNECTOR


def _redis_url() -> str:
    url = os.environ.get("REDIS_URL")
    if url:
        return url
    host = os.environ.get("REDIS_HOST", "127.0.0.1")
    port = os.environ.get("REDIS_PORT", "6379")
    return f"redis://{host}:{port}/0"


def _marketplace() -> MarketplaceCode:
    raw = os.environ.get("MARKETPLACE_CODE", "").strip()
    if not raw:
        raise ValueError("MARKETPLACE_CODE is required: one of " + _marketplace_choices())
    try:
        return MarketplaceCode(raw.upper())
    except ValueError:
        raise ValueError(
            f"MARKETPLACE_CODE {raw!r} is not a marketplace_code: {_marketplace_choices()}"
        ) from None


def _marketplace_choices() -> str:
    return " | ".join(str(code) for code in MarketplaceCode)


@dataclass(frozen=True, slots=True)
class Config:
    """Everything this service needs to start."""

    redis_url: str
    marketplace: MarketplaceCode
    poll_interval_seconds: int
    log_level: str
    fixture_dir: Path | None = None

    @classmethod
    def from_env(cls) -> Config:
        """Read configuration from the process environment, applying the compose defaults."""
        fixture_dir = os.environ.get("MARKETPLACE_FIXTURE_DIR")
        return cls(
            redis_url=_redis_url(),
            marketplace=_marketplace(),
            poll_interval_seconds=int(os.environ.get("MARKETPLACE_POLL_INTERVAL_SECONDS", "300")),
            log_level=os.environ.get("LOG_LEVEL", "INFO"),
            # Only meaningful while `fetch_raw()` is the recorded-fixture stub
            # (`INPUTS_NEEDED.md` item 1). Unset means the connector's own
            # default directory; Task 2.6 mounts one and points this at it.
            fixture_dir=Path(fixture_dir) if fixture_dir else None,
        )
