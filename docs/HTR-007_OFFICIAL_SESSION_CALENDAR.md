# HTR-007 Official Session Calendar and Session Truth

## Purpose

This slice reconciles canonical NSE cash-market candles with official exchange holiday and special-session evidence. It does not infer that a missing bhavcopy is a holiday.

## Evidence model

The engine accepts immutable JSON source documents:

1. The official NSE trading-holiday API payload containing a `CM` list.
2. Normalized official historical circular evidence containing:

```json
{
  "covered_years": [2024],
  "source_url": "https://www.nseindia.com/...official-circular...",
  "holidays": [
    {
      "tradingDate": "26-Jan-2024",
      "description": "Republic Day"
    }
  ],
  "special_sessions": [
    {
      "tradingDate": "02-Mar-2024",
      "description": "Official special live trading session"
    }
  ]
}
```

Every source file is identified by its SHA-256. Raw official files remain under the ignored Historical Truth runtime tree and are not committed to Git.

## Session classifications

- `regular_session`: weekday with canonical candles and no official closure.
- `special_session`: officially declared special session, or an observed weekend session awaiting official confirmation.
- `holiday`: officially declared CM holiday without candles.
- `weekend`: ordinary Saturday or Sunday without candles.
- `unresolved_weekday`: weekday without candles and without official closure evidence.

## Fail-closed findings

- `HOLIDAY_HAS_OBSERVED_CANDLES`
- `MISSING_OFFICIAL_SPECIAL_SESSION`
- `UNCONFIRMED_SPECIAL_SESSION`

A report is `certified` only when every year in the requested window has official source coverage, unresolved weekdays are zero, special sessions are confirmed and no conflicts remain. Otherwise it is `incomplete_official_evidence`.

## Commands

Download the current official NSE holiday payload:

```bash
poetry run python -m alpha.historical_truth.session_calendar_cli download-current \
  --source-dir alpha_data/raw/nse/calendar
```

Reconcile all JSON source files in the source directory:

```bash
poetry run python -m alpha.historical_truth.session_calendar_cli reconcile \
  --start 2016-01-01 \
  --end 2026-07-20 \
  --root alpha_data \
  --source-dir alpha_data/raw/nse/calendar \
  --output-dir artifacts/htr007_session_calendar
```

Both commands show progress. The reconciliation emits deterministic JSON, CSV and Markdown artifacts plus a report SHA-256.

## Governance boundary

- Observed bhavcopies are session evidence, not independent holiday evidence.
- Weekday HTTP 404 responses remain unresolved until matched to official closure evidence.
- Weekend bhavcopies are treated as unconfirmed special sessions until an official special-session source is supplied.
- This slice changes no strategy, score, recommendation, approval or portfolio policy.
