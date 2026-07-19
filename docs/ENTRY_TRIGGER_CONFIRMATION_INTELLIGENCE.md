# Entry Trigger Confirmation Intelligence

Entry Trigger Confirmation Intelligence is a diagnostic, research-only layer. It
does not modify production recommendations, timing states, component weights,
allocation, trade plans, live data, provider code, or execution.

## Frozen Baseline

The frozen baseline is `FULL_STACK_PLUS_TIMING`, inherited from Opportunity
Evolution Intelligence. It is evaluated once per opportunity, not once per
observation, and remains the reference for all confirmation experiments.

## Failure Attribution

Failed baseline triggers are classified into typed causes such as:

- `FALSE_BREAKOUT`
- `INSUFFICIENT_VOLUME_CONFIRMATION`
- `WEAK_RELATIVE_STRENGTH`
- `HOSTILE_MARKET_REGIME`
- `RETEST_FAILED`
- `STOP_TOO_TIGHT`
- `STOP_TOO_WIDE`
- `OPPORTUNITY_GROUPING_ERROR`
- `INHERENT_MARKET_UNCERTAINTY`

Each failure also receives a preventability class:

- `PREVENTABLE_WITH_EXISTING_EVIDENCE`
- `PREVENTABLE_WITH_NEW_POINT_IN_TIME_FEATURE`
- `STOP_OR_TRADE_PLAN_PRIMARY`
- `OPPORTUNITY_GROUPING_PRIMARY`
- `LABEL_OR_OUTCOME_AMBIGUITY`
- `NOT_REASONABLY_PREVENTABLE`
- `INSUFFICIENT_EVIDENCE`

The distinction matters: Alpha should not treat every failed trade as a bad
directional call. Some failures are direction errors, some are entry timing
errors, some are stop design errors, and some are simply not avoidable with the
available data.

## Confirmation Feature Lineage

The research scores are kept separate:

- `OPPORTUNITY_QUALITY_SCORE`
- `ENTRY_TRIGGER_SCORE`
- `PARTICIPATION_CONFIRMATION_SCORE`
- `BREAKOUT_CONFIRMATION_SCORE`
- `RETEST_QUALITY_SCORE`
- `RISK_CONFIRMATION_SCORE`
- `CONFIRMED_ENTRY_SCORE`

Each score reports lineage and overlap with existing evidence. The composite
`CONFIRMED_ENTRY_SCORE` is diagnostic only and does not feed production scoring.

## Participation Proxies

The research concept is `PARTICIPATION_CONFIRMATION`, not direct institutional
buying. The current proxies use only replay-available fields such as relative
volume, liquidity, relative strength, and price-volume sequences.

No report should claim institutional buying unless direct point-in-time
institutional-flow data is available.

## Retest Model

Retest states are typed:

- `NO_RETEST`
- `RETEST_FORMING`
- `CONTROLLED_RETEST`
- `SUPPORT_HOLD_CONFIRMED`
- `DEEP_RETEST`
- `FAILED_RETEST`
- `RETEST_UNAVAILABLE`

The goal is to compare immediate breakout entries against controlled retest and
support-hold triggers without using future data.

## Persistence And Cancellation

Persistence asks whether the setup remains valid for more than one observation.
Cancellation asks whether a qualified trigger deteriorates before the next
confirmation point. Cancellation reasons include loss of price confirmation,
volume confirmation, support, relative strength, regime support, or trade-plan
quality.

This is a simulated diagnostic, not real execution behavior.

## Methodology

The engine keeps opportunity-level evaluation as the primary metric:

- one primary trigger per opportunity
- point-in-time evidence only
- confidence intervals
- effective sample size
- fold best/worst/dispersion
- concentration by year, setup, symbol, sector, and regime
- precision, coverage, delay, missed move, expectancy, MAE, and MFE shown
together

## CLI Commands

```bash
poetry run python -m alpha replay confirmation-intelligence
poetry run python -m alpha replay trigger-failure-attribution
poetry run python -m alpha replay participation-confirmation
poetry run python -m alpha replay false-breakout-audit
poetry run python -m alpha replay retest-quality-audit
poetry run python -m alpha replay trigger-persistence-audit
poetry run python -m alpha replay trigger-cancellation-audit
poetry run python -m alpha replay confirmation-frontier
```

All commands support:

```bash
--format text
--format json --output report.json
--format csv --output records.csv
--group-by failure-cause
--group-by preventability
--group-by setup
--group-by regime
--group-by confirmation
--group-by trigger
--group-by year
--group-by horizon
--symbol SYMBOL
--opportunity-id ID
```

## Production Isolation

Every report prints `PRODUCTION_INFLUENCE=false`. Promotion of any confirmation
rule into production requires a separate milestone with explicit policy review,
sufficient sample size, stable outer-fold evidence, and concentration controls.

## Known Limitations

The current diagnostic uses replay-available proxies. It cannot validate direct
institutional participation, delivery activity, order-flow behavior, or corporate
event shocks unless those fields are later ingested point-in-time.
