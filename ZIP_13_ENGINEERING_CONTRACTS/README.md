# ZIP_13 — Engineering Contracts

Purpose: close every gap flagged in ZIP_01-12 (Q1-Q55) with a binding decision.
No file in this ZIP is a proposal. Where a prior doc said "unstated" or
"unresolved", this ZIP is the resolution. Where this ZIP disagrees with an
earlier ZIP, **this ZIP wins** — it is dated after and supersedes on every
point of conflict listed in `RESOLVED_QUESTIONS.md`.

Goal: an engineer builds a service by reading its ZIP + this ZIP. No
architectural decision left to author of the code.

## Files

| File | Contract type |
|---|---|
| `DATABASE_SCHEMA.md` | Full DDL, every table, every column |
| `EVENT_SCHEMAS.md` | JSON Schema for every event + envelope |
| `API_CONTRACTS.md` | REST endpoints, API Gateway + Admin Dashboard |
| `DTOS.md` | Request/response DTOs for API + inter-service payloads |
| `CANONICAL_MODELS.md` | Canonical Product, Listing and shared domain models |
| `SERVICE_INTERFACES.md` | Method signatures every service must implement |
| `ENUMS.md` | Every enum, every allowed value, no free-text status fields |
| `VALIDATION_RULES.md` | Field-level and cross-field validation, applied at boundary |
| `ERROR_CODES.md` | Canonical error code registry, HTTP + event-level |
| `STATE_TRANSITIONS.md` | Every state machine, every edge, every guard, every timeout |
| `RESOLVED_QUESTIONS.md` | Q1-Q55 mapped to their binding resolution |

## Non-negotiable defaults applied throughout

- All internal entity primary keys: **UUID v4**. No exceptions (resolves Q29).
- All money: **integer, minor units (paise), currency fixed to INR for MVP**.
- All timestamps: `timestamptz`, UTC, ISO-8601 on the wire.
- All events: wrapped in the envelope defined in `EVENT_SCHEMAS.md` §1.
- All consumers: idempotent via `event_id` dedup (resolves Q17).
- All cross-service reads: request/response event pairs only, never DB reads
  (ADR-009, unchanged).
