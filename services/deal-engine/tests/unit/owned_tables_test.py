"""No repository touches a table outside the six — Sprint 3 Task 3.1.

This is the task's Definition of Done stated as a test rather than as a
comment: "no method touches a table outside the six". It reads the SQL out of
each repository module and fails on any table name that is not one of them, so
a later task that reaches into `orders` or `telegram_users` from here breaks
the build instead of quietly crossing a service boundary.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

OWNED_TABLES = frozenset(
    {"brands", "marketplaces", "products", "listings", "price_history", "deals"}
)

REPOSITORY_DIR = Path(__file__).resolve().parents[2] / "src" / "repositories"

# Every place a table name can appear in the SQL these modules write. Nothing
# here builds SQL dynamically, so matching the source text is matching the
# statements that actually run.
TABLE_REFERENCE = re.compile(
    r"\b(?:FROM|JOIN|INTO|UPDATE|DELETE\s+FROM)\s+([a-z_][a-z0-9_.]*)",
    re.IGNORECASE,
)

REPOSITORY_MODULES = sorted(
    path for path in REPOSITORY_DIR.glob("*_repo.py") if path.name != "__init__.py"
)


def sql_text(module_path: Path) -> str:
    """Every SQL string a module defines, concatenated.

    Parsed rather than grepped: a docstring sentence like "arriving from a
    marketplace listing" matches a naive `FROM <table>` search and would fail
    the check for a table named `a`. Only module-level constant assignments are
    considered, which is where all of this service's SQL lives — nothing here
    builds a statement at runtime.
    """
    module = ast.parse(module_path.read_text(encoding="utf-8"))
    parts: list[str] = []

    for node in module.body:
        if not isinstance(node, ast.Assign | ast.AnnAssign) or node.value is None:
            continue
        for literal in ast.walk(node.value):
            if isinstance(literal, ast.Constant) and isinstance(literal.value, str):
                parts.append(literal.value)

    return "\n".join(parts)


def test_every_owned_table_has_a_repository() -> None:
    """Six tables, six modules — a missing one would make this suite pass vacuously."""
    module_stems = {path.stem.removesuffix("_repo") for path in REPOSITORY_MODULES}

    assert module_stems == {"brand", "marketplace", "product", "listing", "price_history", "deal"}


@pytest.mark.parametrize("module_path", REPOSITORY_MODULES, ids=lambda p: p.name)
def test_repository_references_only_owned_tables(module_path: Path) -> None:
    referenced = {
        match.group(1).lower() for match in TABLE_REFERENCE.finditer(sql_text(module_path))
    }

    assert referenced <= OWNED_TABLES, (
        f"{module_path.name} references tables outside the Deal Engine's six: "
        f"{sorted(referenced - OWNED_TABLES)}"
    )


# Word-bounded so prose in a docstring ("inserting the row here would hide it")
# is not mistaken for a statement.
WRITE_STATEMENTS = {
    "INSERT": re.compile(r"\bINSERT\s+INTO\b", re.IGNORECASE),
    "UPDATE": re.compile(r"\bUPDATE\s+[a-z_]+\s+SET\b", re.IGNORECASE),
    "DELETE": re.compile(r"\bDELETE\s+FROM\b", re.IGNORECASE),
}


def test_marketplace_repository_never_writes() -> None:
    """`DATABASE_SCHEMA.md` §2: seed row per code, no dynamic inserts at runtime."""
    sql = sql_text(REPOSITORY_DIR / "marketplace_repo.py")

    for name, pattern in WRITE_STATEMENTS.items():
        assert pattern.search(sql) is None, f"marketplace_repo.py writes: {name}"


def test_price_history_repository_never_updates() -> None:
    """`DATABASE_SCHEMA.md` §5: rows are never updated, only inserted."""
    sql = sql_text(REPOSITORY_DIR / "price_history_repo.py")

    for name in ("UPDATE", "DELETE"):
        assert WRITE_STATEMENTS[name].search(sql) is None, f"price_history_repo.py: {name}"
