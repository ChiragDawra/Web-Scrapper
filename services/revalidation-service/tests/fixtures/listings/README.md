# Recorded live reads

One file per listing, named `{listing_id}.json` — the only key a
`DEAL_REVALIDATION_REQUEST` carries (`EVENT_SCHEMAS.md` §3). Replayed by
`FixtureListingSource` while the live read path is undecided
(`INPUTS_NEEDED.md` item 1).

Shape:

```json
{ "current_price": 799900, "in_stock": true, "observed_at": "2026-01-01T12:00:00+00:00" }
```

- `current_price` — paise, integer, positive (`common.json#/$defs/paise`).
  `price` is accepted as an alias, since a recording taken straight off a
  marketplace response is likelier to use it.
- `in_stock` — boolean, required. Not inferred when absent: a recording with no
  stock signal is defective, and inferring `false` would answer `SOLD_OUT` for a
  listing nobody checked (`VALIDATION_RULES.md` §1 puts that inference in the
  *connector*, against a real response).
- `observed_at` — optional ISO-8601 with offset. Absent means "now", which is
  the honest answer for a replay.

The two files here are the reference cases the Sprint 5 tests assert against: an
unchanged listing inside the 2% tolerance, and one outside it. Both are
hand-cut, not captured — there is no live transport to capture from yet.
