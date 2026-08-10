# event-store-consumer

Subscribes to every event-type stream, validates each envelope and payload, and
appends it to `events` — the sole write path into that table.

- Contract: `ZIP_13_ENGINEERING_CONTRACTS/SERVICE_INTERFACES.md` §9
- Owns: events (sole writer, ADR-010)
- Events: see `ZIP_13_ENGINEERING_CONTRACTS/EVENT_SCHEMAS.md`

## Run

Needs the compose stack up and the schema migrated:

```
docker compose up -d
(cd infra/postgres && alembic upgrade head)
PYTHONPATH=.:services/event-store-consumer python -m src.main
```

Configuration comes from the environment keys in the root `.env.example`
(`DATABASE_URL` or `POSTGRES_*`, `REDIS_URL` or `REDIS_HOST`/`REDIS_PORT`,
`LOG_LEVEL`), plus `CONSUMER_NAME` — which must be distinct per replica, since
Redis hands two consumers of the same name the same pending entries. It defaults
to the container hostname.

`EVENT_CONSUMER_SERVICE` is deliberately *not* read here: this deployable is
always `event-store-consumer`, and letting an environment variable say otherwise
would only allow a misconfiguration to split the consumer group in two.

## Test

The suite is per-service, not part of the root `pytest tests` run: every service
owns a top-level `src` package, so collecting several in one session would give
several modules named `src`.

```
cd services/event-store-consumer && pytest
```

Tests skip rather than fail when Postgres or Redis is unreachable, or when the
migration has not been applied.
