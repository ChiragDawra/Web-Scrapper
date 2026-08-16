# revalidation-service

Live price/stock re-check at confirmation time. Sprint 5.

- Contract: `ZIP_13_ENGINEERING_CONTRACTS/SERVICE_INTERFACES.md` §3
- Owns: no tables. The one table it touches is `processed_events`, owned per-row
  by `consumer_service` (`DATABASE_SCHEMA.md` §18) — dedup, not state.
- Handles: `DEAL_REVALIDATION_REQUEST`. Also reads `DEAL_SCORED`, for the reason
  below.
- Emits: `DEAL_REVALIDATED` (`EVENT_SCHEMAS.md` §3), carrying a
  `RevalidationResult` flat.

## The verdict

`changed` is `abs(current_price - detected_price) / detected_price > 0.02`, or a
stock flip (`VALIDATION_RULES.md` §5, `STATE_TRANSITIONS.md` §1). The 2% lives in
`libs/validation_rules/revalidation.py` and nowhere else — §5 names itself the
single source of truth for it.

## Why it reads DEAL_SCORED

The tolerance is measured against `detected_price`, and
`DEAL_REVALIDATION_REQUEST` carries only `deal_id`, `listing_id` and
`correlation_id`. The scored price lives in `deals`, which belongs to the Deal
Engine, and ADR-009 forbids reading another service's tables. So it comes off the
bus: `DEAL_SCORED` carries `detected_price`, and `DealReferenceStore` keeps an
in-memory projection of it. `EventConsumer` creates its group at id `0`, so a
restart replays the retained stream and the projection warms itself before the
first request. A request for a deal it has never seen is refused, never guessed.

## The 30s budget

§3: "Must respond within 30s or the Bot times out and treats it as changed
(`REVAL_TIMEOUT`) — the service should not bother emitting late." The budget
starts at delivery and is checked three times: before the live read, after it, and
immediately before the publish. Past the deadline, nothing is emitted at all — the
Bot's own fail-safe moves the deal to `PRICE_CHANGED`, and a late event would ask
it to re-decide a transition it has already taken, spending the one
`PRICE_CHANGED -> REVALIDATING` round-trip §1 allows per deal.

## Running

```
cd services/revalidation-service && pytest
docker compose up revalidation-service
```

The live read path is a recorded-fixture stub (`INPUTS_NEEDED.md` item 1);
recordings and their shape are documented in `tests/fixtures/listings/README.md`.
