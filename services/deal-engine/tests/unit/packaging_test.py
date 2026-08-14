"""Image and compose wiring — Sprint 3 Task 3.7.

Text assertions, deliberately: the failures they catch are the ones a green
test suite hides until a container starts. A pin that drifts from the root
requirements.txt, or a service whose source never gets copied into its image,
is invisible to every other test here.

Nothing in this module builds or runs anything, so it costs a few milliseconds
and needs no Docker daemon.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Final

import pytest

SERVICE_DIR: Final = Path(__file__).resolve().parents[2]
REPO_ROOT: Final = SERVICE_DIR.parents[1]

DOCKERFILE: Final = (SERVICE_DIR / "Dockerfile").read_text(encoding="utf-8")
REQUIREMENTS: Final = (SERVICE_DIR / "requirements.txt").read_text(encoding="utf-8")
COMPOSE: Final = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
ROOT_REQUIREMENTS: Final = (REPO_ROOT / "requirements.txt").read_text(encoding="utf-8")

PIN = re.compile(r"^(?P<name>[A-Za-z0-9._-]+(?:\[[a-z,]+\])?)==(?P<version>[\w.]+)$", re.MULTILINE)


def pins(text: str) -> dict[str, str]:
    return {match["name"]: match["version"] for match in PIN.finditer(text)}


def test_every_pin_matches_the_root_file() -> None:
    """A service resolving a different redis than the libs it imports is the bug."""
    root = pins(ROOT_REQUIREMENTS)

    for name, version in pins(REQUIREMENTS).items():
        assert name in root, f"{name} is pinned here but not at the repo root"
        assert version == root[name], f"{name}: {version} here, {root[name]} at the root"


def test_the_driver_is_present() -> None:
    """Unlike a connector, this service owns tables (`SERVICE_INTERFACES.md` §2)."""
    assert any(name.startswith("psycopg") for name in pins(REQUIREMENTS))


@pytest.mark.parametrize("package", ["SQLAlchemy", "alembic"])
def test_migration_tooling_is_not_shipped(package: str) -> None:
    """Migrations are an operator step, not a race between app containers."""
    assert package not in pins(REQUIREMENTS)


def test_the_image_carries_both_import_roots() -> None:
    """`src` is this service's top-level package; `libs` is the repo root's."""
    assert "PYTHONPATH=/app:/app/services/deal-engine" in DOCKERFILE


@pytest.mark.parametrize(
    "path",
    ["COPY libs/ ./libs/", "COPY services/deal-engine/src/ ./services/deal-engine/src/"],
)
def test_the_image_copies_what_it_imports(path: str) -> None:
    assert path in DOCKERFILE


def test_the_container_does_not_run_as_root() -> None:
    assert "USER dealengine" in DOCKERFILE


def test_compose_defines_the_service() -> None:
    assert "\n  deal-engine:" in COMPOSE
    assert "dockerfile: services/deal-engine/Dockerfile" in COMPOSE
    # Repo root, because the image copies libs/.
    assert "context: ." in COMPOSE


@pytest.mark.parametrize("dependency", ["postgres", "redis"])
def test_compose_waits_for_its_backing_services(dependency: str) -> None:
    """`service_healthy`, not `service_started`: it writes on the first event it reads."""
    service = COMPOSE.split("\n  deal-engine:", 1)[1]
    depends = service.split("depends_on:", 1)[1]

    assert f"{dependency}:" in depends
    assert depends.count("condition: service_healthy") == 2


def test_compose_points_at_the_container_hostnames() -> None:
    """The loopback port mappings are for host tooling, not for containers."""
    service = COMPOSE.split("\n  deal-engine:", 1)[1].split("\nvolumes:", 1)[0]
    settings = [line for line in service.splitlines() if not line.lstrip().startswith("#")]

    assert "@postgres:5432/" in service
    assert "REDIS_URL: redis://redis:6379/0" in service
    assert not any("127.0.0.1" in line for line in settings)
