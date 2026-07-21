# HTR-007 Slice 2 Validation

## Scope

This validation record covers the checkpointed NSE bhavcopy backfill orchestrator on branch `feature/htr-007-checkpointed-backfill`.

## Guarded source validation

The formatted source commit `fd6de00cffdf25aefb3e20bd54be850e2feda3fc` was created only after the temporary guarded workflow passed all of the following on the same working tree:

- Ruff checks for all Slice 2 source and tests.
- Full MyPy over `alpha`.
- Backfill engine tests.
- Backfill CLI tests.
- Existing archive-manager compatibility tests.
- Existing resumable-download compatibility tests.

The temporary workflow deleted itself before committing the validated source.

## Required repository validation

Before PR #18 can leave draft state, GitHub must independently pass:

```bash
poetry run ruff check .
poetry run ruff format --check .
poetry run mypy alpha
poetry run pytest -q
```

An authorized local smoke run is also required before merge. The smoke run must retain:

- planning basis `WEEKDAY_CANDIDATES_UNRECONCILED`;
- certification state `unreconciled_not_certified`;
- explicit unavailable and failed counts;
- deterministic JSON, CSV, Markdown, checkpoint, and report-hash evidence.

No full historical certification is claimed by Slice 2.
