# Claude Workflow

How to run an implementation session against this repository with Claude Code. This document governs *process*, not architecture. It does not modify `ZIP_13_ENGINEERING_CONTRACTS/` (frozen, v1.0) or add scope beyond `IMPLEMENTATION_ROADMAP.md` / `REPOSITORY_STRUCTURE.md`.

Core rule underneath every section below: **one task from `IMPLEMENTATION_ROADMAP.md`, one session-slice, one commit.** Everything else here exists to make that rule practical to follow with a limited context window.

---

## 1. Beginning an Implementation Session

Fixed order, every session, no skipping steps:

1. **State check.** Read `ZIP_14_IMPLEMENTATION_PREP/IMPLEMENTATION_ROADMAP.md` §2 (Sprint List) and find the current sprint's task table. If a per-ZIP `CURRENT_STATE.json` or `CHANGELOG.md` has been updated by a prior session (post-Sprint-16 convention, `IMPLEMENTATION_ROADMAP.md` Task 16.7), read that first — it is more current than your memory of the last session.
2. **Pick exactly one task.** Not a sprint, not "a few tasks" — one row from the sprint's task table. If the previous session ended mid-task, resume that same task before starting a new one.
3. **Load only what that task cites.** Every task row names the exact `ZIP_13_ENGINEERING_CONTRACTS/*.md` file(s) and section(s) it implements, plus its own "Files Involved" column. Load:
   - The cited ZIP_13 file(s) — full file if short (`ENUMS.md`, `VALIDATION_RULES.md`, `SERVICE_INTERFACES.md` are all under 260 lines), or just the cited section if the file is large (`DATABASE_SCHEMA.md`, `EVENT_SCHEMAS.md`).
   - `REPOSITORY_STRUCTURE.md` §2-3 for the target service's layout, if creating new files.
   - The relevant existing source files under `services/<service>/` or `libs/` that the task will edit — not the whole service tree.
   - `IMPLEMENTATION_ROADMAP.md` §5 (Standard Review Checklist) — short, cheap to keep loaded all session.
4. **Do not load:** other sprints' task tables, other services' source trees, ZIP_01-ZIP_12 (superseded by ZIP_13 on any point of conflict — only consult them if ZIP_13 is silent on something ZIP_13's own README says it should cover, and even then treat it as background, not a contract).
5. State the task ID (e.g. "Sprint 3, Task 3.4") and its Definition of Done back before writing any code, so the session has an explicit, checkable target.

---

## 2. Keeping Context Under ~30%

The roadmap's own task granularity (30-90 minutes) is the primary lever — small tasks mean small context. Beyond that:

- **Read narrow, not wide.** Use `grep`/targeted `Read` with line ranges instead of reading full large files. `DATABASE_SCHEMA.md` and `EVENT_SCHEMAS.md` are the two files most tasks over-read from — go straight to the numbered section a task cites.
- **Never re-read a file you just wrote.** If the edit tool didn't error, it succeeded — trust that instead of re-reading to confirm.
- **One task, one context.** Don't carry the full history of the last 5 tasks in active context "just in case." If task 3.6 needs something task 3.4 established, name the specific fact (e.g. "the `deal_writer.py` dedup guard uses `SELECT ... FOR UPDATE`") rather than re-reading `deal_writer.py` in full.
- **Prefer the Standard Review Checklist over re-deriving review criteria.** It's short and already loaded; don't re-read `VALIDATION_RULES.md` in full to remember a rule the checklist already summarized.
- **When context crosses roughly 30%,** stop mid-sprint (not mid-task if avoidable — finish the current task, commit, then stop) and start a new session per §5 below rather than pushing through.
- **Delegate exploration, not decisions.** If a task requires locating something ("where does X get consumed downstream"), use a search/explore pass scoped to that question, then discard the exploration transcript from active context — keep only the answer.

---

## 3. Avoiding Architecture Drift

Architecture drift here means: code that silently diverges from `ZIP_13_ENGINEERING_CONTRACTS/`, or a "helpful" fix that redesigns something instead of flagging it.

- **The frozen files are read-only, always.** `DATABASE_SCHEMA.md`, `EVENT_SCHEMAS.md`, `API_CONTRACTS.md`, `DTOS.md`, `CANONICAL_MODELS.md`, `SERVICE_INTERFACES.md`, `ENUMS.md`, `VALIDATION_RULES.md`, `ERROR_CODES.md`, `STATE_TRANSITIONS.md`. If a session's diff touches any of these, that is a stop-and-report condition, not a thing to quietly fix and continue past.
- **Field names, types, nullability — copy, don't paraphrase.** When a task says "matches `PurchaseOutcome` exactly," that means the same field names, same required/nullable-ness, not an equivalent-but-renamed version.
- **A discovered gap is not an invitation to invent.** If a task can't be completed because ZIP_13 (or its surrounding docs) doesn't specify something, add it to `IMPLEMENTATION_ROADMAP.md` §7 (Known Gaps) with what's missing and what task is blocked, and stop that task rather than guessing. Sprint 14 Task 14.1 (frontend framework) is the existing template for how to close a *process* gap without touching architecture.
- **No unrequested scope.** A task fixing `deal-engine`'s `score()` does not also refactor `resolveBrand()` "while we're in there." That's a separate task row, run separately, reviewed separately.
- **Cross-service boundaries are load-bearing, not a style preference.** ADR-009 (no service reads another's tables directly) shows up as a checklist item for a reason — a task that seems to need a cross-schema read is a task that needs an event or a Gateway read-only client, never a direct query.
- **When in doubt about whether something is "architecture" vs. "implementation detail,"** the test is: does `ZIP_13_ENGINEERING_CONTRACTS/` name it? If yes, it's frozen. If no, it's an implementation detail this workflow (or the roadmap's gap log) can decide.

---

## 4. Prompt Templates

**Starting a task:**
```
Implement Task <sprint>.<task#> from IMPLEMENTATION_ROADMAP.md.
Objective: <copy the Objective column>
Files: <copy the Files Involved column>
Contract(s) to match exactly: <ZIP_13 file + section the task cites>
Definition of Done: <copy the DoD column>
Do not touch any file outside "Files Involved" without stopping to explain why first.
```

**Resuming a session:**
```
Resume Task <sprint>.<task#>. Last session ended at: <one-line state, e.g.
"normalize() written and unit-tested, event emit wiring not yet started">.
Re-read only <specific file(s)>, not the whole service tree.
```

**Reporting a discovered gap (per §3):**
```
Task <sprint>.<task#> is blocked: <what ZIP_13/surrounding docs don't specify>.
This is not something I'm deciding — logging it in IMPLEMENTATION_ROADMAP.md §7
and stopping this task. <if applicable: which other task depends on this being resolved>
```

**Requesting a review pass (§5 below):**
```
Review the diff for Task <sprint>.<task#> against:
1. Its own Definition of Done.
2. The Standard Review Checklist (IMPLEMENTATION_ROADMAP.md §5).
3. Any task-specific checklist addition in its row.
Flag anything that touches a file in ZIP_13_ENGINEERING_CONTRACTS/ as a hard stop.
```

**Ending a session:**
```
Session end for Task <sprint>.<task#>: <done | partial, resume point: ...>.
Run the Session-Ending Checklist (CLAUDE_WORKFLOW.md §7) before closing.
```

---

## 5. Code Review Workflow

1. **Self-check against the task row first.** Before calling anything "done," re-read the task's own Definition of Done column and confirm each clause literally, not approximately.
2. **Run the Standard Review Checklist** (`IMPLEMENTATION_ROADMAP.md` §5) plus any task-specific addition in the "Review Checklist" column.
3. **Diff against the cited contract, not against memory.** For any task touching a DB table, event schema, or DTO, re-open the exact ZIP_13 section and compare field-by-field — don't rely on what was loaded three tasks ago, it may have been evicted from context.
4. **Tests are part of the review, not a follow-up.** A task isn't reviewed until its own tests (per its DoD) are green.
5. **Flag, don't fix, anything outside scope.** If review surfaces an unrelated pre-existing issue, note it (a comment, or a new line in a backlog if one exists) rather than fixing it inside this task's diff.
6. **One task = one commit.** Commit message references the task ID (e.g. `feat(deal-engine): score() + resolveBrand() — Sprint 3 Task 3.2-3.3`) so the roadmap and git history stay traceable to each other.

---

## 6. When to Start a New Conversation

Start fresh rather than continuing when any of the following is true:
- Context has crossed ~30% (§2) and the current task is at a clean stopping point (task done, or a sub-step boundary within a task).
- A sprint boundary is reached — new sprint, new session, even if context is low, since it's a natural checkpoint for the Session-Ending Checklist below.
- A gap was just logged in `IMPLEMENTATION_ROADMAP.md` §7 that blocks the current task — the next session should start by reading that gap's resolution status, not by re-deriving the blocker.
- The session has drifted into exploratory/debugging territory unrelated to the current task's files (e.g. chasing an unrelated flaky test) — finish or abandon that detour explicitly, then restart clean rather than let it bleed into the next task.
- More than one task has been attempted in the same session and the second task's context is now mixed with the first's — split them retroactively by starting the next task fresh.

Do **not** start fresh mid-task just because context feels "cluttered" — finish the task, commit, and let the natural task boundary be the reset point. Fragmenting a single task across many short sessions costs more (re-loading context each time) than it saves.

---

## 7. Session-Ending Checklist

Before closing any session:

- [ ] Current task's tests pass locally.
- [ ] Diff reviewed against the Standard Review Checklist (`IMPLEMENTATION_ROADMAP.md` §5) and the task's own Review Checklist column.
- [ ] No frozen `ZIP_13_ENGINEERING_CONTRACTS/` file appears in the diff.
- [ ] Commit made, message references the task ID.
- [ ] If the task is only partially done: one clear sentence recorded (commit message body, or wherever the project tracks this) describing exactly where it stopped, so the next session's "Resuming a session" prompt (§4) has something concrete to point at.
- [ ] If a gap was discovered: it's recorded in `IMPLEMENTATION_ROADMAP.md` §7 with which task it blocks, not left implicit in the conversation only.
- [ ] If this was the last task in a sprint: the sprint's Definition of Done and Acceptance Criteria (its own section header in `IMPLEMENTATION_ROADMAP.md` §6) are checked against reality, not assumed from individual task completions.
