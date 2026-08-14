# deal-engine

Scores listings into deals. Consumes `LISTING_DISCOVERED` and `USER_INTERESTED`,
emits `DEAL_SCORED`.

- Contract: `ZIP_13_ENGINEERING_CONTRACTS/SERVICE_INTERFACES.md` §2
- Owns: `brands`, `marketplaces`, `products`, `listings`, `price_history`, `deals`
- Events: `ZIP_13_ENGINEERING_CONTRACTS/EVENT_SCHEMAS.md` §2, §3
- Scoring rules: `VALIDATION_RULES.md` §2; deal lifecycle: `STATE_TRANSITIONS.md` §1

## Layout

| Path | What |
|---|---|
| `src/repositories/` | One module per owned table. SQL as module constants, no commits. |
| `src/services/brand_resolver.py` | `resolve_brand()` — case-insensitive, creates `STANDARD` on miss. |
| `src/services/scorer.py` | `score()` — four weighted components, `None` below threshold. |
| `src/services/deal_writer.py` | One-open-deal-per-listing guard, under an advisory lock. |
| `src/handlers/event_handlers.py` | The two consumers. |
| `src/main.py` | Consumer loop; one event is one transaction and one dedup mark. |

## Running

Postgres and Redis from the root `docker-compose.yml`, with the schema applied:

```
docker compose up -d postgres redis
cd infra/postgres && alembic upgrade head
```

Then either `docker compose up deal-engine`, or locally from this directory
with the variables in `.env.example` set:

```
python -m src.main
```

## Tests

Per-service pytest session, from this directory:

```
cd services/deal-engine && pytest
```

`tests/unit` needs nothing running. `tests/integration` skips itself unless
Postgres is up with `alembic upgrade head` applied, and
`listing_discovered_test.py` additionally needs Redis — it uses logical DB 15
and flushes it, never DB 0.
