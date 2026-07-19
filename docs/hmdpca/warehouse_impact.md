# Warehouse and Alpha Impact

**PRODUCTION_INFLUENCE=false**

## Purpose

This map explains why Alpha would buy each dataset. A dataset should not be procured
because it is interesting; it should close a measured Warehouse v2 or decision-quality
gap.

| Dataset | Warehouse capability added | Alpha systems improved | What does not improve automatically | Acceptance evidence |
| --- | --- | --- | --- | --- |
| NSE/BSE raw daily OHLCV | Exchange-authoritative bars and venue separation | Replay, Market DNA, Strategy Lab, feature attribution | Identity, corporate actions, survivorship | Session and field coverage; raw-value reconciliation |
| Trade count and turnover | Better liquidity and capacity evidence | Gate truth, candidate generation, portfolio sizing | Bid/ask spread or true execution capacity | Units, currency, zero-trade behavior, full population |
| Delivery volume and percentage | Delivery-aware price-volume evidence | Setup quality, breakout validation, Market DNA | Beneficial-owner identity or institutional intent | Quantity definitions, corrections, historical depth |
| Security master | Stable identifiers and series/reference facts | Historical universe, replay, recommendation lineage | Historical identity unless effective dated | Active/inactive sample and symbol-reuse cases |
| Listing/delisting/suspension history | Valid tradable universe by date | Point-in-time universe, opportunity truth, replay | Price correctness | IPO, suspension, relisting, and delisting cases |
| Corporate-action ledger | Event-aware raw/adjusted continuity | Replay, stops/targets, performance, learning | Merger lineage unless terms and successors are explicit | Known split/bonus/rights/merger/demerger cases |
| Historical index levels and TRI | Valid benchmarks and regime inputs | Benchmark replay, regime, performance attribution | Constituent membership | Level/TRI dates, base methodology, corrections |
| Historical index constituents | Membership-safe benchmark universes | Point-in-time universe, sector/regime, portfolio | Security identity unless identifiers are stable | Add/remove effective dates and inactive members |
| Point-in-time sector/industry | Historical grouping without current-label leakage | Regime, sector fit, DNA, portfolio concentration | Company fundamentals | Reclassification history and effective dates |
| Market breadth | Cross-sectional market-state evidence | Regime, timing, gate attribution | Security selection by itself | Denominator, unchanged/suspended handling |
| Shareholding pattern | Promoter/public/institutional ownership snapshots | Market DNA, risk, research | Daily FII/DII flows or causal interpretation | Filing timestamp, revision, security mapping |
| FPI/DII/MF aggregate flows | Market-wide institutional context | Regime and research diagnostics | Stock-level ownership | Definition and publication-time history |
| Mutual-fund portfolios | Security-level fund ownership snapshots | Ownership research, DNA, liquidity context | Daily transactions | Complete AMC coverage and as-of/publication dates |
| Earnings filings and board notices | Actual result and event chronology | Event studies, risk calendars, research | Consensus, surprise, or guidance normalization | Publication timestamp and restatement lineage |
| Point-in-time estimates/guidance | Revision-safe expectation history | Earnings surprise, feature attribution, Strategy Lab | Exchange truth or realized execution | India sample, contributor history, lag policy |

## Dependency Order

```text
Daily prices + security identity + calendar
                  |
                  v
Listing status + corporate actions
                  |
                  v
Point-in-time universe + index membership
                  |
                  v
Delivery/breadth/ownership/earnings enrichment
                  |
                  v
Certified replay and research features
```

Buying enrichment before identity and corporate-action safety creates more columns,
not more truth. Price, identity, calendar, listing status, and action lineage are the
minimum coherent Warehouse v2 unit.

## Decision-Quality Boundaries

- Delivery percentage can strengthen volume interpretation only after its definition
  and historical consistency are verified.
- Ownership can describe context; it must not be read as institutional conviction
  without filing lags and category changes.
- Earnings dates from exchange notices are event facts. Earnings surprises require a
  point-in-time expectation source and cannot be reconstructed from later consensus.
- Historical sectors and index membership must never be backfilled from current files.
- A second price source improves reconciliation, but conflicting venues must remain
  separate observations rather than being averaged into false certainty.

## Production Boundary

This document describes potential research value only. No dataset affects candidate
generation, recommendations, approval, allocation, or execution.

