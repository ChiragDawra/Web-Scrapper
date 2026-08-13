"""Marketplace Connector configuration — Sprint 2 Task 2.4.

`MARKETPLACE_CODE` gets the most attention here because it is the one setting
that changes what the deployable *is*: one connector per marketplace
(`SERVICE_INTERFACES.md` §1).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from src.config import PRODUCER_SERVICE, Config

from libs.enums import EventProducerService, MarketplaceCode

CONNECTOR_ENV = (
    "MARKETPLACE_CODE",
    "MARKETPLACE_POLL_INTERVAL_SECONDS",
    "MARKETPLACE_FIXTURE_DIR",
    "REDIS_URL",
    "REDIS_HOST",
    "REDIS_PORT",
    "LOG_LEVEL",
)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Start from an empty environment — a developer's own `.env` must not decide a result."""
    for name in CONNECTOR_ENV:
        monkeypatch.delenv(name, raising=False)


def test_the_producer_service_is_fixed() -> None:
    """`EVENT_SCHEMAS.md` §1 `producer_service`. Not configurable — this deployable is it."""
    assert PRODUCER_SERVICE is EventProducerService.MARKETPLACE_CONNECTOR


def test_marketplace_code_is_required() -> None:
    """No default: a connector silently falling back to Amazon would publish Amazon
    listings from a container named for another marketplace."""
    with pytest.raises(ValueError, match="MARKETPLACE_CODE is required"):
        Config.from_env()


def test_an_unknown_marketplace_code_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MARKETPLACE_CODE", "EBAY")

    with pytest.raises(ValueError, match="not a marketplace_code"):
        Config.from_env()


def test_marketplace_code_is_read_case_insensitively(monkeypatch: pytest.MonkeyPatch) -> None:
    """`ENUMS.md` spells it uppercase; a lowercase value in a `.env` is a typo, not a
    different marketplace."""
    monkeypatch.setenv("MARKETPLACE_CODE", "amazon")

    assert Config.from_env().marketplace is MarketplaceCode.AMAZON


def test_the_compose_defaults_apply(monkeypatch: pytest.MonkeyPatch) -> None:
    """`.env.example` values, so an unset environment matches a running stack."""
    monkeypatch.setenv("MARKETPLACE_CODE", "AMAZON")
    config = Config.from_env()

    assert config.redis_url == "redis://127.0.0.1:6379/0"
    assert config.poll_interval_seconds == 300
    assert config.log_level == "INFO"
    assert config.fixture_dir is None


def test_redis_url_wins_over_the_host_and_port_parts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MARKETPLACE_CODE", "AMAZON")
    monkeypatch.setenv("REDIS_HOST", "ignored")
    monkeypatch.setenv("REDIS_URL", "redis://redis:6379/3")

    assert Config.from_env().redis_url == "redis://redis:6379/3"


def test_the_host_and_port_parts_build_a_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MARKETPLACE_CODE", "AMAZON")
    monkeypatch.setenv("REDIS_HOST", "redis")
    monkeypatch.setenv("REDIS_PORT", "6380")

    assert Config.from_env().redis_url == "redis://redis:6380/0"


def test_the_fixture_directory_is_read_as_a_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """Task 2.6 mounts a directory and points this at it; unset means the connector's own."""
    monkeypatch.setenv("MARKETPLACE_CODE", "AMAZON")
    monkeypatch.setenv("MARKETPLACE_FIXTURE_DIR", "/srv/fixtures/amazon")

    assert Config.from_env().fixture_dir == Path("/srv/fixtures/amazon")


def test_the_poll_interval_is_read_as_an_integer(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MARKETPLACE_CODE", "AMAZON")
    monkeypatch.setenv("MARKETPLACE_POLL_INTERVAL_SECONDS", "60")

    assert Config.from_env().poll_interval_seconds == 60
