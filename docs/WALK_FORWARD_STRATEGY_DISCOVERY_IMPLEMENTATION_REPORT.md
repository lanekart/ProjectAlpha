# Walk-Forward Strategy Discovery Implementation Report

## 1. Implementation

Project Alpha now has a diagnostic-only, bounded walk-forward strategy discovery
engine under `alpha/strategy_discovery/`. It materializes point-in-time evidence,
quarantines invalid features, generates immutable strategy specifications, evaluates
chronological folds after explicit costs, controls holdout access, performs
robustness and multiplicity checks, records all trials, integrates with IRD, and
fails closed at shadow publication.

Files added or updated for this milestone:

- `alpha/strategy_discovery/__init__.py`
- `alpha/strategy_discovery/models.py`
- `alpha/strategy_discovery/feature_manifest.py`
- `alpha/strategy_discovery/historical_signal_generator.py`
- `alpha/strategy_discovery/strategy_family_registry.py`
- `alpha/strategy_discovery/candidate_strategy_generator.py`
- `alpha/strategy_discovery/walk_forward_engine.py`
- `alpha/strategy_discovery/strategy_evaluator.py`
- `alpha/strategy_discovery/robustness_engine.py`
- `alpha/strategy_discovery/multiple_testing_control.py`
- `alpha/strategy_discovery/parameter_stability.py`
- `alpha/strategy_discovery/strategy_registry.py`
- `alpha/strategy_discovery/shadow_candidate_publisher.py`
- `alpha/strategy_discovery/discovery_service.py`
- `alpha/strategy_discovery/research_integration.py`
- `alpha/strategy_discovery/rendering.py`
- `alpha/application/strategy_discovery_cli.py`
- `alpha/cli.py`
- `alpha/research/models.py`
- `alpha/research/diagnostic_registry.py`
- `tests/strategy_discovery/test_strategy_discovery_core.py`
- `tests/strategy_discovery/test_strategy_discovery_integration.py`
- `tests/research/test_institutional_research_director.py`
- `docs/WALK_FORWARD_STRATEGY_DISCOVERY.md`

## 2. Tests

Sixteen strategy-discovery tests cover temporal enforcement, leakage quarantine,
bounded deterministic generation, strategy hashes and versions, purge gaps,
holdout access control, costs, expectancy, drawdown, profit factor, Wilson intervals,
perturbation, ablation, concentration, multiple testing, minimum evidence, overfit
classification, fail-closed publication, JSON/CSV exports, CLI registration, IRD
registration, research persistence, and production-policy isolation.

## 3. Empirical Result

- Ledger candidates: 1,546
- Discovery rows with resolved outcomes: 1,500
- Exclusions: 46
- Authoritative completed rows: 0
- Evaluated population: 1,500 separately labelled reconstructed rows
- Strategies tested: 61 across 12 declared families
- Chronological folds: 3 with a 20-day purge gap
- Holdout strategies evaluated: 0; no strategy passed pre-holdout shortlist gates
- Final decision: `NO_GENERALISABLE_STRATEGY_FOUND`

The leading reconstructed diagnostic was score at least 85, with 7 validation
trades and 6.20% mean return after the configured 0.30% round-trip cost. It is not
valid evidence for publication: the sample is small, perturbation and ablation fail,
the bootstrap lower bound is not positive, profits are concentrated, and the source
population is reconstructed.

The raw recorded approval benchmark had 5 validation trades and -4.92% expectancy.
The strict `APPROVAL_POLICY_V1` benchmark selected zero validation trades. A broad
market comparison is unavailable because no valid point-in-time benchmark-return
series is aligned to candidate outcomes.

## 4. Feature Governance

Usable features are strategy score, verdict, raw approval, confidence, data quality,
setup, entry timing, long permission, complete plan, entry price, stop distance,
reward/risk, price, volume, and candle components.

Quarantined features are retracement calibration, invalid market-regime labels,
unavailable historical sector membership, realised return, MFE, and MAE. Outcome
fields remain evaluation labels and cannot enter strategy conditions.

## 5. Research Governance and IRD

The Research Registry contains experiment
`strategy-discovery-b2675ee4b8a15adb87db`, classified `COMPLETED / REJECT` with
`LOW` statistical confidence. IRD now registers
`strategy-discovery-generalisation` as its ninth diagnostic. Its roadmap records the
authoritative identity and corporate-action evidence dependency at P2. No historical
or in-sample metric is presented as measured forward ROI.

## 6. Isolation

`APPROVAL_POLICY_V1`, recommendation logic, approval gates, allocation, live market
data, broker APIs, existing forward snapshots, and existing policy cohorts were not
changed. The shadow publication registry is separate, immutable, capital-disabled,
and broker-disabled. No shadow candidate file was created because no strategy
qualified.

## 7. Complete CLI Transcripts

### `alpha strategy discover`

```text
Strategy Discovery
Dataset: strategy-discovery-v1-reconstructed-ea5acfc503940ed1
Historical Truth: RECONSTRUCTED
Included Rows: 1500
Excluded Rows: 46
Strategies Generated: 61
Search-Space Hash: f975755b6eae2565073dde37749cb2e4f3c76da61d08df2e7c0c194ad6850d8b
Feature Manifest:
- strategy_score: USABLE
- final_verdict: USABLE
- raw_approved: USABLE
- confidence: USABLE
- data_quality: USABLE
- setup_type: USABLE
- entry_timing_state: USABLE
- long_trade_permission: USABLE
- complete_trade_plan: USABLE
- entry_price: USABLE
- stop_distance_pct: USABLE
- reward_risk: USABLE
- price_component: USABLE
- volume_component: USABLE
- candle_component: USABLE
- retracement_component: QUARANTINED
- market_regime: QUARANTINED
- sector: QUARANTINED
- realised_return_pct: QUARANTINED
- mfe_pct: QUARANTINED
- mae_pct: QUARANTINED
Quarantined Features:
- retracement_component: Previously inversely predictive; calibration direction is unresolved.
- market_regime: Reference-label scale defect invalidates predictive-quality evidence.
- sector: Authoritative point-in-time historical sector membership is unavailable.
- realised_return_pct: Future-derived outcome fields cannot be discovery features.
- mfe_pct: Future-derived outcome fields cannot be discovery features.
- mae_pct: Future-derived outcome fields cannot be discovery features.
Strategy Families:
- APPROVAL_GATE_SUBSET: 6 variants
- APPROVAL_POLICY_V1: 1 variants
- ENTRY_TIMING: 3 variants
- NO_TRADE: 1 variants
- PRICE_STRUCTURE: 3 variants
- PRICE_VOLUME: 4 variants
- RAW_RECORDED_APPROVAL: 1 variants
- SCORE_THRESHOLD: 7 variants
- SETUP_SPECIFIC: 4 variants
- SIGNAL_COMPONENT_SUBSET: 3 variants
- SIMPLE_CONJUNCTION: 25 variants
- TRADE_PLAN_QUALITY: 3 variants
PRODUCTION_INFLUENCE=false
```

### `alpha strategy walk-forward`

```text
Chronological Walk-Forward Validation
Dataset: strategy-discovery-v1-reconstructed-ea5acfc503940ed1
Historical Truth: RECONSTRUCTED
Walk-Forward Folds: 3
- WF-1: train 2016-07-11 to 2016-09-23; validate 2016-10-14 to 2016-12-21; purge 20 days
- WF-2: train 2016-07-11 to 2016-10-21; validate 2016-12-22 to 2020-01-01; purge 20 days
- WF-3: train 2016-07-11 to 2020-01-01; validate 2020-04-01 to 2022-10-03; purge 20 days
Validation Leaders Before Holdout:
- STRATEGY_RESEARCH_V020 SCORE_THRESHOLD 6: trades=7; expectancy=6.20%; profit factor=2.76
- STRATEGY_RESEARCH_V002 APPROVAL_GATE_SUBSET 6: trades=2; expectancy=5.83%; profit factor=unavailable
- STRATEGY_RESEARCH_V043 SIMPLE_CONJUNCTION 20: trades=18; expectancy=5.68%; profit factor=1.73
- STRATEGY_RESEARCH_V026 SCORE_THRESHOLD 5: trades=13; expectancy=4.84%; profit factor=1.50
- STRATEGY_RESEARCH_V022 SCORE_THRESHOLD 7: trades=4; expectancy=2.32%; profit factor=1.38
Holdout: untouched by this command
PRODUCTION_INFLUENCE=false
```

### `alpha strategy evaluate`

```text
Strategy Evaluation
Dataset: strategy-discovery-v1-reconstructed-ea5acfc503940ed1
Historical Truth: RECONSTRUCTED
Objective: expectancy after explicit transaction costs and slippage
Top Evaluations:
1. STRATEGY_RESEARCH_V020 | score >= 85 | INVALID_DATA | validation trades=7, expectancy=6.20%, holdout unavailable
2. STRATEGY_RESEARCH_V002 | complete data and raw approved | INVALID_DATA | validation trades=2, expectancy=5.83%, holdout unavailable
3. STRATEGY_RESEARCH_V043 | high confidence and complete data | INVALID_DATA | validation trades=18, expectancy=5.68%, holdout unavailable
4. STRATEGY_RESEARCH_V026 | score >= 80 | INVALID_DATA | validation trades=13, expectancy=4.84%, holdout unavailable
5. STRATEGY_RESEARCH_V022 | score >= 90 | INVALID_DATA | validation trades=4, expectancy=2.32%, holdout unavailable
6. STRATEGY_RESEARCH_V003 | high confidence | INVALID_DATA | validation trades=22, expectancy=1.70%, holdout unavailable
7. STRATEGY_RESEARCH_V009 | entry state BUY | INVALID_DATA | validation trades=22, expectancy=1.70%, holdout unavailable
8. STRATEGY_RESEARCH_V025 | score >= 75 | INVALID_DATA | validation trades=22, expectancy=1.70%, holdout unavailable
9. STRATEGY_RESEARCH_V040 | high confidence, price >= 0.65, score >= 70 | INVALID_DATA | validation trades=22, expectancy=1.70%, holdout unavailable
10. STRATEGY_RESEARCH_V049 | high confidence and price >= 0.65 | INVALID_DATA | validation trades=22, expectancy=1.70%, holdout unavailable
Benchmarks:
- Raw recorded approval: 5 validation trades, -4.92% expectancy
- APPROVAL_POLICY_V1: 0 validation trades, expectancy unavailable
- No trade: 0 validation trades, expectancy unavailable
Broad-Market Benchmark: unavailable; no valid aligned point-in-time benchmark-return series.
Holdout Accesses Evaluated: 0 strategies
Final Decision: NO_GENERALISABLE_STRATEGY_FOUND
PRODUCTION_INFLUENCE=false
```

### `alpha strategy robustness`

```text
Strategy Robustness
Dataset: strategy-discovery-v1-reconstructed-ea5acfc503940ed1
- STRATEGY_RESEARCH_V020: perturbation=FAIL, ablation=FAIL, cost stress=PASS
  delayed entry=UNAVAILABLE_NO_BAR_LEVEL_FILL_PATH; stop gap=UNAVAILABLE_NO_INTRABAR_GAP_ORDERING; weaknesses=perturbation collapse; ablation failure; bootstrap lower bound not positive; winner concentration
- STRATEGY_RESEARCH_V002: perturbation=PASS, ablation=FAIL, cost stress=PASS
  delayed entry=UNAVAILABLE_NO_BAR_LEVEL_FILL_PATH; stop gap=UNAVAILABLE_NO_INTRABAR_GAP_ORDERING; weaknesses=ablation failure; winner concentration
- STRATEGY_RESEARCH_V043: perturbation=PASS, ablation=FAIL, cost stress=PASS
  delayed entry=UNAVAILABLE_NO_BAR_LEVEL_FILL_PATH; stop gap=UNAVAILABLE_NO_INTRABAR_GAP_ORDERING; weaknesses=ablation failure; bootstrap lower bound not positive; winner concentration
- STRATEGY_RESEARCH_V026: perturbation=FAIL, ablation=FAIL, cost stress=PASS
  delayed entry=UNAVAILABLE_NO_BAR_LEVEL_FILL_PATH; stop gap=UNAVAILABLE_NO_INTRABAR_GAP_ORDERING; weaknesses=perturbation collapse; ablation failure; missed-fill failure; bootstrap lower bound not positive; winner concentration
- STRATEGY_RESEARCH_V022: perturbation=FAIL, ablation=FAIL, cost stress=PASS
  delayed entry=UNAVAILABLE_NO_BAR_LEVEL_FILL_PATH; stop gap=UNAVAILABLE_NO_INTRABAR_GAP_ORDERING; weaknesses=perturbation collapse; ablation failure; winner concentration
- STRATEGY_RESEARCH_V003: perturbation=PASS, ablation=FAIL, cost stress=PASS
  delayed entry=UNAVAILABLE_NO_BAR_LEVEL_FILL_PATH; stop gap=UNAVAILABLE_NO_INTRABAR_GAP_ORDERING; weaknesses=ablation failure; bootstrap lower bound not positive; winner concentration
- STRATEGY_RESEARCH_V009: perturbation=PASS, ablation=FAIL, cost stress=PASS
  delayed entry=UNAVAILABLE_NO_BAR_LEVEL_FILL_PATH; stop gap=UNAVAILABLE_NO_INTRABAR_GAP_ORDERING; weaknesses=ablation failure; bootstrap lower bound not positive; winner concentration
- STRATEGY_RESEARCH_V025: perturbation=FAIL, ablation=FAIL, cost stress=PASS
  delayed entry=UNAVAILABLE_NO_BAR_LEVEL_FILL_PATH; stop gap=UNAVAILABLE_NO_INTRABAR_GAP_ORDERING; weaknesses=perturbation collapse; ablation failure; bootstrap lower bound not positive; winner concentration
- STRATEGY_RESEARCH_V040: perturbation=PASS, ablation=FAIL, cost stress=PASS
  delayed entry=UNAVAILABLE_NO_BAR_LEVEL_FILL_PATH; stop gap=UNAVAILABLE_NO_INTRABAR_GAP_ORDERING; weaknesses=ablation failure; bootstrap lower bound not positive; winner concentration
- STRATEGY_RESEARCH_V049: perturbation=PASS, ablation=FAIL, cost stress=PASS
  delayed entry=UNAVAILABLE_NO_BAR_LEVEL_FILL_PATH; stop gap=UNAVAILABLE_NO_INTRABAR_GAP_ORDERING; weaknesses=ablation failure; bootstrap lower bound not positive; winner concentration
Unavailable stress tests are reported, never inferred.
Final Decision: NO_GENERALISABLE_STRATEGY_FOUND
PRODUCTION_INFLUENCE=false
```

### `alpha strategy leaderboard`

```text
Strategy Generalisation Leaderboard
Dataset: strategy-discovery-v1-reconstructed-ea5acfc503940ed1
Population: RECONSTRUCTED
1. V020 score >= 85 | INVALID_DATA | 7 trades | 6.20% expectancy
2. V002 complete data and raw approved | INVALID_DATA | 2 trades | 5.83%
3. V043 high confidence and complete data | INVALID_DATA | 18 trades | 5.68%
4. V026 score >= 80 | INVALID_DATA | 13 trades | 4.84%
5. V022 score >= 90 | INVALID_DATA | 4 trades | 2.32%
6. V003 high confidence | INVALID_DATA | 22 trades | 1.70%
7. V009 entry state BUY | INVALID_DATA | 22 trades | 1.70%
8. V025 score >= 75 | INVALID_DATA | 22 trades | 1.70%
9. V040 high confidence, price >= 0.65, score >= 70 | INVALID_DATA | 22 trades | 1.70%
10. V049 high confidence and price >= 0.65 | INVALID_DATA | 22 trades | 1.70%
11. V050 high confidence and score >= 70 | INVALID_DATA | 22 trades | 1.70%
12. V053 complete plan and high confidence | INVALID_DATA | 22 trades | 1.70%
13. V058 high confidence and volume >= 0.55 | INVALID_DATA | 22 trades | 1.70%
14. V004 high confidence and BUY | INVALID_DATA | 18 trades | 1.56%
15. V006 BUY | INVALID_DATA | 18 trades | 1.56%
16. V015 price >= 0.75 and volume >= 0.65 | INVALID_DATA | 48 trades | -0.71%
17. V014 price >= 0.75 | INVALID_DATA | 106 trades | -1.26%
18. V034 candle >= 0.55 and high confidence | INVALID_DATA | 20 trades | -3.43%
19. V042 score >= 70 and volume >= 0.55 | INVALID_DATA | 49 trades | -4.21%
20. V044 price >= 0.65, score >= 70, volume >= 0.55 | INVALID_DATA | 49 trades | -4.21%
Benchmarks: raw approval -4.92%; APPROVAL_POLICY_V1 unavailable; no-trade unavailable.
Final Decision: NO_GENERALISABLE_STRATEGY_FOUND
PRODUCTION_INFLUENCE=false
```

### `alpha strategy publish-shadow-candidate`

```text
Shadow Strategy Publication
NO_GENERALISABLE_STRATEGY_FOUND
No strategy specification was published.
APPROVAL_POLICY_V1 and existing forward cohorts are unchanged.
PRODUCTION_INFLUENCE=false
```

### `alpha strategy discovery-report`

```text
Walk-Forward Strategy Discovery Report
Generated At: 2026-07-10T18:26:35.837513+00:00
Dataset: strategy-discovery-v1-reconstructed-ea5acfc503940ed1
Historical Truth: RECONSTRUCTED
Discovery Population: 1500
Excluded Population: 46
Strategies Tested: 61
Chronological Folds: 3
Classification Summary:
- INVALID_DATA: 58 non-benchmark candidates
Top Candidate Leaderboard:
1. score >= 85: 7 trades, 6.20% reconstructed validation expectancy
2. complete data and raw approved: 2 trades, 5.83%
3. high confidence and complete data: 18 trades, 5.68%
Dominant Failure Reasons:
- authoritative identity and corporate-action coverage is insufficient
- historical evaluation uses a separately labelled reconstructed population
Current Forward Evidence:
- APPROVAL_POLICY_V1 immutable snapshots=108, completed shadow positions=0; no strategy-discovery cohort mixed.
Broad-Market Benchmark:
- Unavailable; no valid point-in-time benchmark return is aligned to candidate outcomes.
Highest-Value Evidence Gap:
- Expand authoritative point-in-time decision provenance, identity, and corporate-action coverage before strategy publication.
Final Strategy Decision: NO_GENERALISABLE_STRATEGY_FOUND
APPROVAL_POLICY_V1 remains unchanged.
PRODUCTION_INFLUENCE=false
```

## 8. Quality Gates

- `poetry run pytest`: passed
- `poetry run ruff check .`: passed
- `poetry run mypy alpha`: passed across 410 source files
- `poetry build`: source distribution and wheel built successfully

## 9. Final Confirmation

The final strategy decision is `NO_GENERALISABLE_STRATEGY_FOUND`. No production
policy, recommendation, approval, allocation, live execution, broker, or real-capital
behavior changed. `PRODUCTION_INFLUENCE=false`.
