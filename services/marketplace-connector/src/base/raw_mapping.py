"""Raw-item plumbing shared by the Sprint 4 connectors — Flipkart, Myntra, Nykaa.

Sprint 4's note is "the framework validator (Sprint 2 Tasks 2.1-2.2) is not
repeated", and the same argument reaches one level further down: three
connectors written back to back would otherwise carry three copies of "rupees
to paise", "a trimmed string or `None`", "walk this path and stop at the first
missing key". Three copies drift, and a drifting paise conversion is a wrong
number in `deals.detected_price` with no trace.

What lives here is only the part that is *not* marketplace lore: the shape of a
lookup and the meaning of a converted value. Where a field sits stays in each
marketplace's `selectors.py`, and which field wins when two are present stays in
its `connector.py`. This module never decides either.

Every failure raised here is `ParseFailedError` (`CONN_PARSE_FAILED`), the one
per-item code `SERVICE_INTERFACES.md` §1 allows: "On `CONN_PARSE_FAILED`, logs
and skips the item; does not emit a partial/malformed `LISTING_DISCOVERED`."
The poll loop (Task 2.5) therefore has a single behaviour to handle no matter
which marketplace produced the item, and nothing here returns a half-built
value that could reach the bus.

Amazon (Sprint 2 Task 2.3) keeps its own private copies of these helpers. They
are behaviourally identical, and folding that connector onto this module is a
refactor of shipped, reviewed code — worth doing, but as its own change with
its own review, not as a side effect of adding three marketplaces.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Final

from libs.enums import CurrencyCode
from src.base.connector_interface import ParseFailedError

__all__ = [
    "PAISE_PER_RUPEE",
    "Path",
    "currency",
    "first_paise",
    "first_text",
    "flag",
    "identifier",
    "only_present",
    "optional_int",
    "optional_number",
    "optional_paise",
    "paise",
    "require",
    "required_paise",
    "required_text",
    "select",
    "text",
]

#: Every marketplace in scope quotes money in major units (rupees); every money
#: field in the system is minor units — `DATABASE_SCHEMA.md`: "All money is
#: integer minor units (paise)".
PAISE_PER_RUPEE: Final = Decimal(100)

#: A lookup into a raw item: mapping keys and list indices, in order.
Path = tuple[str | int, ...]


def select(raw: Any, path: Path) -> Any:
    """Walk `path` through `raw`, returning `None` the moment it stops resolving.

    Total by design. The caller is asking "is this field present and what is
    it", and a `KeyError` escaping mid-parse would abort an item that a later
    `validate()` call is entitled to judge for itself. A missing key and an
    explicit `null` both resolve to `None`: no rule in `VALIDATION_RULES.md` §1
    treats the two differently.
    """
    current: Any = raw
    for key in path:
        if isinstance(key, int):
            if not isinstance(current, Sequence) or isinstance(current, str | bytes):
                return None
            if not -len(current) <= key < len(current):
                return None
            current = current[key]
        else:
            if not isinstance(current, Mapping):
                return None
            current = current.get(key)
        if current is None:
            return None
    return current


def require(raw: Mapping[str, Any], path: Path, field: str) -> Any:
    """The value at `path`, or `CONN_PARSE_FAILED` naming the field and the path."""
    value = select(raw, path)
    if value is None:
        raise ParseFailedError(f"{field}: missing at {'.'.join(str(key) for key in path)}")
    return value


def text(raw: Mapping[str, Any], path: Path) -> str | None:
    """A trimmed string, or `None` when absent, blank or not a string.

    Blank collapses to `None` deliberately: for the optional fields this serves,
    an empty `brand_name` and a missing one mean the same thing downstream, and
    `resolveBrand("")` would otherwise create a nameless `brands` row.

    A number is not coerced to its digits. A marketplace that returns `1499` for
    a colour is returning something this connector does not understand, and
    `"1499"` in `attributes.color` is worse than an absent key.
    """
    value = select(raw, path)
    if not isinstance(value, str):
        return None
    return value.strip() or None


def first_text(raw: Mapping[str, Any], paths: Iterable[Path]) -> str | None:
    """The first path that yields a usable string, or `None` if none do.

    Fallback chains are ordinary here — a brand under one key on the search
    response and another on the detail response is the norm, not a defect — and
    each connector spells its own preference order out in the call.
    """
    for path in paths:
        value = text(raw, path)
        if value is not None:
            return value
    return None


def identifier(raw: Mapping[str, Any], paths: Iterable[Path], field: str) -> str:
    """A listing id as a string, from the first path that carries one.

    Two of the Sprint 4 sources quote the id as a JSON *number*. The id is a
    string everywhere downstream, and `str(1466678)` is the same listing key on
    every poll, so the number is converted rather than the item dropped.

    `bool` is excluded explicitly — it is an `int` subclass, and `"True"` is not
    a listing id. A float is rejected too: `1466678.0` and `1466678` would key
    the same listing two ways in `listings`, and a fractional id is a defect at
    the source rather than something to round here.
    """
    paths = tuple(paths)
    for path in paths:
        value = select(raw, path)
        if value is None:
            continue
        if isinstance(value, str):
            if value.strip():
                return value.strip()
            continue
        if isinstance(value, bool) or not isinstance(value, int):
            raise ParseFailedError(f"{field}: {value!r} is neither a string nor an integer id")
        return str(value)

    tried = " or ".join(".".join(str(key) for key in path) for path in paths)
    raise ParseFailedError(f"{field}: missing at {tried}")


def required_text(raw: Mapping[str, Any], path: Path, field: str) -> str:
    value = require(raw, path, field)
    if not isinstance(value, str):
        raise ParseFailedError(f"{field}: is a {type(value).__name__}, expected a string")
    return value


def paise(amount: Any, field: str) -> int:
    """Rupees as recorded -> paise as stored.

    Via `Decimal(str(...))`, never float: `1499.35 * 100` is `149934.99999...`
    in binary floating point, and `int()` of that is a rupee-and-a-bit short on
    every listing. Half-up rounding covers sub-paise precision, which is a bug
    at the source rather than a reason to drop an otherwise good listing.

    Strings are accepted because two of the three Sprint 4 sources quote money
    as `"1,499"` or `"1499.00"`; the grouping separator is stripped rather than
    parsed, since `Decimal("1,499")` is an `InvalidOperation` and dropping a
    valid listing over a comma helps nobody.
    """
    if isinstance(amount, bool) or not isinstance(amount, int | float | str | Decimal):
        raise ParseFailedError(f"{field}: {amount!r} is not a number")
    if isinstance(amount, str):
        amount = amount.replace(",", "").strip().removeprefix("₹").strip()
    try:
        rupees = Decimal(str(amount))
    except InvalidOperation as error:
        raise ParseFailedError(f"{field}: {amount!r} is not a number") from error
    if not rupees.is_finite():
        raise ParseFailedError(f"{field}: {amount!r} is not finite")

    return int((rupees * PAISE_PER_RUPEE).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def optional_paise(raw: Mapping[str, Any], path: Path, field: str) -> int | None:
    value = select(raw, path)
    return None if value is None else paise(value, field)


def first_paise(raw: Mapping[str, Any], paths: Iterable[Path], field: str) -> int | None:
    """Paise from the first path that carries an amount, or `None` if none do.

    Every marketplace here quotes more than one money field per listing, and
    which one wins is a marketplace decision each `connector.py` makes by the
    order it passes. This only walks that order.
    """
    for path in paths:
        amount = select(raw, path)
        if amount is not None:
            return paise(amount, field)
    return None


def required_paise(raw: Mapping[str, Any], paths: Iterable[Path], field: str) -> int:
    """`first_paise`, but a listing with no amount at any path is unusable."""
    paths = tuple(paths)
    amount = first_paise(raw, paths, field)
    if amount is None:
        tried = " or ".join(".".join(str(key) for key in path) for path in paths)
        raise ParseFailedError(f"{field}: missing at {tried}")
    return amount


def optional_number(raw: Mapping[str, Any], path: Path, field: str) -> float | None:
    """Absent stays absent. §1 permits a null `rating`; it does not permit a made-up one."""
    value = select(raw, path)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ParseFailedError(f"{field}: {value!r} is not a number")
    return float(value)


def optional_int(raw: Mapping[str, Any], path: Path, field: str) -> int | None:
    value = select(raw, path)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ParseFailedError(f"{field}: {value!r} is not an integer")
    return value


def currency(raw: Mapping[str, Any], path: Path) -> CurrencyCode:
    """The recorded currency, or `INR` when the listing omits it (the model's default).

    An unmapped code raises rather than falling back: `CurrencyCode` has one
    member on purpose, and quietly relabelling a USD price as rupees would put a
    wrong number into `deals.detected_price` with no trace.
    """
    code = text(raw, path)
    if code is None:
        return CurrencyCode.INR
    try:
        return CurrencyCode(code.upper())
    except ValueError as error:
        raise ParseFailedError(f"currency: {code!r} is not a supported currency_code") from error


def flag(raw: Mapping[str, Any], path: Path) -> bool | None:
    """A real boolean at `path`, or `None` — never a truthiness verdict.

    §1 rule 9 wants a *positive* stock signal, so "the key is present but holds
    a string" has to be distinguishable from "the key says true". Returning
    `bool(value)` here would turn `"false"` into in-stock, which sends a
    purchase agent at an unbuyable listing.
    """
    value = select(raw, path)
    return value if isinstance(value, bool) else None


def only_present(candidates: Mapping[str, Any]) -> dict[str, Any]:
    """Drop the `None`s from an `attributes` draft.

    `attributes` is an open map, but a `{"size": None}` entry reads as "this
    listing has a null size" to anything iterating it, where an absent key reads
    as "unknown" — which is the truth.
    """
    return {key: value for key, value in candidates.items() if value is not None}
