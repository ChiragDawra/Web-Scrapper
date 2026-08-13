# marketplace-connector

Reads marketplace listings, normalizes them to `CanonicalProduct`, publishes one
`LISTING_DISCOVERED` per valid listing. One deployable per marketplace.

- Contract: `ZIP_13_ENGINEERING_CONTRACTS/SERVICE_INTERFACES.md` §1
- Owns: no tables — publishes to the bus and touches no database
- Publishes: `LISTING_DISCOVERED` (`EVENT_SCHEMAS.md` §2), consumed by `deal-engine`

## Layout

| Path | What |
|---|---|
| `src/base/connector_interface.py` | `ConnectorInterface` ABC, the `CONN_*` error hierarchy, `iter_products()` (log-and-skip) |
| `src/base/normalizer.py` | Shared `VALIDATION_RULES.md` §1 validator, used by every connector |
| `src/connectors/amazon/selectors.py` | Where each field lives in a raw response — the part that rots |
| `src/connectors/amazon/connector.py` | What those fields mean: rupees to paise, `SavingBasis` to `mrp`, absent stock signal to `false` |
| `src/config.py` | Environment, including the required `MARKETPLACE_CODE` |
| `src/main.py` | Poll loop: fetch, normalize, publish |

## Running

```sh
docker compose up marketplace-connector-amazon
```

`MARKETPLACE_CODE` has no default — a connector that quietly fell back to Amazon
would publish Amazon listings from a container named for another marketplace.
See the root `.env.example` for the rest.

The fetch path is a stub over recorded fixtures in `tests/fixtures/amazon/`
while the live listing source is undecided (`INPUTS_NEEDED.md` item 1). Only
`selectors.py` and `AmazonConnector.fetch_raw()` change when it is.

## Tests

Per-service pytest session — every service owns a top-level `src` package, so
one combined run would see eleven modules named `src`:

```sh
cd services/marketplace-connector && pytest
```

`tests/integration/` needs Redis (`docker compose up redis`) and skips itself
without one.
