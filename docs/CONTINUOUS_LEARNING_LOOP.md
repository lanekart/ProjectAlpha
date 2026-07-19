# Closed Learning Loop

## Purpose

The Closed Learning Loop (CLL) converts every frozen Alpha recommendation into
permanent diagnostic evidence. It compares the frozen prediction with later market
reality, measures where prediction quality changes, and recommends research.

CLL cannot alter recommendation confidence, strategy state, approval policy,
allocation, trading logic, or execution. `PRODUCTION_INFLUENCE=false` is enforced in
its models, registry, research recommendations, CLI reports, and IRD adapter.

## Evidence Flow

1. `OutcomeCollector` reads the recommendation performance ledger and immutable
   forward-validation snapshots/events.
2. It normalizes entry, exit, stop, targets, MFE, MAE, return, holding period,
   regime, sector, volatility, and liquidity without filling missing values.
3. `ContinuousLearningRegistry` appends immutable outcome observations. A later
   state transition creates a new observation; it never overwrites the old one.
4. `PredictionTracker` compares expected direction, confidence, timing, and exit
   quality with the resolved outcome.
5. `StrategyHealthMonitor` aggregates evidence by setup type.
6. `ConceptDriftEngine` compares earlier and recent completed outcomes.
7. `FeatureDriftEngine` measures score, volatility, and sector-population shifts.
8. `ConfidenceCalibrationEngine` produces reliability buckets, Brier score, and
   expected calibration error.
9. `ResearchTriggerEngine` creates evidence-linked research recommendations.
10. The IRD plugin exposes the latest continuous evidence beside historical
    diagnostics without treating it as measured deployment ROI.

## Missing Evidence

Pending recommendations are never counted as wins or losses. Missing sector,
volatility, liquidity, MFE, MAE, or returns stay unavailable. Sector drift is
`UNKNOWN` unless both chronological segments have at least ten classified rows.
Calibration can calculate descriptive values from a tiny sample, but its status
remains `INSUFFICIENT_EVIDENCE` until at least twenty resolved predictions exist.

The registry permanently retains historical observations even when their upstream
source is later unavailable. Such observations are reported as quarantined and remain
auditable, but they are excluded from prediction, strategy-health, drift, calibration,
and IRD analytical populations until current source provenance is restored.

## Strategy Health

Health classifications are advisory:

- `HEALTHY`
- `WATCH`
- `DEGRADING`
- `RESEARCH_REQUIRED`
- `RETIRE`

`RETIRE` is a research finding, not an action. The monitor cannot disable or promote
a strategy. Recall is unavailable because the recommendation ledger does not contain
every market opportunity.

The versioned thresholds in `LearningThresholds` are explicit research assumptions.
They do not modify Alpha's existing adaptive-learning or production thresholds.

## Drift

Outcome drift evaluates precision, expectancy, and entry timing. Feature drift
evaluates recommendation-score means, volatility means, and sector distribution.
Every result is one of `NO_DRIFT`, `EARLY_DRIFT`, `SIGNIFICANT_DRIFT`, or `UNKNOWN`,
with population counts and evidence confidence.

## Confidence Calibration

The initial transparent diagnostic mapping is HIGH = 0.80, MEDIUM = 0.60, and
LOW = 0.40. This mapping exists solely to measure reliability. It does not claim
that Alpha's labels are calibrated probabilities and cannot rewrite production
confidence.

## Registry

The default registry is `.alpha/continuous_learning/registry.json`. It contains
append-only outcome observations and learning events. Stable hashes make repeated
collection idempotent. An existing identity with different evidence is rejected.

JSON and CSV exports are available from `learning collect`:

```text
--export-json PATH
--export-csv PATH
```

## Commands

```text
poetry run python -m alpha learning collect
poetry run python -m alpha learning outcomes
poetry run python -m alpha learning drift
poetry run python -m alpha learning strategy-health
poetry run python -m alpha learning calibration
poetry run python -m alpha learning recommendations
poetry run python -m alpha learning report
```

`learning report` begins with the executive CLL report and retains Alpha's existing
historical adaptive-learning report beneath it for compatibility.

## Operational Interpretation

CLL evidence is not paper trading, not backtesting, and not capital-deployment
approval. Historical, reconstructed, pending, and genuinely resolved forward evidence
remain distinct. IRD may prioritize research from CLL findings, but production
behavior remains unchanged.
