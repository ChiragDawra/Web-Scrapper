# Notification Engine

Final gate of the Deal Engine. Consumes `DEAL_SCORED`, emits `DEAL_NOTIFIED`,
and moves a deal from `SCORED` to `NOTIFIED`
(`ZIP_02/STATE_DIAGRAMS.md`).

---

## Confidence Threshold

**Only deals with Confidence >= 70 may be sent to users.**

Confidence is normalized 0-100 and is computed separately from the deal score
(`DEAL_SCORING.md`). A deal with a high score but confidence below 70 is not
notified.

Deals below the threshold stay at `SCORED` and are retained. They are not
discarded — persisted scores are required for analytics and future ML
training (`ZIP_09/DATASET_DESIGN.md`).

---

## Duplicate Suppression

Duplicate notifications must be prevented. This is separate from listing
deduplication, which happens earlier in the pipeline
(`DUPLICATE_DETECTION.md` dedups by marketplace listing ID and canonical
product mapping).

---

## Required Payload Fields

Every notification includes the marketplace and the deal ID.

The Bot renders these fields (`ZIP_06/MESSAGE_TEMPLATES.md`):

- Platform
- Brand
- Product
- Current price
- MRP
- Discount
- Deal ID
- Last verified time

The deal ID is an immutable UUID (`ZIP_03/ER_DIAGRAM.md`,
`ZIP_03/CONSTRAINTS.md`). Marketplace identity is immutable across the
lifecycle (ADR-005), which is what allows the Bot to display the platform and
the Planner to route on it later.

---

## Boundaries

- The Notification Engine publishes `DEAL_NOTIFIED`. It does not talk to
  Telegram. The Bot owns all user interaction
  (`ZIP_06/TELEGRAM_ARCHITECTURE.md`).
- Notification data is never used to make a purchase decision. Revalidation
  through the Revalidation Service is mandatory before quantity is collected
  (ADR-004, `REVALIDATION_FLOW.md`).

---

## Open Points

1. **Duplicate window (Q45).** "Prevent duplicate notifications" has no
   definition of duplicate. Same deal ID, same listing, or same product
   across marketplaces? And over what time window — the deal's lifetime, 24
   hours, forever?
2. **No rate limit (Q46).** Nothing caps notifications per user per hour or
   per day. A large scan producing many qualifying deals has no throttle.
3. **Single-user assumption (Q47).** No document says whether notifications
   go to one operator, a group, or per-user subscriptions. The `TelegramUser`
   entity exists but no relationship links a user to the deals they should
   receive.
4. **Confidence inputs (Q8a).** Data Quality, Historical Stability and Seller
   Reliability are named but undefined and unweighted, so the threshold of 70
   is not yet computable.
