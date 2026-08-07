# Deal Scoring

Hybrid approach: rule-based weights now, ML ranking later
(`ZIP_09/DEAL_SCORING_MODEL.md`, `ZIP_09/ML_ROADMAP.md`).

Scoring produces the `DEAL_SCORED` event and moves a deal from `DETECTED` to
`SCORED` (`ZIP_02/STATE_DIAGRAMS.md`).

---

## Score Range

**0-100.**

---

## Official Weights

| Component | Weight |
|---|---|
| Discount | 30 |
| Historical Lowest Price | 20 |
| Brand Popularity | 15 |
| Seller Trust | 15 |
| Ratings | 10 |
| Review Count | 5 |
| Confidence | 5 |
| **Total** | **100** |

Each component contributes at most its weight. The sum of all components at
maximum equals 100, which is what makes the score range 0-100.

> **Deprecated.** The previous formula
> `score = discount + history + seller + popularity + confidence` is no
> longer valid. It had five terms and no weights. Ratings and Review Count
> were added; every term now carries an explicit weight.

---

## Component Inputs

Each component draws on data already defined elsewhere in the repository.

| Component | Input source |
|---|---|
| Discount | Current listing price against MRP (`ZIP_06/MESSAGE_TEMPLATES.md`) |
| Historical Lowest Price | `lowest_price` from price snapshots (`PRICE_HISTORY_DESIGN.md`, `HISTORICAL_PRICE_ANALYSIS.md`) |
| Brand Popularity | Brand entity (`ZIP_03/ER_DIAGRAM.md`) |
| Seller Trust | Seller thresholds already used by the rule engine (`RULE_ENGINE.md`) |
| Ratings | Listing ratings (`ZIP_09/FEATURE_ENGINEERING.md`) |
| Review Count | Listing review count (`ZIP_09/FEATURE_ENGINEERING.md`) |
| Confidence | See `NOTIFICATION_ENGINE.md` and section below |

---

## Confidence

Confidence is both a scoring component (weight 5) and the notification gate.
It is normalized **0-100** independently of the deal score.

Phase 1 confidence is computed from:

- Data Quality
- Historical Stability
- Seller Reliability

Only deals with **Confidence >= 70** may be sent to users
(`NOTIFICATION_ENGINE.md`).

Note that confidence therefore does two jobs: it contributes 5 points to the
deal score, and it independently gates notification.

---

## Persistence

`SCORED` is a persisted state, not a transient step. Every scored deal is
stored, including deals that never reach the notification threshold.
Historical scores are required for analytics and for future ML training
(`ZIP_09/DATASET_DESIGN.md`).

Deals scored below the threshold are negative training examples.

---

## Future

ML models may replace these weights (`ZIP_09/DEAL_SCORING_MODEL.md`). The
transition is Phase 3 of `ZIP_09/ML_ROADMAP.md`. Until then the weights above
are authoritative.

---

## Open Points

1. **No normalization rule per component (Q7a).** Each component has a
   weight but no stated function mapping raw input to `0..weight`. A 40%
   discount and a 60% discount both need to land somewhere in `0..30`, and
   nothing says how.
2. **Confidence sub-weights (Q8a).** Data Quality, Historical Stability and
   Seller Reliability are named but not weighted against each other, and
   none has a defined input.
3. **Where weights live (Q43).** Whether the weight table is code constants,
   database configuration, or the same configurable store as the rule engine
   is unspecified. `RULE_ENGINE.md` calls its own rules "configurable"
   without naming a format either.
4. **Rescoring (Q34).** Whether a deal at `SCORED` or `NOTIFIED` is rescored
   when its price changes is unspecified.
5. **Ratings and Review Count availability (Q44).** Both are now scoring
   inputs, so every connector must supply them. `ZIP_04/CONNECTOR_INTERFACE.md`
   does not list them and the canonical product model has no field list.
