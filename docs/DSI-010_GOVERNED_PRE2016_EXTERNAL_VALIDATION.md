# DSI-010 — Governed Pre-2016 External-Era Validation

## Purpose

DSI-010 evaluates whether the DSI-009 descriptive stop challenger
`STOP-STRUCTURAL-10D` generalises to an earlier Indian-market era without using
that era to tune the rule.

The protocol is frozen to:

```text
2005-01-01 through 2015-12-31
```

No 2016 observation is admissible because DSI-007 strategy research begins in
2016.

## Two separate tests

### Frozen-policy transport

The latest signed DSI-007 regime-to-strategy mapping is transported unchanged
to the earlier era. The incumbent and challenger receive the same:

- point-in-time market state;
- strategy signal;
- next-session-open entry;
- targets;
- trailing and time exits;
- position sizing;
- liquidity and capacity limits;
- transaction costs and slippage.

Only the initial stop differs. The challenger uses the point-in-time ten-session
structural support recorded as `support10`; when that value is unavailable it
falls back to the incumbent stop. Future lows or recoveries never choose the
stop.

A feature warm-up and portfolio warm-up period are retained. The actual
transport test therefore begins only after at least 504 governed sessions and
is reported explicitly rather than pretending the full 2005 period was
tradable.

### Independent-era walk-forward replication

The existing bounded DSI-007 strategy grammar is independently trained,
validated, frozen, and tested inside 2005–2015. Its results remain separate from
the frozen-policy transport test because the evidence populations answer
different questions.

## Data preparation

Download and ingest the official NSE archive range:

```bash
poetry run python -m alpha benchmark \
  decision-superiority-pre2016-archive-backfill \
  --start 2005-01-01 \
  --end 2015-12-31
```

The backfill command uses Alpha's existing official NSE archive provider and
canonical ingestion service. Downloaded archives, local databases, and bulk
market files must not be committed to GitHub.

The external validation engine consumes the governed Historical Truth warehouse,
not an ungoverned CSV collection. Before the run, the warehouse must contain the
same certified table contracts required by DSI-007:

- `adjusted_daily_candle`;
- `adjusted_candle_lineage`;
- `security_isin_interval_complete`;
- `security_membership_interval_complete`;
- `corporate_action_event`;
- `price_basis_interval`.

Missing identity, membership, corporate-action, or backward-adjustment evidence
fails closed or remains an explicit partial-coverage limitation.

## Benchmark

Supply a governed total-return-index CSV with a date column and one of:

- `total_return_index`;
- `tri`;
- `value`.

Nifty 500 TRI is the primary benchmark. A price index must not be relabelled as
a total-return index.

## Run

```bash
poetry run python -m alpha benchmark \
  decision-superiority-pre2016-external-validation \
  --dsi009-certificate <DSI009_CERTIFICATE> \
  --dsi007-certificate <DSI007_CERTIFICATE> \
  --database alpha_data/warehouse/historical_truth.duckdb \
  --historical-truth-snapshots alpha_data/snapshots \
  --benchmark <NIFTY_500_TRI_CSV> \
  --output artifacts/dsi010_pre2016_external_validation
```

## Verify

```bash
poetry run python -m alpha benchmark \
  decision-superiority-pre2016-external-validation-verify \
  --certificate artifacts/dsi010_pre2016_external_validation/\
dsi010_pre2016_external_certificate.json \
  --require-ready
```

The certificate binds the frozen protocol, challenger identity, source lineage,
all deterministic support artifacts, readiness decisions, benchmark-relative
performance, concentration, robustness, and governance flags.

## Interpretation

The external-era result may:

- beat both incumbent and benchmark;
- beat the incumbent but remain below the benchmark;
- provide mixed directional support;
- fail because of concentration, insufficient sample, or underperformance.

A negative result is retained. DSI-010 cannot alter the challenger after viewing
2005–2015 results and cannot reuse this era as a new optimisation population.

## Governance

```text
STOP_POLICY_AUTOMATIC_PROMOTION_ENABLED=false
LIVE_STOP_POLICY_ENABLED=false
LIVE_STRATEGY_SELECTION_ENABLED=false
LIVE_SCORING_ENABLED=false
PRODUCTION_SIGNAL_PUBLICATION_ENABLED=false
PRODUCTION_PORTFOLIO_INFLUENCE=false
THRESHOLD_CHANGE_PERMITTED=false
PORTFOLIO_POLICY_CHANGE_PERMITTED=false
EXECUTION_POLICY_CHANGE_PERMITTED=false
SYNTHETIC_MARKET_DATA_PERMITTED=false
SYNTHETIC_TRADES_PERMITTED=false
SYNTHETIC_OUTCOMES_PERMITTED=false
ECONOMIC_SUPERIORITY_CLAIMED=false
CAUSAL_CLAIM_PERMITTED=false
DEFAULT_RUNTIME_BEHAVIOUR_CHANGED=false
RECOMMENDATION_INFLUENCE=false
PORTFOLIO_POLICY_INFLUENCE=false
EXECUTION_INFLUENCE=false
LEARNING_MUTATION_ENABLED=false
ACTIVE_REPLAY_INTEGRATION=false
PRODUCTION_INFLUENCE=false
```

A ready DSI-010 certificate permits, at most, continued forward paper research.
It does not activate any live or production mechanism.
