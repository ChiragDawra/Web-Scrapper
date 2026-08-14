"""Startup configuration — Sprint 3 Task 3.7.

The container's whole contract with its environment. Worth testing because
every failure here is a failure at boot, and the DSN rewrite in particular is
invisible until libpq rejects a URL the rest of the repo considers correct.
"""

from __future__ import annotations

import pytest
from src.config import CONSUMED_EVENT_TYPES, PRODUCER_SERVICE, Config
from src.main import HANDLERS

from libs.enums import EventProducerService

DSN = "postgresql://businessscrapper:businessscrapper@127.0.0.1:5432/businessscrapper"


@pytest.fixture(autouse=True)
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for key in (
        "DATABASE_URL",
        "REDIS_URL",
        "REDIS_HOST",
        "REDIS_PORT",
        "CONSUMER_NAME",
        "LOG_LEVEL",
        "SCORING_CONFIG_URL",
    ):
        monkeypatch.delenv(key, raising=False)


def test_database_url_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    """No default: an engine pointed at the wrong database writes deals nobody reads."""
    with pytest.raises(ValueError, match="DATABASE_URL is required"):
        Config.from_env()


def test_a_sqlalchemy_dsn_is_rewritten_for_libpq(monkeypatch: pytest.MonkeyPatch) -> None:
    """`.env.example` documents the `+psycopg` form, which `psycopg.connect` rejects."""
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://user:pw@db:5432/app")

    assert Config.from_env().database_url == "postgresql://user:pw@db:5432/app"


def test_a_plain_dsn_is_left_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", DSN)

    assert Config.from_env().database_url == DSN


def test_redis_host_and_port_compose_a_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", DSN)
    monkeypatch.setenv("REDIS_HOST", "redis")
    monkeypatch.setenv("REDIS_PORT", "6380")

    assert Config.from_env().redis_url == "redis://redis:6380/0"


def test_redis_url_wins_over_the_parts(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", DSN)
    monkeypatch.setenv("REDIS_HOST", "ignored")
    monkeypatch.setenv("REDIS_URL", "redis://redis:6379/2")

    assert Config.from_env().redis_url == "redis://redis:6379/2"


def test_scoring_config_url_is_absent_until_the_gateway_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Compose passes an empty string when the variable is unset; that is not a URL."""
    monkeypatch.setenv("DATABASE_URL", DSN)
    monkeypatch.setenv("SCORING_CONFIG_URL", "")

    assert Config.from_env().scoring_config_url is None


def test_every_consumed_event_type_has_a_handler() -> None:
    """`SERVICE_INTERFACES.md` §2 "Handles" — both, as of Task 3.6."""
    assert set(CONSUMED_EVENT_TYPES) == set(HANDLERS)


def test_the_producer_service_is_the_deal_engine() -> None:
    """Also the consumer group name and the `processed_events` key."""
    assert PRODUCER_SERVICE is EventProducerService.DEAL_ENGINE
    assert str(PRODUCER_SERVICE) == "deal-engine"
