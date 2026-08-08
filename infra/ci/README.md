# CI

Implements Sprint 0 Task 0.5 (`ZIP_14_IMPLEMENTATION_PREP/IMPLEMENTATION_ROADMAP.md` §6).

## Provider

**GitHub Actions.** `REPOSITORY_STRUCTURE.md` reserves this directory for
"pipeline definitions — provider TBD", and `IMPLEMENTATION_ROADMAP.md` §7 item 2
records the CI provider as an open gap. That gap is now closed.

## Where the pipeline actually lives

[`.github/workflows/ci.yml`](../../.github/workflows/ci.yml)

GitHub Actions reads workflows from `.github/workflows/` and nowhere else, so the
workflow cannot physically live in this directory. This README holds the
directory's slot in `REPOSITORY_STRUCTURE.md` and records where to look.

Provider-specific artifacts that are *not* path-constrained — deployment
manifests, pipeline scripts invoked by a job — belong here.

## What runs

Two jobs on push to `main` and on every pull request. No deploy step, by design
(Task 0.5: "lint + test job on push/PR, no deploy step").

| Job | Command | Source of truth |
|---|---|---|
| `lint` | `pre-commit run --all-files` | `.pre-commit-config.yaml` pins ruff and mypy, so CI cannot drift from a developer's machine |
| `test` | `pytest tests -q` | `tests/` |

Python 3.12, matching `[tool.ruff] target-version` and `[tool.mypy] python_version`
in the root `pyproject.toml`.

## Known gaps

- **No dependency management.** No Sprint 0 task establishes it, so `pre-commit`
  and `pytest` are pinned inline in the workflow. Once Sprint 1 introduces a real
  dependency file, both jobs should install from it instead.
- **`test` tolerates an empty suite.** `tests/` currently holds only empty Task
  0.1 placeholders, and pytest exits 5 ("no tests collected") rather than 0.
  The job treats 5 as success. Remove that branch once the suite is non-empty,
  so an accidentally empty run is caught again.
