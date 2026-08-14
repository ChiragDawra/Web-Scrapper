# Deal Engine image — Sprint 3 Task 3.7.
#
# Build context is the repo root, not this directory: the service imports libs/
# (canonical models, enums, event bus, error codes), and a context rooted here
# could not reach it. Compose sets `context: .` with this file as `dockerfile`.
#
#   docker compose up deal-engine

FROM python:3.12-slim

# 3.12 matches [tool.ruff] target-version and [tool.mypy] python_version.

# `src` is the service's top-level package and `libs` is the repo root's, so both
# roots are on the path — the same two entries this service's pyproject.toml
# gives pytest.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app:/app/services/deal-engine

WORKDIR /app

# Dependencies before source: this layer is rebuilt only when the pins change,
# not on every edit to the engine.
COPY services/deal-engine/requirements.txt ./service-requirements.txt
RUN pip install --no-cache-dir --disable-pip-version-check -r service-requirements.txt

COPY libs/ ./libs/
COPY services/deal-engine/src/ ./services/deal-engine/src/

# Unprivileged: this process talks to Postgres and Redis and writes nothing to
# disk, so it has no reason to be able to. In particular it does not run
# migrations — infra/postgres is applied by CI or an operator, not by whichever
# container happens to boot first.
RUN useradd --create-home --uid 10001 dealengine && chown -R dealengine:dealengine /app
USER dealengine

CMD ["python", "-m", "src.main"]
