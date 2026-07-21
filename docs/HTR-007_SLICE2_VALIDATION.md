# HTR-007 Slice 2 Validation

## Scope

This validation record covers the checkpointed NSE bhavcopy backfill orchestrator on branch `feature/htr-007-checkpointed-backfill`.

## Guarded source validation

The formatted Slice 2 source commit `fd6de00cffdf25aefb3e20bd54be850e2feda3fc` was created only after the temporary guarded workflow passed all of the following on the same working tree:

- Ruff checks for all Slice 2 source and tests.
- Full MyPy over `alpha`.
- Backfill engine tests.
- Backfill CLI tests.
- Existing archive-manager compatibility tests.
- Existing resumable-download compatibility tests.

The standalone CLI was corrected to parse ISO date strings explicitly because the pinned Typer version does not support `datetime.date` option annotations.

## Pilot compatibility validation

Full repository testing identified that immutable archive drift was blocked correctly but the original pilot evidence flag was not propagated through the new warehouse failure path. Commit `0b4dd2f1c0736f4e6ad994a303f31817d813b8c7` restores the deterministic `checksum_drift` flag while retaining fail-closed behavior.

The guarded compatibility workflow passed:

- Ruff for the pilot source.
- Full MyPy over `alpha`.
- Cross-era pilot tests.
- Checkpointed backfill engine tests.
- Backfill CLI tests.

Each temporary workflow deleted itself before committing validated source.

## Runtime repository hygiene

Authorized pilot execution exposed that Historical Truth runtime state had previously been committed to Git. Slice 2 removes tracked raw archives, staging CSVs, immutable snapshots, warehouse files, manifests and checkpoints from the repository index while preserving those paths as ignored local runtime state.

This prevents future authorized downloads from dirtying the source tree or being accidentally committed. Local runtime data must be backed up before first synchronizing to the cleaned branch head, then restored after the reset.

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
