# HTR-007 Slice 1 Validation

The cross-era backfill pilot is validated without performing live NSE downloads in CI.

## Automated gates

```bash
poetry run ruff check .
poetry run ruff format --check .
poetry run mypy alpha
poetry run pytest -q
```

Focused pilot tests:

```bash
poetry run pytest \
  tests/historical_truth/test_backfill_pilot.py \
  tests/historical_truth/test_backfill_pilot_cli.py -q
```

The deterministic test archives cover:

- legacy bhavcopy schemas for 2016, 2020 and 2023,
- UDiFF bhavcopy schema for 2026,
- idempotent reruns and identical artifact hashes,
- immutable raw-archive checksum drift,
- unsafe nested ZIP members,
- standalone CLI registration and export.

## Live pilot gate

The live pilot is run only from an authorized local environment:

```bash
poetry run python -m alpha.historical_truth pilot \
  --root alpha_data \
  --output-dir artifacts/htr007_backfill_pilot
```

A live result is not accepted merely because downloads complete. Every representative date must have:

- official URL and immutable raw checksum,
- the expected legacy or UDiFF schema,
- source validation success,
- canonical rows in DuckDB,
- a verified point-in-time snapshot,
- no checksum drift or ZIP safety failure.

Full multi-year acquisition remains blocked until the cross-era pilot passes locally and its artifacts are reviewed.
