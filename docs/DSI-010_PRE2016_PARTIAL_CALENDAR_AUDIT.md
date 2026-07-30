# DSI-010 — Partial Official Calendar Audit

## Purpose

The full DSI-010 calendar certifier remains fail-closed until official NSE
evidence covers every year from 2005 through 2015. The partial audit exists only
to inspect supported official-year subsets and expose conflicts before missing
years are acquired.

## Command

```bash
poetry run python -m alpha benchmark \
  decision-superiority-pre2016-calendar-partial-audit \
  --database alpha_data/warehouse/historical_truth.duckdb \
  --manifest alpha_data/manifests/archive_manifest.jsonl \
  --official-source <OFFICIAL_SOURCE_JSON> \
  --output artifacts/dsi010_pre2016_partial_calendar
```

Repeat `--official-source` for every supported year source.

## Outputs

The command exports:

- holiday dates that also have observed candles;
- unresolved weekdays inside officially covered years;
- unavailable archive dates inside officially covered years;
- annual reconciliation metrics;
- a deterministic summary that keeps certification disabled.

## Governance

The partial audit cannot:

- mark the 2005–2015 calendar certified;
- infer holidays from archive HTTP status;
- infer special sessions from observed candles;
- fill missing official years;
- influence production, recommendations or strategy promotion.

```text
CALENDAR_CERTIFICATION_PERMITTED=false
PRODUCTION_INFLUENCE=false
```

## Source boundary

Formatted partial-audit implementation:

`efe3936d5738145a01bffe9c7140ab8208bda33b`

Permanent GitHub validation must pass on this owner-authored publication head
before local use.
