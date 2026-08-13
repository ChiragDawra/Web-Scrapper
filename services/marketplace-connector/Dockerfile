# Marketplace Connector image — Sprint 2 Task 2.6.
#
# Build context is the repo root, not this directory: the service imports libs/
# (canonical models, enums, event bus, error codes), and a context rooted here
# could not reach it. Compose sets `context: .` with this file as `dockerfile`.
#
# Layout inside the image mirrors the repo, so `DEFAULT_FIXTURE_DIR` in the
# connector — resolved relative to its own module path — points at the same
# fixtures it does locally, and a traceback line number matches the source.
#
#   docker compose up marketplace-connector-amazon

FROM python:3.12-slim

# 3.12 matches [tool.ruff] target-version and [tool.mypy] python_version.

# `src` is the service's top-level package and `libs` is the repo root's, so both
# roots are on the path — the same two entries this service's pyproject.toml
# gives pytest.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app:/app/services/marketplace-connector

WORKDIR /app

# Dependencies before source: this layer is rebuilt only when the pins change,
# not on every edit to the connector.
COPY services/marketplace-connector/requirements.txt ./service-requirements.txt
RUN pip install --no-cache-dir --disable-pip-version-check -r service-requirements.txt

COPY libs/ ./libs/
COPY services/marketplace-connector/src/ ./services/marketplace-connector/src/
# The recorded fixtures the fetch stub reads while the live listing source is
# undecided (INPUTS_NEEDED.md item 1). They leave the image with the stub.
COPY services/marketplace-connector/tests/fixtures/ ./services/marketplace-connector/tests/fixtures/

# Unprivileged: this process makes outbound connections only and writes nothing
# to disk, so it has no reason to be able to.
RUN useradd --create-home --uid 10001 connector && chown -R connector:connector /app
USER connector

# One deployable per marketplace (SERVICE_INTERFACES.md §1). No default for
# MARKETPLACE_CODE — compose sets it per service, and src/config.py refuses to
# start without it rather than guessing.
CMD ["python", "-m", "src.main"]
