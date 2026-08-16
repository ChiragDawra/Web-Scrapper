# Revalidation Service image — Sprint 5 Task 5.4.
#
# Build context is the repo root, not this directory: the service imports libs/
# (canonical models, enums, event bus, error codes, validation rules), and a
# context rooted here could not reach it. Compose sets `context: .` with this
# file as `dockerfile`.
#
#   docker compose up revalidation-service

FROM python:3.12-slim

# 3.12 matches [tool.ruff] target-version and [tool.mypy] python_version.

# `src` is the service's top-level package and `libs` is the repo root's, so both
# roots are on the path — the same two entries this service's pyproject.toml
# gives pytest.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app:/app/services/revalidation-service

WORKDIR /app

# Dependencies before source: this layer is rebuilt only when the pins change,
# not on every edit to the service.
COPY services/revalidation-service/requirements.txt ./service-requirements.txt
RUN pip install --no-cache-dir --disable-pip-version-check -r service-requirements.txt

COPY libs/ ./libs/
COPY services/revalidation-service/src/ ./services/revalidation-service/src/
# Recorded live reads, while the read path is the fixture stub
# (INPUTS_NEEDED.md item 1). Copied rather than mounted so the image runs
# standalone; REVALIDATION_FIXTURE_DIR points elsewhere when a real recording set
# is mounted over it. Same layout the connector image uses, and the reason is the
# same: DEFAULT_FIXTURE_DIR resolves relative to the module, so the paths inside
# the image have to mirror the repo.
COPY services/revalidation-service/tests/fixtures/ ./services/revalidation-service/tests/fixtures/

# Unprivileged: this process talks to Postgres and Redis, reads recordings, and
# writes nothing to disk. In particular it does not run migrations —
# infra/postgres is applied by CI or an operator, not by whichever container
# happens to boot first.
RUN useradd --create-home --uid 10001 revalidation && chown -R revalidation:revalidation /app
USER revalidation

CMD ["python", "-m", "src.main"]
