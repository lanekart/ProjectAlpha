# Market Truth Engine

## Purpose

The Market Truth Engine (MTE) is Project Alpha's single consumer-facing market-data
boundary. Downstream systems request market truth and remain unaware of whether the
selected evidence came from an exchange, licensed vendor, broker fallback, or local
cache.

MTE is data infrastructure only. It cannot place orders, allocate capital, alter a
recommendation, or mutate policy.

`PRODUCTION_INFLUENCE=false`.

## Truth Contract

Every response is an immutable `MarketTruth` envelope containing:

- source and selected provider;
- observation timestamp and point-in-time request boundary;
- evidence class;
- transparent confidence assessment;
- quality classification (`COMPLETE`, `PARTIAL`, `DEGRADED`, `UNAVAILABLE`);
- measured completeness;
- content-addressed version;
- provenance ID, lineage hash, provider checksum, and all failover attempts;
- typed records, or an explicit empty `NO_DATA` response.

An MTE response is actionable only when it has records and quality is `COMPLETE`.
Stale intraday data, future-dated rows, invalid OHLC relationships, duplicates, missing
sources, and cache-integrity failures are not actionable.

## Architecture

```text
Provider plugins
  -> deterministic capability/priority registry
  -> provider failover router
  -> structural quality validation
  -> confidence assessment
  -> content-addressed provenance/version
  -> checksum-verified immutable cache
  -> typed MarketTruth services
  -> Alpha consumers
```

New providers implement the `MarketTruthProvider` protocol and register a
`ProviderDescriptor`. No MTE core switch or conditional needs to change.

## Provider Registry

The initial registry exposes these provider classes:

| Provider | Priority | Current default state | Role |
|---|---:|---|---|
| NSE Official | 10 | Remote access opt-in | Authoritative daily bhavcopy |
| BSE Official | 20 | Unconfigured | Authoritative fallback |
| Licensed Historical Archive | 30 | Unconfigured | Historical, identity, actions, reference data |
| Licensed Live Feed | 40 | Unconfigured | Tick and intraday |
| Broker Feed (Fallback) | 50 | Unconfigured | Bounded live fallback |
| Local Canonical Cache | 90 | Configured when DuckDB exists | Persisted daily prices |
| Local Versioned Cache | 95 | Configured | Last-resort checksum-verified truth |

Unconfigured providers are visible in health reports and are never silently skipped in
provenance. MTE never fabricates a substitute dataset.

## Historical Data

`HistoricalMarketTruthService` supports daily, weekly, and monthly bars. Weekly and
monthly bars are deterministically aggregated from a frozen daily response:

- open: first session open;
- high: maximum session high;
- low: minimum session low;
- close: final session close;
- volume: sum of session volume;
- timestamp: final included session.

The request end and `as_of` boundaries are enforced before aggregation, preventing
look-ahead.

## Intraday Data

`IntradayMarketTruthService` supports tick, one-minute, and five-minute requests.
Freshness limits are part of the request contract. Stale records are classified as
`DEGRADED` and are not actionable. The default installation returns `NO_DATA` until a
licensed live or bounded broker plugin is configured.

## Identity And Corporate Actions

Identity records carry symbol, series, ISIN, security ID, active interval, status,
continuity ID, and authority. Corporate actions support split, bonus, rights, merger,
demerger, symbol change, listing, delisting, and suspension events. Events are
effective-dated and versioned.

The current default installation does not infer identity or corporate actions from
price rows. It returns `NO_DATA` until an authoritative plugin is configured.

## Cache And Versioning

Provider datasets are stored under a deterministic request key with a content checksum.
Existing cache keys cannot be rewritten with different content. Every read recomputes
the provider checksum. A mismatch raises an integrity error and the router fails closed.

The local canonical DuckDB source is opened read-only, allowing concurrent terminal
queries without triggering schema migration or write-style database locks.

## Consumer Migration

The following consumers now use MTE interfaces or compatibility adapters:

- historical ingestion and backtest archive acquisition;
- Replay and historical observation construction;
- breakout reference and source-inventory diagnostics;
- Strategy Lab and Market DNA through their replay evidence inputs;
- Forward Validation future-bar reads;
- Autonomous Loop mark-to-market through Forward Validation's MTE source;
- Closed Learning Loop through immutable forward outcomes;
- IRD through the `market-truth-engine` diagnostic plugin.

Provider-specific read-only NSE and Upstox diagnostic transports are owned by MTE.
Consumer packages contain an automated guard against direct provider, network, or
database access.

## CLI

```text
poetry run python -m alpha market-truth providers
poetry run python -m alpha market-truth health
poetry run python -m alpha market-truth quality --symbol RELIANCE --start 2026-01-01 --end 2026-07-10
poetry run python -m alpha market-truth confidence --symbol RELIANCE --start 2026-01-01 --end 2026-07-10
poetry run python -m alpha market-truth identity --symbols RELIANCE --as-of 2026-07-10
poetry run python -m alpha market-truth corporate-actions --symbols RELIANCE --start 2016-01-01 --end 2026-07-10 --as-of 2026-07-10
poetry run python -m alpha market-truth daily --symbol RELIANCE --start 2026-07-01 --end 2026-07-10
poetry run python -m alpha market-truth weekly --symbol RELIANCE --start 2026-01-01 --end 2026-07-10
poetry run python -m alpha market-truth monthly --symbol RELIANCE --start 2026-01-01 --end 2026-07-10
poetry run python -m alpha market-truth intraday --symbol RELIANCE --interval MINUTE_1 --start 2026-07-10T09:15:00+05:30 --end 2026-07-10T09:20:00+05:30
poetry run python -m alpha market-truth report
```

Use `--remote` only on historical commands when official NSE acquisition is intended.
Daily truth supports deterministic `--json` and `--csv` exports.

## Operational Rules

- Do not consume provider modules from decision or research systems.
- Do not treat `PARTIAL`, `DEGRADED`, or `UNAVAILABLE` truth as actionable.
- Do not overwrite cache entries or provenance.
- Do not combine reconstructed and forward-observed evidence in one response.
- Do not infer missing identity, actions, calendars, fundamentals, or prices.
- Monitor provider health, cache integrity, completeness, and source lineage.

Broker orders are disabled. Automatic capital deployment is disabled. Production
policy influence is disabled.

