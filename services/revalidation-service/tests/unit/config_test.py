"""Startup configuration — Sprint 5 Task 5.4.

The container's whole contract with its environment. The clamp on
`REVALIDATION_TIMEOUT_SECONDS` is the assertion worth having: a deployment that
raises it would produce a service that looks configured and emits into a window
the Bot has already closed.
"""

from __future__ import annotations

import pytest
from src.config import CONSUMED_EVENT_TYPES, PRODUCER_SERVICE, Config
from src.main import HANDLERS

from libs.enums import EventProducerService
from libs.validation_rules import REVALIDATION_TIMEOUT_SECONDS

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
        "REVALIDATION_TIMEOUT_SECONDS",
        "REVALIDATION_FIXTURE_DIR",
    ):
        monkeypatch.delenv(key, raising=False)


def test_database_url_is_required() -> None:
    """Dedup is not optional (`EVENT_SCHEMAS.md` §1), so neither is the connection."""
    with pytest.raises(ValueError, match="DATABASE_URL is required"):
        Config.from_env()


def test_a_sqlalchemy_dsn_is_rewritten_for_libpq(monkeypatch: pytest.MonkeyPatch) -> None:
    """`.env.example` documents the `+psycopg` form, which `psycopg.connect` rejects."""
    monkeypatch.setenv("DATABASE_URL", DSN.replace("postgresql://", "postgresql+psycopg://"))

    assert Config.from_env().database_url == DSN


def test_redis_defaults_to_loopback(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", DSN)

    assert Config.from_env().redis_url == "redis://127.0.0.1:6379/0"


def test_the_timeout_budget_defaults_to_the_documented_thirty_seconds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", DSN)

    assert Config.from_env().timeout_budget_seconds == REVALIDATION_TIMEOUT_SECONDS


def test_a_longer_budget_is_clamped(monkeypatch: pytest.MonkeyPatch) -> None:
    """`STATE_TRANSITIONS.md` §1 fixes the Bot's timeout; this side cannot vote itself more."""
    monkeypatch.setenv("DATABASE_URL", DSN)
    monkeypatch.setenv("REVALIDATION_TIMEOUT_SECONDS", "300")

    assert Config.from_env().timeout_budget_seconds == REVALIDATION_TIMEOUT_SECONDS


def test_a_shorter_budget_is_honored(monkeypatch: pytest.MonkeyPatch) -> None:
    """Lower is legal: it only makes this side give up first."""
    monkeypatch.setenv("DATABASE_URL", DSN)
    monkeypatch.setenv("REVALIDATION_TIMEOUT_SECONDS", "5")

    assert Config.from_env().timeout_budget_seconds == 5


def test_the_consumer_name_is_unique_per_process(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", DSN)

    assert Config.from_env().consumer_name.startswith("revalidation-service-")


def test_the_fixture_dir_is_unset_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """Unset means the service's own recordings, which the image already carries."""
    monkeypatch.setenv("DATABASE_URL", DSN)

    assert Config.from_env().fixture_dir is None


def test_the_producer_service_is_the_documented_string() -> None:
    """The group name, the `processed_events` key and the DLQ stream suffix, all at once."""
    assert PRODUCER_SERVICE is EventProducerService.REVALIDATION_SERVICE
    assert str(PRODUCER_SERVICE) == "revalidation-service"


def test_every_consumed_event_type_has_a_handler() -> None:
    """An event type subscribed to without a handler is a wiring bug, not a data problem."""
    assert set(CONSUMED_EVENT_TYPES) == set(HANDLERS)


def test_the_handled_event_is_the_one_the_contract_names() -> None:
    """`SERVICE_INTERFACES.md` §3. `DEAL_SCORED` is read as well, for the reference price."""
    assert "DEAL_REVALIDATION_REQUEST" in CONSUMED_EVENT_TYPES
