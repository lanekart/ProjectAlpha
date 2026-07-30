# DSI-010B5 — Final Official-Evidence Closure

## Purpose

DSI-010B5 closes the 66 corporate-action evidence cases remaining after
DSI-010B4 and attempts to materialize the complete 2005–2015 adjusted price
history. The milestone remains research-only and fail-closed.

Event-factor certification and historical-row identity certification are
separate contracts. An official factor does not authorize Alpha to assign a
legacy candle to that factor's security by ticker alone.

## Event Closure

All 66 starting event cases reached terminal governed outcomes:

| B4 missing component | Resolved |
| --- | ---: |
| Fourteen governed pre-event bars | 31 |
| First governed action-session candle | 10 |
| Governed reference-price identity | 12 |
| Complete official equity-rights terms | 11 |
| Official effective-dated ISIN transition | 1 |
| Authoritative superseding official terms | 1 |

The complete 705-case material validation population now contains:

| Outcome | Count |
| --- | ---: |
| `FACTOR_CONFIRMED_CORRECT_MARKET_GAP` | 695 |
| `FACTOR_CERTIFIED_OFFICIAL_TERMS_CONTINUITY_NOT_TESTABLE` | 2 |
| `FACTOR_NON_MULTIPLICATIVE` | 8 |
| Unresolved | 0 |

The two continuity-not-testable cases are VASWANI and MINDACORP. Their official
bonus factors and governed action candles are certified, but the securities
have zero and one prior governed sessions respectively. The 14-bar ATR
requirement was not weakened.

The effective terminal factor population is 697 certified multiplicative
factors, eight non-multiplicative events and zero unresolved factors.

## Named Cases

`TATAPOWER`

Both the 2011 split and 2014 rights event are confirmed. The rights reference
and action-session identities use the explicit official transition contract;
the missing-ISIN bridge is not used to bypass an explicit mismatch.

`HINDMOTOR`

The BSE-hosted annual report provides supersession proof for the
court-confirmed reduction from paid-up face value Rs.10 to Rs.5, states that
share count was unchanged, and records the suspension boundary. The NSE
recommencement notice governs the successor symbol, series and ISIN. The event
is confirmed with neutral price and quantity factors of 1.0.

## Adjusted-History Materialization

The materializer admits a historical candle only through:

1. exact candle ISIN equal to the factor identity; or
2. a signed, dated official identity bridge covering that exact candle date,
   symbol and series.

It applies every accepted future factor backward and preserves factor IDs,
source hashes and lineage in a separate DuckDB overlay. The raw warehouse is
read-only.

Results:

| Measure | Count |
| --- | ---: |
| Required pre-action adjustment rows | 500,046 |
| Governed adjusted rows | 246,688 |
| Exact-ISIN adjusted rows | 115,776 |
| Certified-bridge adjusted rows | 130,912 |
| Uncertified identity rows | 253,358 |
| Unresolved governed identities | 330 |
| Unresolved date/series segments | 476 |
| Invalid adjusted rows | 0 |
| Duplicate adjusted rows | 0 |

Adjusted rows increased from 99,106 at the B4 boundary to 246,688. On the
comparable one-interval-per-governed-identity basis, mixed identities declined
from 349 to 330.

## Remaining Evidence Boundary

The remaining blocker is not corporate-action terms or continuity. It is the
absence of effective-dated official identity history for legacy candles whose
ISIN field is empty.

The 476 exact segments comprise:

- 415 `NO_MATCHING_OFFICIAL_INTERVAL`;
- 60 `SERIES_MISMATCH`; and
- one `DATE_OUTSIDE_INTERVAL`.

Every segment records the governed identity, symbol, series, date range,
affected-row count and exact bridge rejection reason. The rows remain in the
raw warehouse. No security or period is excluded.

Certifying these rows requires official historical ISIN, symbol and series
interval evidence. Candle presence and ticker similarity are not sufficient.

## CLI

```bash
poetry run python -m alpha historical-truth \
  final-official-evidence-closure-certify \
  --database <HISTORICAL_TRUTH_DUCKDB> \
  --htr009a2-output <SIGNED_HTR009A2> \
  --htr010a3-output <SIGNED_HTR010A3> \
  --htr010b-output <FINAL_HTR010B> \
  --final-b1c-output <FINAL_B1C> \
  --final-b1e2-output <FINAL_B1E2> \
  --baseline-b4-output <SIGNED_B4> \
  --start 2005-01-01 \
  --end 2015-12-31 \
  --output <OUTPUT>
```

The command emits deterministic JSON, CSV, Markdown and DuckDB artifacts,
including the 66-case before/after ledger, all remaining identity segments,
factor lineage, official source manifest and readiness certificate.

## Readiness

```text
READINESS=BLOCKED_BY_UNCERTIFIED_PRE_EVENT_IDENTITY_HISTORY
FULL_BENCHMARK_REPLAYS=0
STOP_POLICY_AUTOMATIC_PROMOTION_ENABLED=false
ADJUSTED_REPLAY_READY=false
PRODUCTION_INFLUENCE=false
```

No recommendation, strategy, stop, approval, portfolio, execution, learning or
production behaviour changed.
