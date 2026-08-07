# Bot Events

Event names follow the canonical catalog in
`ZIP_02/EVENT_DRIVEN_ARCHITECTURE.md`. Where this file and the catalog
disagree, the catalog wins.

Transport is Redis Streams. Every event is versioned, e.g.
`USER_INTERESTED.v1`.

---

## Consumes

| Event | Producer | Bot behaviour |
|---|---|---|
| `DEAL_NOTIFIED` | Deal Engine — Notification Engine | Render the deal card and move `IDLE -> DEAL_SENT` (`MESSAGE_TEMPLATES.md`, `STATES.md`) |
| `DEAL_REVALIDATED` | Revalidation Service | If the deal still holds, move `REVALIDATING -> WAITING_QUANTITY`. If it changed or expired, send an updated deal card and return to `DEAL_SENT` (`REVALIDATION_FLOW.md`) |
| `DEAL_EXPIRED` | Deal Engine — Deal Lifecycle component | Inform the user and terminate the conversation for that deal |

---

## Produces

| Event | When | Source |
|---|---|---|
| `USER_INTERESTED` | The user taps Interested | `BUTTONS.md`, `INTERESTED_FLOW.md` |
| `PURCHASE_REQUESTED` | The user confirms quantity and total | `QUANTITY_COLLECTION.md`, `ORDER_CONFIRMATION.md` |
| `PURCHASE_CANCELLED` | The user cancels at confirmation | `STATES.md` |

---

## The Bot does not call connectors

Revalidation is event-driven. The Bot publishes `USER_INTERESTED` and then
waits for `DEAL_REVALIDATED`. It never calls a marketplace connector
directly.

```
Bot ---USER_INTERESTED--->  Revalidation Service
                                   |
                                   v
                        DEAL_REVALIDATION_REQUEST
                                   |
                                   v
                          Marketplace Connector
                                   |
                                   v
Bot <---DEAL_REVALIDATED---  Revalidation Service
```

This supersedes the wording in `LIVE_PRICE_REFRESH.md` and
`INTERESTED_FLOW.md`, which described the Bot querying the connector itself.
The underlying rule is unchanged and still binding: **no purchase decision is
ever taken from cached notification data.** Only the transport changed.

While waiting, the Bot holds state `REVALIDATING` (`STATES.md`).

---

## Open points

1. No payload schema exists for `USER_INTERESTED`, `PURCHASE_REQUESTED` or
   `PURCHASE_CANCELLED` (Q18).
2. No timeout is defined for the `REVALIDATING` state. If
   `DEAL_REVALIDATED` never arrives, the Bot's behaviour is unspecified
   (Q24).
3. The Bot produces no event for `Ignore` or `Watch Later`, and no state
   transition is defined for either button (Q24).
4. The Bot is not listed as a consumer of `PURCHASE_COMPLETED` or
   `PURCHASE_FAILED`, so how the user learns the outcome of their approved
   purchase is unspecified (Q37).
