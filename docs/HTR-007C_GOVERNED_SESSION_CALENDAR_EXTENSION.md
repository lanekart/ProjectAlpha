# HTR-007C Governed Session Calendar Extension

HTR-007C appends official NSE CM calendar evidence beyond an existing certified calendar window without rewriting historical sources or records.

## Extension contract

- Verify the existing calendar report SHA-256 before use.
- Verify every existing source file against the source registry checksum.
- Fetch and immutably persist the current official NSE CM holiday payload, or consume an explicitly pinned source.
- Scope the appended source to the newly governed year or years.
- Preserve all existing governed source files unchanged.
- Reconcile the complete calendar from the original start date through the requested extension date.
- Compare every historical record through the old calendar end and fail on any parity difference.
- Include regular sessions, official holidays and officially evidenced special sessions.
- Keep raw OHLCV immutable.

## B1C compatibility repair

HTR-007C also corrects two downstream reporting semantics:

- Observed sessions outside a stale calendar window are reported as `OBSERVATIONS_BEYOND_GOVERNED_CALENDAR_WINDOW`, not as calendar/database contradictions.
- Quarantine economic weight is labelled `MEASURED_OBSERVED_DATABASE_WINDOW` until governed session coverage is complete. It becomes `MEASURED_GOVERNED_COMPLETE_WINDOW` only after full session certification.

## Command

```bash
poetry run python -m alpha historical-truth session-calendar-extend-certify \
  --existing-calendar-report artifacts/htr007_historical_session_evidence/htr007_session_calendar.json \
  --database alpha_data/warehouse/historical_truth.duckdb \
  --source-dir alpha_data/sources/session_calendar \
  --through-date 2026-07-20 \
  --output artifacts/htr007c_governed_calendar_extension_2026 \
  --refresh
```

For deterministic offline verification, supply `--current-source` and use `--no-refresh`.

## Required outputs

- `htr007_session_calendar.json`
- `htr007_session_calendar.csv`
- `htr007_session_calendar.md`
- `htr007c_session_calendar_extension.json`
- `htr007c_session_calendar_extension.md`

## Governance

- No benchmark replay is executed.
- No candidate, scoring, approval, risk or production-policy behavior changes.
- Existing source files and raw candles remain immutable.
- `PRODUCTION_INFLUENCE=false`.
