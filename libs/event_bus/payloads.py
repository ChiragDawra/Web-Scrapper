"""Per-event-type payload schemas and their validator.

Implements `ZIP_13_ENGINEERING_CONTRACTS/EVENT_SCHEMAS.md` §2-§7 — Sprint 1 Task 1.3.

Task 1.3's "Files Involved" column names only `libs/event_bus/schema/*.json`.
Those files are the contract; this module is the loader that makes them
enforceable — the schemas are useless without something that resolves their
`$ref`s and maps an `event_type` to the right file. It lives beside
`envelope.py` rather than inside it because §1 (envelope) and §2-§7 (payloads)
are two separate validation steps, and `envelope.py` says so in its docstring.

Two files under `schema/` are not event types: `common.json` (shared primitives,
transcribed from `ENUMS.md`) and `canonical_models.json` (`CANONICAL_MODELS.md`).
They exist so a repeated shape — `CanonicalProduct`, `PurchaseOutcome`,
`marketplace_code` — is written once and `$ref`'d, rather than copied into
several event schemas where the copies can drift apart.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from functools import cache, lru_cache
from types import MappingProxyType
from typing import Any, Final

from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource

from libs.event_bus.envelope import (
    SCHEMA_DIR,
    EventSchemaInvalidError,
    format_schema_errors,
    validate_envelope,
)

__all__ = [
    "EVENT_PAYLOAD_SCHEMA_FILES",
    "load_schema",
    "payload_validator",
    "validate_event",
    "validate_payload",
]

# `event_type` -> schema filename, one entry per event type in EVENT_SCHEMAS.md
# §2-§7. Adding a key here without a corresponding section in that document is an
# architecture change, not a convenience (IMPLEMENTATION_ROADMAP.md §5).
EVENT_PAYLOAD_SCHEMA_FILES: Final[Mapping[str, str]] = MappingProxyType(
    {
        # §2 Ingestion & scoring
        "LISTING_DISCOVERED": "listing_discovered.json",
        "DEAL_SCORED": "deal_scored.json",
        # §3 Deal interaction
        "USER_INTERESTED": "user_interested.json",
        "DEAL_REVALIDATION_REQUEST": "deal_revalidation_request.json",
        "DEAL_REVALIDATED": "deal_revalidated.json",
        # §4 Order planning & allocation
        "PURCHASE_REQUESTED": "purchase_requested.json",
        "ACCOUNT_ALLOCATION_REQUEST": "account_allocation_request.json",
        "ACCOUNT_ALLOCATION_RESPONSE": "account_allocation_response.json",
        "PURCHASE_TASK_CREATED": "purchase_task_created.json",
        # §5 Purchase execution outcomes
        "PURCHASE_COMPLETED": "purchase_completed.json",
        "PURCHASE_FAILED": "purchase_failed.json",
        # §6 Account health
        "ACCOUNT_HEALTH_CHANGED": "account_health_changed.json",
        # §7 Dead-lettering
        "EVENT_DEAD_LETTERED": "event_dead_lettered.json",
    }
)

# The only payload version any schema here describes. A consumer receiving a
# known `event_type` at a version it doesn't handle must reject and dead-letter
# rather than best-effort parse (VALIDATION_RULES.md §5).
SUPPORTED_VERSION: Final = 1


@cache
def load_schema(filename: str) -> dict[str, Any]:
    """Return a parsed schema file from `schema/`. Cached — files never change at runtime."""
    with (SCHEMA_DIR / filename).open(encoding="utf-8") as fh:
        schema: dict[str, Any] = json.load(fh)
    return schema


@lru_cache(maxsize=1)
def _registry() -> Registry:
    """Registry of every schema under `schema/`, keyed by filename, so `$ref`s resolve locally.

    Each schema's `$id` is its bare filename — no invented hostname, and nothing
    is ever fetched over the network during validation.
    """
    resources = [
        (path.name, Resource.from_contents(load_schema(path.name)))
        for path in sorted(SCHEMA_DIR.glob("*.json"))
    ]
    return Registry().with_resources(resources)


@cache
def payload_validator(event_type: str) -> Draft202012Validator:
    """Return the validator for one event type. Raises `EventSchemaInvalidError` if unknown."""
    try:
        filename = EVENT_PAYLOAD_SCHEMA_FILES[event_type]
    except KeyError:
        raise EventSchemaInvalidError(f"event_type: unknown event type {event_type!r}") from None
    return Draft202012Validator(
        load_schema(filename),
        registry=_registry(),
        format_checker=FormatChecker(),
    )


def validate_payload(event_type: str, payload: Mapping[str, Any]) -> None:
    """Validate one payload against its event type's schema.

    Raises `EventSchemaInvalidError` (`SYS_EVENT_SCHEMA_INVALID`) for an unknown
    event type as well as a malformed payload — an event type with no schema
    cannot be published or stored, so it is rejected, never waved through.
    """
    reason = format_schema_errors(payload_validator(event_type).iter_errors(payload))
    if reason:
        raise EventSchemaInvalidError(f"payload/{event_type}: {reason}")


def validate_event(data: Mapping[str, Any]) -> None:
    """Validate a full wire event: envelope (§1) first, then its payload (§2-§7).

    Envelope first, deliberately — `event_type` and `version` cannot be trusted
    to select a payload schema until the envelope itself is known well-formed.
    """
    validate_envelope(data)

    version = data["version"]
    if version != SUPPORTED_VERSION:
        raise EventSchemaInvalidError(
            f"version: {data['event_type']} v{version} is not a version this build handles "
            f"(v{SUPPORTED_VERSION})"
        )

    validate_payload(data["event_type"], data["payload"])
