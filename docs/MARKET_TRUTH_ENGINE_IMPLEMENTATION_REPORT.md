# Market Truth Engine Implementation Report

## Delivered

Project Alpha v4.0 now includes `alpha/market_truth/`, a typed and deterministic
market-data authority with:

- plugin registration and capability-based routing;
- explicit provider priorities and failover evidence;
- provider health persistence;
- point-in-time daily, weekly, monthly, tick, one-minute, and five-minute services;
- identity, corporate-action, calendar, index, and fundamental services;
- structural quality and freshness checks;
- evidence-authority confidence assessment;
- content-addressed versions and provenance;
- immutable checksum-verified cache entries;
- read-only access to Alpha's canonical DuckDB prices;
- JSON and CSV truth exports;
- CLI and IRD integration;
- an automated consumer-isolation regression guard.

## Current Provider State

The local canonical price store is configured and contains 2,466 sessions from
2016-07-08 through 2026-07-10. The versioned cache is configured. NSE remote access is
explicitly opt-in. BSE, licensed historical, licensed live, and broker fallback plugins
are registered but unconfigured.

This means daily, weekly, and monthly truth is operational from cached authoritative
prices. Identity, corporate actions, intraday, calendars, indices, and fundamentals
correctly return `NO_DATA` until appropriate evidence providers are configured.

## Sample Local Truth

For `RELIANCE`, 2026-07-01 through 2026-07-10:

```text
Dataset: DAILY
Records: 4
Provider: LOCAL_CANONICAL_CACHE
Evidence: CACHED_AUTHORITATIVE
Confidence: 90.00% (VERY_HIGH)
Quality: COMPLETE
Completeness: 100%
Last close: INR 1,307.80 on 2026-07-10
```

The same default installation returns this honest intraday state:

```text
Dataset: MINUTE_1
Records: 0
Provider: NO_DATA
Confidence: 0% (NONE)
Quality: UNAVAILABLE
Alpha must refuse data-dependent action.
```

## Consumer Migration

Historical ingestion, backtest acquisition, Replay, breakout reconstruction, source-gap
inventory, Forward Validation, Autonomous Loop marking, Closed Learning Loop evidence,
Market DNA, Strategy Lab, and IRD now reach market data through MTE-owned interfaces.
The migration changes data access only; recommendation, approval, allocation, strategy,
portfolio, and trade logic are unchanged.

## Tests

The MTE regression suite covers provider registration, conflict detection, failover,
health, daily/weekly/monthly aggregation, tick/one-minute/five-minute freshness,
identity, corporate actions, calendars, indices, fundamentals, cache immutability,
checksum tampering, deterministic versions, provenance, local DuckDB reads, confidence,
quality, CLI rendering, JSON/CSV exports, `NO_DATA`, point-in-time rejection, initial
provider classes, and consumer isolation.

## Quality Gates

```text
poetry run pytest
1683 passed in 192.46s

poetry run ruff check .
All checks passed!

poetry run mypy alpha
Success: no issues found in 508 source files

poetry build
Built alpha-1.3.0.dev0.tar.gz
Built alpha-1.3.0.dev0-py3-none-any.whl
```

## Production Boundary

- Broker orders: disabled
- Automatic capital deployment: disabled
- Recommendation and approval behavior: unchanged
- Automatic provider-derived policy changes: disabled
- `PRODUCTION_INFLUENCE=false`
