"""Assert `libs.error_codes` is 1:1 with `ZIP_13_ENGINEERING_CONTRACTS/ERROR_CODES.md`.

Like the enum test, the contract's tables are parsed rather than restated, so
the assertions cannot drift alongside the code they check.

`ERROR_CODES.md` records the Retryable column in prose ("yes, with backoff",
"no (needs credential refresh)", "n/a"), while the contract's own preamble
declares `retryable` a bool. The mapping asserted here is: leading "yes" is
True, everything else — including "n/a" — is False.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from libs.enums import ErrorSeverity
from libs.error_codes import ERROR_CODES, get_error_code

CONTRACT = Path(__file__).resolve().parents[2] / "ZIP_13_ENGINEERING_CONTRACTS" / "ERROR_CODES.md"

ROW = re.compile(
    r"^\|\s*`([A-Z][A-Z0-9_]*)`\s*\|\s*(.+?)\s*\|\s*(INFO|WARNING|ERROR|CRITICAL)\s*\|\s*(.+?)\s*\|$",
    re.MULTILINE,
)


def _documented() -> dict[str, tuple[str, str, str]]:
    """{code: (message, severity, retryable_prose)} from the contract's tables."""
    text = CONTRACT.read_text(encoding="utf-8")
    return {m[1]: (m[2], m[3], m[4]) for m in ROW.finditer(text)}


def test_contract_parsed_at_all() -> None:
    """Guard against a regex that silently matches nothing."""
    assert len(_documented()) >= 25


def test_no_missing_and_no_invented_codes() -> None:
    documented = set(_documented())
    implemented = set(ERROR_CODES)

    assert not (documented - implemented), (
        f"codes in ERROR_CODES.md with no counterpart: {sorted(documented - implemented)}"
    )
    assert not (implemented - documented), (
        f"codes defined with no counterpart in ERROR_CODES.md: "
        f"{sorted(implemented - documented)} — error paths may emit only "
        "documented codes (IMPLEMENTATION_ROADMAP.md §5)"
    )


@pytest.mark.parametrize("code", sorted(_documented()))
def test_severity_and_retryable_match_the_contract(code: str) -> None:
    message, severity, retryable_prose = _documented()[code]
    entry = ERROR_CODES[code]

    assert entry.severity == ErrorSeverity(severity), (
        f"{code} severity is {entry.severity}, contract says {severity}"
    )

    expected_retryable = retryable_prose.lower().startswith("yes")
    assert entry.retryable is expected_retryable, (
        f"{code} retryable is {entry.retryable}, contract says {retryable_prose!r}"
    )

    # The message is the contract's Meaning column, minus its backticks — the
    # column is written as prose, and ERROR_CODES.md requires the message be
    # safe to show a user or log.
    assert entry.message == message.replace("`", "")


def test_registry_is_immutable() -> None:
    with pytest.raises(TypeError):
        ERROR_CODES["SYS_DUPLICATE_EVENT"] = ERROR_CODES["SYS_DEAD_LETTERED"]  # type: ignore[index]


def test_lookup_rejects_an_ad_hoc_string() -> None:
    with pytest.raises(KeyError):
        get_error_code("SYS_MADE_UP_CODE")


def test_the_two_codes_sprint_1_depends_on_exist() -> None:
    """Tasks 1.2 and 1.5 name these in their Definitions of Done."""
    assert get_error_code("SYS_EVENT_SCHEMA_INVALID").severity is ErrorSeverity.CRITICAL
    assert get_error_code("SYS_DUPLICATE_EVENT").severity is ErrorSeverity.INFO
