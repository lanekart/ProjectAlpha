# Alpha Canonical Universe Opportunity Audit (ACU-1)

## Purpose

ACU-1 is a research-only diagnostic that measures how often the current Alpha
engine finds opportunities, where candidates are rejected, how correlated the
surviving ideas are, and whether the legacy market population can support the
resulting capacity conclusions.

The audited engine is frozen as `ALPHA_CANONICAL_v1.0`. ACU does not alter any
weight, threshold, approval rule, strategy, entry condition, stop, exit, trade
plan, learning model, adaptive-weight policy, or portfolio policy.

`PRODUCTION_INFLUENCE=false`.

## Evidence Boundary

The current source is `data/ingestion.duckdb`. Every output is labelled:

- `PROVISIONAL`
- `NOT AUTHORITATIVE`
- `LEGACY_DATASET`

The warehouse currently contains NSE daily OHLCV. Industry, theme, market-cap,
free-float, and historical sector classification are unavailable. ACU records
those fields as unavailable and does not infer them.

## Canonical Execution

For each trading day, ACU runs the current pipeline in point-in-time order:

1. Load the valid daily universe from the read-only legacy store.
2. Run `DailyMarketReport` unchanged.
3. Rank the complete universe with the current quality rank.
4. Retain the current top ten technical candidates.
5. Load the live runtime's 250-bar history window for those same ten symbols.
6. Run `RecommendationEngine`, portfolio construction, and explainability.
7. Run the current `InstitutionalDecisionEngine` and trade-plan optimizer.
8. Record the complete funnel and typed rejection reasons.

If the unchanged canonical pipeline rejects its own values or otherwise raises a
deterministic calculation error, ACU records the day as `FAILED_CLOSED`, assigns
`CANONICAL_RUNTIME_ERROR` to the affected technical candidates, and infers no
scores, approvals, allocations, or outcomes. This is audit evidence, not a
production repair.

The ACU input adapter repeats only the pre-ranking needed to avoid reading 250
bars for every listed symbol. A parity regression proves it selects the same ten
candidates and produces the same candidate inputs as the canonical builder.

## Funnel Definitions

- **Universe Size**: valid daily OHLCV rows.
- **Eligible Securities**: at least 200 prior/current valid bars, matching the
  existing complete 200-DMA requirement.
- **Technical Candidates**: current top-ten canonical candidate rank.
- **Approval Candidates**: final signal `BUY` or `STRONG_BUY`.
- **Institutional Approvals**: accepted by the current institutional decision
  layer after stress and trade-plan checks.
- **Portfolio Eligible**: institutional approval with positive current portfolio
  allocation output.

These definitions are stored in every JSON report and must not be compared with
metrics that use a different population or approval definition.

The JSON and executive summary include daily, ISO-weekly, monthly, and yearly
opportunity frequency; opportunity-day clusters; average and median trades per
symbol across the full legacy universe; and per-symbol annual and
decade-normalized candidate, approval, and actual portfolio-eligible trade rates.

## Outcomes

Approval-candidate trade plans are evaluated from future OHLCV using the
recorded entry, stop, targets, and holding period. The existing Strategy Lab
simulation assumptions are used, including explicit costs and conservative
stop-first ordering when stop and target are touched in one bar. Incomplete
future windows remain pending and are never treated as completed evidence.

## Correlation And Capacity

Simultaneous approvals are grouped with the current portfolio correlation limit
of `0.75`. The independent count is the number of connected correlation groups,
not the raw number of symbols.

Liquidity capacity follows the current capacity convention: the lesser of the
requested capital and 1% of legacy average daily traded value. All such values
are labelled `APPROXIMATE / LEGACY DATA`. Missing free float and live spread
prevent an institutional capacity claim.

The INR 1 crore utilisation view is a diagnostic estimate capped at 10% per
position and does not allocate capital.

## Commands

```text
poetry run python -m alpha acu run
poetry run python -m alpha acu opportunities
poetry run python -m alpha acu sectors
poetry run python -m alpha acu gates
poetry run python -m alpha acu liquidity
poetry run python -m alpha acu capacity
poetry run python -m alpha acu report
```

`acu run` supports `--database`, `--output`, `--start`, `--end`, and an optional
`--research-registry` override. Date-bounded runs are useful for deterministic
smoke tests; the production audit artifact is the complete available legacy
range.

## Artifacts

The audit writes:

- `opportunity_capacity.json`
- `opportunity_capacity.csv`
- `gate_attribution.csv`
- `sector_opportunities.csv`
- `daily_opportunities.csv`
- `monthly_summary.csv`
- `candidate_rankings.csv`
- `liquidity_capacity.csv`
- `symbol_statistics.csv`
- `executive_report.md`

It also writes `trl_validation_bridge.json`, a non-executing reference manifest
for future matched TradingView Research Laboratory validation. It does not claim
that a TRL validation has occurred.

## Research Governance

Every completed audit is idempotently recorded in the permanent Research
Registry. ACU exposes the standard IRD diagnostic plugin interface, allowing IRD
to use opportunity frequency and approval bottleneck evidence without a core
change. The audit remains observational and never updates Alpha learning or
adaptive weights.
