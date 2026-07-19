# Walk-Forward Strategy Discovery and Generalisation

## Purpose

The strategy-discovery subsystem asks one narrow research question: can a simple,
auditable Alpha strategy retain positive expectancy after costs on chronological
unseen evidence? It does not change recommendations, approvals, allocation, broker
orders, or `APPROVAL_POLICY_V1`.

`PRODUCTION_INFLUENCE=false` is enforced in discovery datasets, strategy
specifications, research records, reports, and shadow publications.

## Architecture

The package `alpha/strategy_discovery/` is an isolated research pipeline:

1. `historical_signal_generator.py` converts the candidate ledger into separate
   authoritative and reconstructed point-in-time populations.
2. `feature_manifest.py` is the only feature allow-list. Future outcomes,
   unresolved retracement calibration, invalid market-regime labels, and unavailable
   historical sector membership are quarantined.
3. `strategy_family_registry.py` and `candidate_strategy_generator.py` generate a
   bounded, deterministic set of interpretable strategies.
4. `walk_forward_engine.py` creates chronological train, validation, and untouched
   holdout partitions with an explicit purge gap and expanding folds.
5. `strategy_evaluator.py` evaluates expectancy after configured costs alongside
   precision, recall, payoff, drawdown, risk-adjusted returns, utilization,
   concentration, turnover, and holding period.
6. `robustness_engine.py`, `parameter_stability.py`, and
   `multiple_testing_control.py` test sensitivity, concentration, bootstrap
   uncertainty, higher costs, missed fills, and multiplicity.
7. `strategy_registry.py` records every search, failed strategy, leaderboard, and
   holdout access. It exports deterministic JSON and CSV.
8. `shadow_candidate_publisher.py` fails closed. A passing strategy is written only
   to the isolated strategy shadow-cohort registry and cannot allocate capital.
9. `research_integration.py` records the experiment in the permanent Research
   Registry and exposes evidence to the Institutional Research Director (IRD).

## Historical Truth

Authoritative and reconstructed rows are never mixed. A row is authoritative only
when its frozen decision provenance and market-state snapshot are linked. If the
authoritative population is too small for the declared minimum evidence assumption,
the engine may evaluate the separately labelled reconstructed population for
diagnosis, but every such candidate is classified `INVALID_DATA` and cannot be
published.

Outcome fields such as realised return, MFE, and MAE are evaluation labels only.
They are never exposed to candidate signal conditions.

## Search and Validation

Initial strategy families are score thresholds, price structure, price plus volume,
setup type, entry timing, trade-plan quality, signal subsets, approval-gate subsets,
small conjunctions, frozen `APPROVAL_POLICY_V1`, raw approvals, and no trade.
Unconstrained black-box search is deliberately excluded.

The default split reserves 20 percent for validation and 20 percent for holdout.
The holdout is accessible only to the final shortlist and its access record is
immutable per dataset. Re-running the same final evaluation is idempotent; changing
the shortlist after access is rejected.

The default cost and evidence constraints are explicit versioned research
assumptions, not production thresholds. They include 20 bps transaction cost,
10 bps slippage, minimum trade and fold counts, positive-fold requirements,
drawdown, winner-concentration, and degradation limits.

## Generalisation Decision

Every strategy receives exactly one classification:

- `INVALID_DATA`
- `LEAKAGE_RISK`
- `INSUFFICIENT_SAMPLE`
- `OVERFIT`
- `UNSTABLE`
- `NEGATIVE_EXPECTANCY`
- `NO_MATERIAL_EDGE`
- `ROBUST_BUT_LOW_CAPACITY`
- `SHADOW_VALIDATION_CANDIDATE`

The final report returns exactly `NO_GENERALISABLE_STRATEGY_FOUND` or
`PUBLISH_<STRATEGY_VERSION>_TO_SHADOW_VALIDATION`. Standards are not relaxed to
force a candidate.

## Commands

```text
poetry run python -m alpha strategy discover
poetry run python -m alpha strategy walk-forward
poetry run python -m alpha strategy evaluate
poetry run python -m alpha strategy robustness
poetry run python -m alpha strategy leaderboard
poetry run python -m alpha strategy publish-shadow-candidate
poetry run python -m alpha strategy discovery-report
```

Commands that write the strategy registry accept `--export-json` and
`--export-csv`. Registry paths can be isolated with `--registry`,
`--research-registry`, and `--shadow-registry`.

## Shadow Isolation

The publisher never edits the recommendation engine, approval engine, allocation
engine, current forward policy, existing forward snapshots, or broker APIs. A shadow
artifact retains the immutable strategy hash, source dataset version,
recommendation-engine version, and a separate strategy cohort version such as
`FORWARD_STRATEGY_V2_SHADOW`.

Historical discovery performance is research evidence. It is never reported as
measured forward ROI. Existing `APPROVAL_POLICY_V1` forward observations continue in
their original cohort without interruption.
