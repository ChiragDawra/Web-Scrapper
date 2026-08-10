"""Assert `libs.enums` is 1:1 with `ZIP_13_ENGINEERING_CONTRACTS/ENUMS.md`.

Covers Sprint 1 Task 1.1's Definition of Done: "Every enum value in `ENUMS.md`
has exactly one code counterpart, no extras."

The contract is parsed at test time rather than restated here. A test that
hardcodes the expected values would pass just as happily when `ENUMS.md` and the
code drift apart in the same direction — it would only prove the test author and
the implementer agreed, which is the thing already in doubt.
"""

from __future__ import annotations

import re
from enum import StrEnum
from pathlib import Path

import pytest

from libs import enums

CONTRACT = Path(__file__).resolve().parents[2] / "ZIP_13_ENGINEERING_CONTRACTS" / "ENUMS.md"

# Enum names in ENUMS.md are snake_case headings; the classes are PascalCase.
HEADING_TO_CLASS = {
    "marketplace_code": enums.MarketplaceCode,
    "deal_status": enums.DealStatus,
    "order_status": enums.OrderStatus,
    "order_item_status": enums.OrderItemStatus,
    "purchase_task_status": enums.PurchaseTaskStatus,
    "account_status": enums.AccountStatus,
    "account_health_band": enums.AccountHealthBand,
    "conversation_state": enums.ConversationState,
    "user_interest_action": enums.UserInterestAction,
    "inventory_item_status": enums.InventoryItemStatus,
    "event_producer_service": enums.EventProducerService,
    "currency_code": enums.CurrencyCode,
    "error_severity": enums.ErrorSeverity,
    "brand_tier": enums.BrandTier,
}


def _sections() -> dict[str, str]:
    """Split ENUMS.md into {heading: body} for every `## ` heading."""
    text = CONTRACT.read_text(encoding="utf-8")
    parts = re.split(r"^## ", text, flags=re.MULTILINE)[1:]
    sections: dict[str, str] = {}
    for part in parts:
        head, _, body = part.partition("\n")
        # "brand_tier (scoring input, `ZIP_05/DEAL_SCORING.md`)" -> "brand_tier"
        sections[head.split(" ")[0].strip()] = body
    return sections


def _documented_values(body: str) -> set[str]:
    """Every `backticked` token in a section that looks like an enum value.

    Excludes cross-references to other documents (`STATE_TRANSITIONS.md`) and
    prose, keeping ALL_CAPS tokens plus the lowercase-hyphenated service names.

    Parenthetical asides are stripped first, because they annotate values rather
    than declare them: "`ZERO` (score 0, forces `BANNED`)" documents one member
    of account_health_band and cross-references one of account_status. Every
    section still declares its full membership outside parentheses — deal_status
    in particular restates all fourteen on its "Full set" line, so nothing is
    lost by discarding its arrow diagram's bracketed branches.
    """
    body = re.sub(r"\([^)]*\)", " ", body)
    tokens = set(re.findall(r"`([^`]+)`", body))
    return {
        t
        for t in tokens
        if not t.endswith(".md")
        and re.fullmatch(r"[A-Z][A-Z0-9_]*|[a-z][a-z0-9-]*", t)
        and "/" not in t
    }


def test_every_documented_enum_has_a_class() -> None:
    documented = set(_sections())
    assert documented == set(HEADING_TO_CLASS), (
        "ENUMS.md headings and mapped classes disagree — a new enum was added to "
        "the contract, or one was mapped that no longer exists"
    )


@pytest.mark.parametrize("heading", sorted(HEADING_TO_CLASS))
def test_enum_values_match_contract_exactly(heading: str) -> None:
    """No missing values, and — just as important — no invented extras."""
    enum_cls: type[StrEnum] = HEADING_TO_CLASS[heading]
    documented = _documented_values(_sections()[heading])
    implemented = {member.value for member in enum_cls}

    assert not (documented - implemented), (
        f"{enum_cls.__name__} is missing values documented in ENUMS.md "
        f"§{heading}: {sorted(documented - implemented)}"
    )
    assert not (implemented - documented), (
        f"{enum_cls.__name__} defines values absent from ENUMS.md "
        f"§{heading}: {sorted(implemented - documented)} — a perceived gap is "
        "logged, never silently patched (IMPLEMENTATION_ROADMAP.md §5)"
    )


def test_members_are_str_enums_so_the_value_is_the_wire_format() -> None:
    """ENUMS.md: each enum is a string literal set on the wire and in Postgres."""
    for enum_cls in HEADING_TO_CLASS.values():
        assert issubclass(enum_cls, StrEnum), f"{enum_cls.__name__} is not a StrEnum"
        for member in enum_cls:
            assert member == member.value


def test_deal_status_includes_the_two_rejected_terminals() -> None:
    """The arrow diagram omits these; the "Full set" and "Terminal" lines do not.

    Guards the one place in ENUMS.md where two statements of the same enum
    disagree in completeness, so a future reader cannot "tidy" the enum by
    trusting the diagram.
    """
    assert enums.DealStatus.PRICE_CHANGED_REJECTED in enums.DealStatus
    assert enums.DealStatus.SOLD_OUT_REJECTED in enums.DealStatus
