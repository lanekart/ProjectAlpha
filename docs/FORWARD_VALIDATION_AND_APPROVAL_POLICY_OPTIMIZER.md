# Forward Validation and Institutional Approval Policy Optimizer

## Purpose

Project Alpha's forward-validation subsystem records what Alpha knew and
recommended at generation time, then evaluates later market outcomes without
replaying or rewriting the recommendation. The approval-policy optimizer uses
historical candidate outcomes to generate diagnostic policy candidates. Neither
subsystem can change production trading behavior.

`PRODUCTION_INFLUENCE=false`

## Architecture

The package is under `alpha/forward_validation/`:

- `models.py`: immutable snapshots, events, policy stages, portfolio values,
  performance metrics, and optimization reports.
- `recommendation_snapshot.py`: freezes runtime recommendations, diagnostics,
  versions, and evidence hashes.
- `validation_registry.py`: append-only JSON registry, snapshot integrity
  validation, event hash chaining, atomic writes, and JSON/CSV export.
- `position_tracker.py`: deterministic entry, stop, target, trailing-stop,
  invalidation, missed-entry, and time-exit events.
- `shadow_portfolio.py`: cash and position accounting isolated by policy cohort.
- `performance_tracker.py`: realized performance and portfolio statistics.
- `approval_gate_optimizer.py`: exact V1 gate survival and marginal metrics.
- `counterfactual_engine.py`: remove, relax, tighten, reorder, merge, and replace
  experiments.
- `approval_policy_optimizer.py`: stop-distance diagnostics, chronological
  staged validation, candidate ranking, and one unambiguous recommendation.
- `policy_versioning.py`: immutable candidate registration and monotonic stage
  transitions.
- `forward_validation_engine.py`: application orchestration.
- `rendering.py`: concise operator output.

## Evidence Contract

Every snapshot freezes the generation timestamp, symbol, current price,
verdict, score, confidence, entry plan, stop, targets, holding period,
reward/risk, regime, sector, engine version, data version, policy version,
allocation approved at generation, diagnostics, per-evidence hashes, and an
overall snapshot hash.

Snapshots cannot be updated. An identical insert is idempotent; a conflicting
insert or a hash mismatch fails. Position changes are new hash-chained events.
Registry writes are atomic. JSON and CSV exports are deterministic.

Normal `alpha run` and `alpha intelligence` commands freeze recommendations at
the CLI application boundary after generation. This wiring does not call or
modify recommendation, approval, allocation, learning, replay, or trading
engines.

## Execution Semantics

- Only frozen `BUY` or `STRONG_BUY` recommendations with positive approved
  deployment, a stop, and at least one target can enter the shadow portfolio.
- A trigger already confirmed at generation uses the frozen market price.
- `CLOSE_ABOVE` fills at the confirming close. `CROSS_ABOVE` fills at the frozen
  trigger. Zone, pullback, and retest entries require bar-range intersection.
- A volume breakout is not inferred from unavailable historical volume. It
  remains pending unless the required confirmation was frozen.
- If a stop and target occur in the same bar, the stop is processed first.
- Target 1 and Target 2 are recorded as touches. The highest configured frozen
  target closes the position because no partial-exit quantity is invented.
- A `2 x ATR` trailing stop is evaluated only when both the frozen ATR and the
  frozen trailing rule exist, and only after Target 1.
- Future bars come from Alpha's persisted price store. The forward engine does
  not download, replay, or recompute the original recommendation.

## Portfolio and Metrics

Every policy has an isolated virtual-capital cohort. Cash, quantities, marks,
realized and unrealized profit/loss, utilization, portfolio value, and drawdown
are reconstructed from immutable events.

Metrics include approval precision, win rate, average winner and loser, profit
factor, expectancy, holding period, maximum drawdown, win/loss streaks,
utilization, CAGR, Sharpe, and Sortino. A metric is `unavailable` when its actual
denominator or observation history is insufficient. No value is imputed.

Risk controls are optional and include maximum positions, position allocation,
sector allocation, daily loss, and portfolio drawdown. They affect only the
shadow portfolio. An exceeded control rejects the virtual entry rather than
resizing it silently.

## Approval Optimization

V1 is reconstructed from the existing candidate-learning policy:

1. Raw deployment approval.
2. BUY or STRONG_BUY verdict.
3. HIGH confidence.
4. COMPLETE or GOOD data.
5. Strategy score at least 85.
6. Complete trade plan.
7. Entry price at least 50 when present.
8. Stop distance at most 10 percent.
9. Reward/risk at least 2.

Each gate reports entering, passing, rejected, cumulative survival, profitable
rejections, accepted/rejected average returns, precision, recall, profit factor,
expectancy, drawdown, utilization impact, and observed redundancy.

Numeric relaxations and tightenings use only the nearest value already observed
in the ledger. This prevents the optimizer from inventing threshold grids.
Reordering and equivalent merging are tested to expose attribution-only effects.
ATR replacement is rejected when comparable frozen ATR evidence is absent.

## Overfitting Protection

Records are ordered by point-in-time evaluation date and divided into 60 percent
training, 20 percent validation, and 20 percent hold-out partitions. A candidate
must approve resolved observations and weakly dominate V1 on precision,
expectancy, and drawdown in every partition. Failure stops progression.

The stages are:

`GENERATED -> TRAINING_PASSED -> VALIDATION_PASSED -> HOLDOUT_PASSED -> FORWARD_VALIDATION`

The diagnostic registry cannot activate a policy or mark it production-ready.
A hold-out survivor may only receive `APPROVAL_POLICY_V2` or
`APPROVAL_POLICY_V3` and enter frozen forward validation. Forward cohorts are
never combined.

## Deployment Readiness

Readiness is evidence-only:

- `NOT_READY`: no immutable forward recommendations.
- `FORWARD_VALIDATION`: immutable collection has started.
- `LIMITED_CAPITAL` and `PRODUCTION_READY`: unavailable until a separately
  governed promotion contract is approved and implemented.

The subsystem deliberately does not invent sample-size or capital-readiness
thresholds.

## Commands

```text
poetry run python -m alpha forward start
poetry run python -m alpha forward snapshot
poetry run python -m alpha forward portfolio
poetry run python -m alpha forward performance
poetry run python -m alpha forward journal
poetry run python -m alpha forward approval-policy
poetry run python -m alpha forward approval-optimizer
poetry run python -m alpha forward approval-counterfactual
poetry run python -m alpha forward deployment-readiness
```

Use `--registry` to isolate a forward registry. `snapshot` and `journal` support
`--export-json` and `--export-csv-dir`. `start` accepts virtual-capital risk
controls. `snapshot` defaults to normal live mode; `--demo` is explicit.

## Constraints and Known Limits

- No broker integration and no order placement.
- No recommendation recalculation after generation.
- No transaction-cost or slippage estimate is invented. Fill conventions are
  explicit and should be extended only with frozen executable-price evidence.
- Daily-loss controls are stored but require intraday/equity-session evidence
  before enforcement; they must not be approximated from unrelated data.
- Candidate policy forward capture needs an explicit, isolated candidate-policy
  runtime before V2/V3 can accumulate a cohort. Production remains V1.
- Promotion criteria for limited or production capital remain a governance
  decision and are intentionally absent from this milestone.
