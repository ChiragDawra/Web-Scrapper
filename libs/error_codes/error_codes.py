"""Canonical error code registry.

Implements `ZIP_13_ENGINEERING_CONTRACTS/ERROR_CODES.md` — Sprint 1 deliverable.

`ERROR_CODES.md` states every error carries exactly four things: `code`,
`message` (human-readable, safe to show a user or log), `severity` (the
`error_severity` enum) and `retryable` (bool). `ErrorCode` below holds those
four and nothing else — error paths must emit only codes defined here, with the
documented severity and retryable values, never ad hoc strings
(`IMPLEMENTATION_ROADMAP.md` §5).

The document's Retryable column carries operational nuance that a bool cannot
hold — "yes, with backoff", "yes, up to 3 attempts", "no (needs credential
refresh)", "n/a". `retryable` records only whether a retry is permitted; the
nuance is preserved in a comment beside each entry, because inventing a fifth
field would contradict the contract. `n/a` entries are `False`: retrying an
`ACCT_COOLDOWN_ACTIVE` or a validation rejection is meaningless, not merely
discouraged.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Final

from libs.enums import ErrorSeverity

__all__ = ["ERROR_CODES", "ErrorCode", "get_error_code"]


@dataclass(frozen=True, slots=True)
class ErrorCode:
    """One row of `ERROR_CODES.md`. Immutable — this is a frozen registry."""

    code: str
    message: str
    severity: ErrorSeverity
    retryable: bool


def _e(code: str, message: str, severity: ErrorSeverity, retryable: bool) -> ErrorCode:
    return ErrorCode(code=code, message=message, severity=severity, retryable=retryable)


# --- Connector / ingestion (CONN_*) -----------------------------------------
CONN_RATE_LIMITED: Final = _e(
    "CONN_RATE_LIMITED",
    "Marketplace returned 429 or equivalent",
    ErrorSeverity.WARNING,
    True,
)
CONN_AUTH_FAILED: Final = _e(
    "CONN_AUTH_FAILED",
    "Marketplace session/API auth rejected",
    ErrorSeverity.ERROR,
    False,  # needs credential refresh
)
CONN_PARSE_FAILED: Final = _e(
    "CONN_PARSE_FAILED",
    "Response shape didn't match expected structure",
    ErrorSeverity.ERROR,
    False,  # needs code fix
)
CONN_LISTING_NOT_FOUND: Final = _e(
    "CONN_LISTING_NOT_FOUND",
    "Listing removed or delisted",
    ErrorSeverity.INFO,
    False,
)
CONN_TIMEOUT: Final = _e(
    "CONN_TIMEOUT",
    "Upstream request exceeded timeout",
    ErrorSeverity.WARNING,
    True,
)
CONN_CAPTCHA: Final = _e(
    "CONN_CAPTCHA",
    "CAPTCHA challenge encountered",
    ErrorSeverity.WARNING,
    True,  # with backoff
)

# --- Revalidation (REVAL_*) --------------------------------------------------
REVAL_TIMEOUT: Final = _e(
    "REVAL_TIMEOUT",
    "No DEAL_REVALIDATED within 30s",
    ErrorSeverity.WARNING,
    True,  # once
)
REVAL_PRICE_CHANGED: Final = _e(
    "REVAL_PRICE_CHANGED",
    "Price delta exceeded 2% tolerance",
    ErrorSeverity.INFO,
    False,
)
REVAL_SOLD_OUT: Final = _e(
    "REVAL_SOLD_OUT",
    "Listing out of stock at revalidation",
    ErrorSeverity.INFO,
    False,
)

# --- Order planning (PLAN_*) -------------------------------------------------
PLAN_NO_ACCOUNTS: Final = _e(
    "PLAN_NO_ACCOUNTS",
    "Zero eligible accounts for the marketplace",
    ErrorSeverity.ERROR,
    False,
)
PLAN_INSUFFICIENT_CAPACITY: Final = _e(
    "PLAN_INSUFFICIENT_CAPACITY",
    "Eligible accounts exist but total capacity < requested quantity",
    ErrorSeverity.WARNING,
    False,  # proceeds as PARTIAL
)
PLAN_ALLOCATION_TIMEOUT: Final = _e(
    "PLAN_ALLOCATION_TIMEOUT",
    "ACCOUNT_ALLOCATION_RESPONSE not received within 10s",
    ErrorSeverity.ERROR,
    True,  # 3 attempts then dead-letter
)

# --- Purchase execution (PURCH_*) --------------------------------------------
PURCH_PRICE_MISMATCH: Final = _e(
    "PURCH_PRICE_MISMATCH",
    "Checkout-time price differs from planned price beyond tolerance",
    ErrorSeverity.ERROR,
    False,
)
PURCH_OUT_OF_STOCK: Final = _e(
    "PURCH_OUT_OF_STOCK",
    "Item unavailable at checkout step",
    ErrorSeverity.ERROR,
    False,
)
PURCH_CHECKOUT_FAILED: Final = _e(
    "PURCH_CHECKOUT_FAILED",
    "Generic checkout automation failure (selector not found, page error)",
    ErrorSeverity.ERROR,
    True,  # up to 3 attempts
)
PURCH_PAYMENT_FAILED: Final = _e(
    "PURCH_PAYMENT_FAILED",
    "Payment step rejected",
    ErrorSeverity.ERROR,
    False,
)
PURCH_ACCOUNT_BLOCKED: Final = _e(
    "PURCH_ACCOUNT_BLOCKED",
    "Account banned/suspended mid-task",
    ErrorSeverity.CRITICAL,
    False,  # task dead-lettered
)
PURCH_TIMEOUT: Final = _e(
    "PURCH_TIMEOUT",
    "Automation exceeded step timeout",
    ErrorSeverity.WARNING,
    True,  # up to 3 attempts
)

# --- Account Service (ACCT_*) ------------------------------------------------
ACCT_COOLDOWN_ACTIVE: Final = _e(
    "ACCT_COOLDOWN_ACTIVE",
    "Account requested while in cooldown",
    ErrorSeverity.INFO,
    False,  # n/a
)
ACCT_DAILY_CAP_EXCEEDED: Final = _e(
    "ACCT_DAILY_CAP_EXCEEDED",
    "Allocation would exceed daily_spend_cap",
    ErrorSeverity.INFO,
    False,  # n/a
)
ACCT_SESSION_EXPIRED: Final = _e(
    "ACCT_SESSION_EXPIRED",
    "Stored session invalid, re-login required",
    ErrorSeverity.WARNING,
    True,
)

# --- Bot / API validation (VALID_*) ------------------------------------------
VALID_QUANTITY_INVALID: Final = _e(
    "VALID_QUANTITY_INVALID",
    "Quantity not a positive integer within allowed range",
    ErrorSeverity.INFO,
    False,  # n/a
)
VALID_QUANTITY_EXCEEDS_STOCK: Final = _e(
    "VALID_QUANTITY_EXCEEDS_STOCK",
    "Requested quantity exceeds known stock signal",
    ErrorSeverity.INFO,
    False,  # n/a
)
VALID_DEAL_EXPIRED: Final = _e(
    "VALID_DEAL_EXPIRED",
    "Action taken on an expired deal",
    ErrorSeverity.INFO,
    False,  # n/a
)
VALID_DUPLICATE_ACTION: Final = _e(
    "VALID_DUPLICATE_ACTION",
    "Conversation state already past this step (double-tap)",
    ErrorSeverity.INFO,
    False,  # n/a
)

# --- System (SYS_*) ----------------------------------------------------------
SYS_EVENT_SCHEMA_INVALID: Final = _e(
    "SYS_EVENT_SCHEMA_INVALID",
    "Payload failed JSON Schema validation on publish",
    ErrorSeverity.CRITICAL,
    False,  # publish rejected
)
SYS_DUPLICATE_EVENT: Final = _e(
    "SYS_DUPLICATE_EVENT",
    "event_id already in processed_events for this consumer",
    ErrorSeverity.INFO,
    False,  # n/a, skip processing
)
SYS_DEAD_LETTERED: Final = _e(
    "SYS_DEAD_LETTERED",
    "Message exceeded retry budget, moved to DLQ stream",
    ErrorSeverity.CRITICAL,
    False,  # needs manual replay
)


ERROR_CODES: Final[MappingProxyType[str, ErrorCode]] = MappingProxyType(
    {
        entry.code: entry
        for entry in (
            CONN_RATE_LIMITED,
            CONN_AUTH_FAILED,
            CONN_PARSE_FAILED,
            CONN_LISTING_NOT_FOUND,
            CONN_TIMEOUT,
            CONN_CAPTCHA,
            REVAL_TIMEOUT,
            REVAL_PRICE_CHANGED,
            REVAL_SOLD_OUT,
            PLAN_NO_ACCOUNTS,
            PLAN_INSUFFICIENT_CAPACITY,
            PLAN_ALLOCATION_TIMEOUT,
            PURCH_PRICE_MISMATCH,
            PURCH_OUT_OF_STOCK,
            PURCH_CHECKOUT_FAILED,
            PURCH_PAYMENT_FAILED,
            PURCH_ACCOUNT_BLOCKED,
            PURCH_TIMEOUT,
            ACCT_COOLDOWN_ACTIVE,
            ACCT_DAILY_CAP_EXCEEDED,
            ACCT_SESSION_EXPIRED,
            VALID_QUANTITY_INVALID,
            VALID_QUANTITY_EXCEEDS_STOCK,
            VALID_DEAL_EXPIRED,
            VALID_DUPLICATE_ACTION,
            SYS_EVENT_SCHEMA_INVALID,
            SYS_DUPLICATE_EVENT,
            SYS_DEAD_LETTERED,
        )
    }
)


def get_error_code(code: str) -> ErrorCode:
    """Look up a code, raising if it is not in `ERROR_CODES.md`.

    Deliberately strict: a `KeyError` at the call site is the intended outcome
    for an ad hoc string, since the contract admits no codes beyond the registry.
    """
    return ERROR_CODES[code]
