# Strategy and Indicator Combination Backtest Lab Implementation Report

## 1. Implementation Scope

Project Alpha now has a bounded, deterministic strategy research lab under
`alpha/strategy_lab`. It composes the existing point-in-time strategy-discovery
pipeline instead of creating a second replay system.

The lab inventories usable and quarantined inputs, generates interpretable strategy
combinations, simulates complete OHLC trade lifecycles when bars are supplied, compares
strategies on a common population, calculates aggregate and time-series metrics,
performs attribution and robustness checks, persists every result, and reports its
findings to the Research Registry and IRD.

The current default population contains reconstructed outcome rows rather than
authoritative bar-level outcomes. Consequently, the lab uses a clearly labelled
`RECONSTRUCTED_OUTCOME_PROXY` for the default comparison and does not infer unavailable
fills or intraday stop/target ordering.

## 2. Files Changed

New production files:

- `alpha/strategy_lab/__init__.py`
- `alpha/strategy_lab/models.py`
- `alpha/strategy_lab/indicator_registry.py`
- `alpha/strategy_lab/strategy_template_registry.py`
- `alpha/strategy_lab/combination_generator.py`
- `alpha/strategy_lab/backtest_engine.py`
- `alpha/strategy_lab/trade_simulator.py`
- `alpha/strategy_lab/execution_assumptions.py`
- `alpha/strategy_lab/performance_metrics.py`
- `alpha/strategy_lab/time_series_analysis.py`
- `alpha/strategy_lab/component_attribution.py`
- `alpha/strategy_lab/combination_attribution.py`
- `alpha/strategy_lab/robustness_analysis.py`
- `alpha/strategy_lab/benchmarking.py`
- `alpha/strategy_lab/leaderboard.py`
- `alpha/strategy_lab/strategy_comparison.py`
- `alpha/strategy_lab/experiment_registry.py`
- `alpha/strategy_lab/exporting.py`
- `alpha/strategy_lab/research_integration.py`
- `alpha/strategy_lab/service.py`
- `alpha/strategy_lab/rendering.py`
- `alpha/application/strategy_lab_cli.py`

Integration changes:

- `alpha/cli.py`
- `alpha/research/models.py`
- `alpha/research/diagnostic_registry.py`

Tests and documentation:

- `tests/strategy_lab/test_strategy_lab.py`
- `tests/research/test_institutional_research_director.py`
- `docs/STRATEGY_INDICATOR_BACKTEST_LAB.md`
- `docs/STRATEGY_LAB_IMPLEMENTATION_REPORT.md`

## 3. Tests Added

The strategy-lab regression suite adds 23 deterministic tests covering:

- indicator registration and quarantined-feature exclusion;
- template inventory, bounded generation, deterministic hashes, and rule de-duplication;
- point-in-time enforcement and maximum-component limits;
- confirmation entries, missed entries, stop/target ambiguity, and gap stops;
- partial exits, trailing stops, and time exits;
- explicit costs and slippage;
- average winners/losers, payoff, expectancy, precision intervals, profit factor,
  drawdown, Sharpe, Sortino, and capital utilisation;
- annual, quarterly, rolling, equity, and underwater series;
- component and combination attribution;
- sample-size and evidence classifications;
- multiple-testing and cost-stress robustness;
- strategy comparison;
- immutable registry behavior and JSON/CSV exports;
- CLI registration and rendering;
- Research Registry and IRD plugin integration;
- policy and production isolation.

## 4. Inventory

The registry contains 21 components: 15 usable point-in-time inputs and 6 quarantined
inputs. The usable set is:

`strategy_score`, `final_verdict`, `raw_approved`, `confidence`, `data_quality`,
`setup_type`, `entry_timing_state`, `long_trade_permission`, `complete_trade_plan`,
`entry_price`, `stop_distance_pct`, `reward_risk`, `price_component`,
`volume_component`, and `candle_component`.

The quarantined set is:

- `retracement_component`: direction remains unresolved after inverse-predictive audit.
- `market_regime`: invalid reference-label scale.
- `sector`: no authoritative point-in-time historical membership.
- `realised_return_pct`, `mfe_pct`, `mae_pct`: future-derived outcomes.

The strategy template registry contains all 17 requested families, including single,
two, and three-component rules, weighted scores, setup/timing rules, price and volume
rules, trade-plan quality, raw approval, `APPROVAL_POLICY_V1`, score thresholds,
no-trade, and broad benchmark templates.

## 5. Dataset and Evidence

- Dataset: `strategy-discovery-v1-reconstructed-ea5acfc503940ed1`
- Available reconstructed outcomes: 1,500
- Excluded outcomes: 46
- Authoritative completed outcomes: 0
- Evidence class: `RECONSTRUCTED`
- Simulation mode: `RECONSTRUCTED_OUTCOME_PROXY`
- Evidence label on tested candidates: `RECONSTRUCTED_RESEARCH_ONLY`

No result is described as authoritative, out-of-sample validated, forward observed, or
deployment-ready.

## 6. Search Space

The default search is capped at three components and uses 61 deterministic strategies:

| Family | Variants |
| --- | ---: |
| Approval gate subset | 6 |
| APPROVAL_POLICY_V1 | 1 |
| Entry timing | 3 |
| No trade | 1 |
| Price structure | 3 |
| Price plus volume | 4 |
| Raw recorded approval | 1 |
| Score threshold | 7 |
| Setup specific | 4 |
| Signal component subset | 3 |
| Simple conjunction | 25 |
| Trade-plan quality | 3 |

Search-space hash:
`46ffd6cb59dba72bd8d4cba26cbf3090916adf966095ba49be22b49516317431`.

The manifest records duplicate removals, impossible-rule rejections, same-lineage
flags, deterministic ordering, execution variants, dataset identity, and total trials.
The current search produced 15 lineage-redundancy flags and no duplicate or impossible
rules.

## 7. Execution and Cost Assumptions

The versioned profile is `strategy-lab-execution-v1`:

- recorded reference entry, stop, and targets for the reconstructed comparison;
- 20-day holding horizon;
- 20 bps configured round-trip transaction-cost assumption;
- 10 bps configured round-trip slippage assumption;
- total cost drag: 0.30%;
- 10% sequential research-capital allocation;
- five-session entry-validity window;
- 50% partial-exit fraction;
- gap-through-stop fills at the opening price;
- stop-first conservative ordering when a daily bar touches stop and target;
- statutory fee fields remain zero because the lab does not assert a current legal or
  brokerage schedule.

The standalone bar simulator additionally supports next-open/next-close entries,
aggressive/preferred/confirmation/breakout/zone entries, fixed/ATR/support/swing/trade
plan/volatility stops, fixed-R/trade-plan/partial/trailing/time exits, MFE, MAE, R
multiples, delayed entries, and explicit missed-fill reasons.

## 8. Overall Leaderboard

| Rank | Strategy | Trades | Precision | Net Expectancy | Profit Factor | Drawdown | Score | Classification |
| ---: | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| 1 | `LAB_STRATEGY_0043_38b2c944` | 51 | 45.10% | 0.34% | 1.04 | 92.45% | 37.15 | OVERFIT |
| 2 | `LAB_STRATEGY_0058_126e03bc` | 104 | 37.50% | -1.53% | 0.83 | 99.75% | 28.50 | NEGATIVE_EXPECTANCY |
| 3 | `LAB_STRATEGY_0053_0f28f21a` | 104 | 37.50% | -1.53% | 0.83 | 99.75% | 28.50 | NEGATIVE_EXPECTANCY |

The composite score includes expectancy, profit factor, drawdown, stability, sample
sufficiency, concentration, and cost robustness. Samples below 30 trades receive a
continuous sufficiency penalty and cannot lead the default view on precision alone.

## 9. Specialized Leaderboards

Highest precision and expectancy:

- `LAB_STRATEGY_0022_8e6d73be`: 57.14% precision and 4.34% net expectancy, but only
  14 trades over five positive/negative annual periods. It is `INSUFFICIENT_SAMPLE`.
- `LAB_STRATEGY_0043_38b2c944`: 45.10% precision and 0.34% net expectancy across 51
  trades, but it is `OVERFIT` with extreme drawdown.

Best payoff/risk-reward:

- Strategies `0006` and `0004`: 1.42 payoff ratio, but average R is -0.12 over 90
  trades.
- Strategy `0022`: 1.42 payoff and positive 0.16 average R, but only 14 trades.

Lowest drawdown:

- Strategy `0030`: 2.65% drawdown, but only one losing trade.
- Strategy `0022`: 46.06% drawdown over 14 trades.
- The best minimum-sample candidate, strategy `0043`, has 92.45% drawdown.

Most stable:

- Strategy `0022`: 60% positive years across only five represented years.
- Strategy `0043`: 50% positive years across ten years.
- All adjusted p-values are 1 after the existing multiple-testing correction.

## 10. Indicator and Combination Attribution

The lab found positive and negative marginal associations for some of the same
components in different matched contexts. That is contextual interaction, not a global
causal claim. `LINEAGE_CONFOUNDED` is used when the component shares source lineage with
another rule, including score/component overlap.

Observed component labels include `POSITIVE_MARGINAL_VALUE`,
`NEGATIVE_MARGINAL_VALUE`, `INSUFFICIENT_EVIDENCE`, and `LINEAGE_CONFOUNDED`.
Combination attribution separately identifies tiny samples, elimination of more than
90% of opportunities, and combinations with no clear net value.

## 11. Performance Through Time

The strongest research strategy spans ten annual periods:

| Year | Trades | Precision | Expectancy | Drawdown |
| ---: | ---: | ---: | ---: | ---: |
| 2017 | 2 | 100.00% | 5.20% | 0.00% |
| 2018 | 2 | 0.00% | -25.40% | 44.35% |
| 2019 | 3 | 33.33% | -14.60% | 39.92% |
| 2020 | 2 | 0.00% | -13.55% | 25.46% |
| 2021 | 5 | 60.00% | 7.29% | 16.48% |
| 2022 | 5 | 100.00% | 36.94% | 0.00% |
| 2023 | 8 | 37.50% | 3.61% | 42.25% |
| 2024 | 16 | 50.00% | 1.22% | 57.20% |
| 2025 | 5 | 20.00% | -19.87% | 73.37% |
| 2026 | 3 | 0.00% | -13.84% | 36.29% |

It has 23 quarterly periods, 32 rolling 20-trade windows, 2 rolling 50-trade
windows, 51 equity points, and 51 underwater points. This time dispersion is why the
small positive aggregate expectancy is not treated as stable.

## 12. Top-Strategy Comparison

The first and second composite strategies share 51 trades on the same 1,500-row
population. The first requires `confidence=HIGH` and `data_quality=COMPLETE`. The
second replaces the data-quality condition with `volume_component>=0.55`, adding 53
trades. Relative to the first, the second has:

- precision lower by 7.60 percentage points;
- expectancy lower by 1.87 percentage points;
- drawdown higher by 7.30 percentage points;
- capital utilisation higher by 3.53 percentage points.

Confidence remains `LOW_RECONSTRUCTED`; the differences are associative.

## 13. Robustness and Multiple Testing

For the strongest strategy:

- expectancy confidence interval: -7.83% to 8.51%;
- fold consistency: 50%;
- adjusted p-value: 1 across 58 effective hypotheses;
- cost and slippage stress retain a positive point estimate;
- the confidence interval includes zero;
- positive-period consistency remains below 60%;
- classification: `OVERFIT`.

The other leading minimum-sample strategies have negative point expectancy, confidence
intervals crossing zero, no cost/slippage robustness, and adjusted p-values of 1.

## 14. Final Recommendation

`NO_RELIABLE_STRATEGY_FOUND`

No strategy qualifies for walk-forward or shadow validation. The strongest research
candidate is `LAB_STRATEGY_0043_38b2c944`, but its reconstructed 0.34% net expectancy,
92.45% drawdown, non-significant adjusted result, and unstable annual distribution do
not support promotion.

The highest-value missing evidence is authoritative completed outcomes with
corporate-action-complete chronological bars. That evidence is needed to validate
fills, stop/target event ordering, holding-period exits, and true holdout performance.

## 15. Registry and IRD

The immutable lab experiment is:

- ID: `strategy-lab-db09c147c571c582e889`
- Schema: `strategy-lab-v1.2`
- Decision: `INCONCLUSIVE`
- Confidence: `LOW`
- Production influence: `false`

All 61 tested strategies, including failures, are retained with immutable hashes,
rules, execution profile, dataset/evidence identity, metrics, timelines, robustness,
classification, and rejection reasons. Repeating an identical experiment is
idempotent; changing its payload under the same ID is rejected.

The IRD plugin is `strategy-indicator-backtest-lab`. It exposes counts,
classifications, attribution, robustness, the final conclusion, and the evidence gap.
IRD places authoritative corporate-action-complete outcomes at P2 because current
approval-policy evidence remains the higher-confidence P0 bottleneck. Historical
backtest output is not recorded as measured forward ROI.

## 16. CLI Outputs

### `strategy-lab inventory`

```text
Strategy Lab Indicator and Rule Inventory
Indicators Registered: 21
Usable Point-in-Time Indicators: 15
Quarantined Indicators: 6
Usable Indicators:
- strategy_score: RECOMMENDATION_SCORE; points; source=candidate decision record; evidence=RECONSTRUCTED
- final_verdict: RECOMMENDATION; category; source=candidate decision record; evidence=RECONSTRUCTED
- raw_approved: APPROVAL_GATE; boolean; source=candidate decision record; evidence=RECONSTRUCTED
- confidence: CONFIDENCE; category; source=candidate decision record; evidence=RECONSTRUCTED
- data_quality: DATA_QUALITY; category; source=candidate decision record; evidence=RECONSTRUCTED
- setup_type: SETUP; category; source=candidate decision record; evidence=RECONSTRUCTED
- entry_timing_state: ENTRY_TIMING; category; source=candidate decision record; evidence=RECONSTRUCTED
- long_trade_permission: APPROVAL_GATE; boolean; source=candidate decision record; evidence=RECONSTRUCTED
- complete_trade_plan: TRADE_PLAN; boolean; source=candidate decision record; evidence=RECONSTRUCTED
- entry_price: ENTRY; INR; source=candidate decision record; evidence=RECONSTRUCTED
- stop_distance_pct: RISK_VOLATILITY; percent; source=candidate decision record; evidence=RECONSTRUCTED
- reward_risk: TRADE_PLAN; ratio; source=candidate decision record; evidence=RECONSTRUCTED
- price_component: PRICE_STRUCTURE; normalized score; source=candidate_learning.CandidateDecisionRecord.indicator_scores; evidence=RECONSTRUCTED
- volume_component: VOLUME; normalized score; source=candidate_learning.CandidateDecisionRecord.indicator_scores; evidence=RECONSTRUCTED
- candle_component: CANDLE; normalized score; source=candidate_learning.CandidateDecisionRecord.indicator_scores; evidence=RECONSTRUCTED
Quarantined Indicators:
- retracement_component: Previously inversely predictive; calibration direction is unresolved.
- market_regime: Reference-label scale defect invalidates predictive-quality evidence.
- sector: Authoritative point-in-time historical sector membership is unavailable.
- realised_return_pct: Future-derived outcome fields cannot be discovery features.
- mfe_pct: Future-derived outcome fields cannot be discovery features.
- mae_pct: Future-derived outcome fields cannot be discovery features.
Strategy Templates: 17
- single-indicator: Single Indicator Threshold; max components=1
- two-indicator: Two Indicator Conjunction; max components=2
- three-indicator: Three Indicator Conjunction; max components=3
- weighted-score: Weighted Score; max components=3
- setup-specific: Setup Specific; max components=3
- entry-timing: Entry Timing Specific; max components=3
- price-only: Price Only; max components=1
- price-volume: Price Plus Volume; max components=2
- trend-rs: Trend Plus Relative Strength; max components=2
- support-breakout: Support Resistance Breakout; max components=3
- retracement: Pullback and Retracement; max components=3
- trade-plan: Trade Plan Quality; max components=3
- raw-approval: Raw Approval Policy; max components=3
- approval-v1: APPROVAL_POLICY_V1; max components=3
- recommendation-score: Recommendation Score; max components=1
- no-trade: No Trade; max components=0
- broad-benchmark: Broad Benchmark; max components=0
PRODUCTION_INFLUENCE=false
```

### `strategy-lab generate`

```text
Strategy Lab Bounded Search Space
Dataset: strategy-discovery-v1-reconstructed-ea5acfc503940ed1
Evidence Class: RECONSTRUCTED
Rows Available: 1500
Strategies Generated: 61
Total Trials: 61
Maximum Components: 3
Duplicate Rules Removed: 0
Impossible Rules Rejected: 0
Lineage Redundancy Flags: 15
Search-Space Hash: 46ffd6cb59dba72bd8d4cba26cbf3090916adf966095ba49be22b49516317431
Family Counts:
- APPROVAL_GATE_SUBSET: 6
- APPROVAL_POLICY_V1: 1
- ENTRY_TIMING: 3
- NO_TRADE: 1
- PRICE_STRUCTURE: 3
- PRICE_VOLUME: 4
- RAW_RECORDED_APPROVAL: 1
- SCORE_THRESHOLD: 7
- SETUP_SPECIFIC: 4
- SIGNAL_COMPONENT_SUBSET: 3
- SIMPLE_CONJUNCTION: 25
- TRADE_PLAN_QUALITY: 3
Execution Rules: RECORDED_REFERENCE, RECORDED_PLAN, RECORDED_PLAN, HOLD_20_DAYS
PRODUCTION_INFLUENCE=false
```

### `strategy-lab backtest`

```text
Strategy Lab Historical Backtest
Experiment: strategy-lab-db09c147c571c582e889
Dataset: strategy-discovery-v1-reconstructed-ea5acfc503940ed1
Evidence Class: RECONSTRUCTED
Source Rows: 1500
Excluded Rows: 46
Strategies Tested: 61
Round-Trip Cost: 0.3%
Classification Summary:
- INSUFFICIENT_SAMPLE: 5
- NEGATIVE_EXPECTANCY: 55
- OVERFIT: 1
Simulation Mode: RECONSTRUCTED_OUTCOME_PROXY
Bar-level fills and intraday stop/target ordering are not inferred from the reconstructed population.
Conclusion: NO_RELIABLE_STRATEGY_FOUND
PRODUCTION_INFLUENCE=false
```

### `strategy-lab leaderboard --top 3`

```text
Strategy Lab Leaderboard - COMPOSITE
1. LAB_STRATEGY_0043_38b2c944 | SIMPLE_CONJUNCTION 20
   Family: SIMPLE_CONJUNCTION
   Trades: 51 | Precision: 45.10% | Net Expectancy: 0.34%
   Profit Factor: 1.04 | Payoff: 1.26 | Max Drawdown: 92.45%
   Research Score: 37.15 | Evidence: RECONSTRUCTED_RESEARCH_ONLY | Classification: OVERFIT
2. LAB_STRATEGY_0058_126e03bc | SIMPLE_CONJUNCTION 13
   Family: SIMPLE_CONJUNCTION
   Trades: 104 | Precision: 37.50% | Net Expectancy: -1.53%
   Profit Factor: 0.83 | Payoff: 1.38 | Max Drawdown: 99.75%
   Research Score: 28.50 | Evidence: RECONSTRUCTED_RESEARCH_ONLY | Classification: NEGATIVE_EXPECTANCY
3. LAB_STRATEGY_0053_0f28f21a | SIMPLE_CONJUNCTION 19
   Family: SIMPLE_CONJUNCTION
   Trades: 104 | Precision: 37.50% | Net Expectancy: -1.53%
   Profit Factor: 0.83 | Payoff: 1.38 | Max Drawdown: 99.75%
   Research Score: 28.50 | Evidence: RECONSTRUCTED_RESEARCH_ONLY | Classification: NEGATIVE_EXPECTANCY
Default ranking is composite, not precision-only.
PRODUCTION_INFLUENCE=false
```

### `strategy-lab compare`

```text
Strategy Lab Side-by-Side Comparison
Shared Eligible Population: 1500
Common Trades: 51
- LAB_STRATEGY_0043_38b2c944 Rules: confidence|EQUAL|HIGH; data_quality|EQUAL|COMPLETE
  Results: unique trades=0, precision delta=0.00 pp, expectancy delta=0.00 pp, drawdown delta=0.00 pp, capital-utilisation delta=0.00 pp, configured cost drag=0.30%
- LAB_STRATEGY_0058_126e03bc Rules: confidence|EQUAL|HIGH; volume_component|GREATER_THAN_OR_EQUAL|0.55
  Results: unique trades=53, precision delta=-7.60 pp, expectancy delta=-1.87 pp, drawdown delta=7.30 pp, capital-utilisation delta=3.53 pp, configured cost drag=0.30%
Evidence Confidence: LOW_RECONSTRUCTED
Conclusion: Differences are associative reconstructed evidence; no causal or deployment inference is permitted.
PRODUCTION_INFLUENCE=false
```

### `strategy-lab attribution --top 5`

```text
Strategy Lab Indicator and Combination Attribution
Marginal Indicator Comparisons:
- candle_component in LAB_STRATEGY_0031_28bdcd49: INSUFFICIENT_EVIDENCE; trades delta=0; expectancy delta=NOT_ESTIMABLE pp; precision delta=NOT_ESTIMABLE pp
- candle_component in LAB_STRATEGY_0033_0c16f2be: LINEAGE_CONFOUNDED; trades delta=-194; expectancy delta=0.50 pp; precision delta=1.81 pp
- candle_component in LAB_STRATEGY_0034_3926af56: NEGATIVE_MARGINAL_VALUE; trades delta=-4; expectancy delta=-1.22 pp; precision delta=-0.50 pp
- candle_component in LAB_STRATEGY_0035_ebbd7005: POSITIVE_MARGINAL_VALUE; trades delta=-341; expectancy delta=0.99 pp; precision delta=1.82 pp
- candle_component in LAB_STRATEGY_0037_64687317: LINEAGE_CONFOUNDED; trades delta=-21; expectancy delta=0.10 pp; precision delta=-0.03 pp
Combination Value Sources:
- LAB_STRATEGY_0002_f94d11fb: TINY_SAMPLE; Apparent performance depends on fewer than 30 trades.
- LAB_STRATEGY_0004_0e4f4746: OPPORTUNITY_ELIMINATION; The combination removes more than 90% of the eligible population.
- LAB_STRATEGY_0015_91a45ea0: NO_CLEAR_VALUE; The combination has no clearly supported net outcome advantage.
- LAB_STRATEGY_0016_75b8cc59: NO_CLEAR_VALUE; The combination has no clearly supported net outcome advantage.
- LAB_STRATEGY_0017_555e8e20: NO_CLEAR_VALUE; The combination has no clearly supported net outcome advantage.
Attribution is associative; lineage-confounded features are not called causal.
PRODUCTION_INFLUENCE=false
```

### `strategy-lab timeline`

```text
Strategy Lab Performance Timeline
Strategy: LAB_STRATEGY_0043_38b2c944 | SIMPLE_CONJUNCTION 20
Annual Performance:
- 2017: trades=2, precision=100.00%, expectancy=5.20%, profit factor=NOT_ESTIMABLE, drawdown=0.00%
- 2018: trades=2, precision=0.00%, expectancy=-25.40%, profit factor=0.00, drawdown=44.35%
- 2019: trades=3, precision=33.33%, expectancy=-14.60%, profit factor=0.01, drawdown=39.92%
- 2020: trades=2, precision=0.00%, expectancy=-13.55%, profit factor=0.00, drawdown=25.46%
- 2021: trades=5, precision=60.00%, expectancy=7.29%, profit factor=2.94, drawdown=16.48%
- 2022: trades=5, precision=100.00%, expectancy=36.94%, profit factor=NOT_ESTIMABLE, drawdown=0.00%
- 2023: trades=8, precision=37.50%, expectancy=3.61%, profit factor=1.40, drawdown=42.25%
- 2024: trades=16, precision=50.00%, expectancy=1.22%, profit factor=1.16, drawdown=57.20%
- 2025: trades=5, precision=20.00%, expectancy=-19.87%, profit factor=0.04, drawdown=73.37%
- 2026: trades=3, precision=0.00%, expectancy=-13.84%, profit factor=0.00, drawdown=36.29%
Quarterly Periods: 23
Rolling 20-Trade Windows: 32
Rolling 50-Trade Windows: 2
Equity Curve Points: 51
Underwater Curve Points: 51
PRODUCTION_INFLUENCE=false
```

### `strategy-lab robustness --top 3`

```text
Strategy Lab Robustness and Multiple-Testing Audit
- LAB_STRATEGY_0043_38b2c944: overfit=True; fold consistency=50.00%; adjusted p=1; hypotheses=58
  Cost stress=True; slippage stress=True; CI=-7.83 to 8.51
  Weaknesses: expectancy confidence interval includes zero; multiple-testing-adjusted evidence is not significant; positive-period consistency is below 60 percent
- LAB_STRATEGY_0058_126e03bc: overfit=True; fold consistency=36.36%; adjusted p=1; hypotheses=58
  Cost stress=False; slippage stress=False; CI=-6.39 to 3.33
  Weaknesses: expectancy confidence interval includes zero; multiple-testing-adjusted evidence is not significant; positive-period consistency is below 60 percent
- LAB_STRATEGY_0053_0f28f21a: overfit=True; fold consistency=36.36%; adjusted p=1; hypotheses=58
  Cost stress=False; slippage stress=False; CI=-6.39 to 3.33
  Weaknesses: expectancy confidence interval includes zero; multiple-testing-adjusted evidence is not significant; positive-period consistency is below 60 percent
Reconstructed winners remain research-only even when robustness checks pass.
PRODUCTION_INFLUENCE=false
```

### `strategy-lab report --top 3`

```text
Project Alpha Strategy and Indicator Combination Backtest Lab
Experiment: strategy-lab-db09c147c571c582e889
Evidence: RECONSTRUCTED
Strategies Tested: 61
Strongest Research Strategy: LAB_STRATEGY_0043_38b2c944
Top Composite Strategies:
- LAB_STRATEGY_0043_38b2c944: score=37.15, expectancy=0.34%, precision=45.10%, trades=51
- LAB_STRATEGY_0058_126e03bc: score=28.50, expectancy=-1.53%, precision=37.50%, trades=104
- LAB_STRATEGY_0053_0f28f21a: score=28.50, expectancy=-1.53%, precision=37.50%, trades=104
Highest Precision Strategies:
- LAB_STRATEGY_0022_8e6d73be: precision=57.14%, trades=14
- LAB_STRATEGY_0043_38b2c944: precision=45.10%, trades=51
- LAB_STRATEGY_0002_f94d11fb: precision=42.86%, trades=21
Highest Net Expectancy Strategies:
- LAB_STRATEGY_0022_8e6d73be: expectancy=4.34%, drawdown=46.06%, trades=14
- LAB_STRATEGY_0043_38b2c944: expectancy=0.34%, drawdown=92.45%, trades=51
- LAB_STRATEGY_0058_126e03bc: expectancy=-1.53%, drawdown=99.75%, trades=104
Best Payoff / Risk-Reward Strategies:
- LAB_STRATEGY_0006_ef54fc02: payoff=1.42, average R=-0.12, trades=90
- LAB_STRATEGY_0004_0e4f4746: payoff=1.42, average R=-0.12, trades=90
- LAB_STRATEGY_0022_8e6d73be: payoff=1.42, average R=0.16, trades=14
Lowest Drawdown Strategies:
- LAB_STRATEGY_0030_186ddb3b: drawdown=2.65%, expectancy=-2.65%, trades=1
- LAB_STRATEGY_0022_8e6d73be: drawdown=46.06%, expectancy=4.34%, trades=14
- LAB_STRATEGY_0002_f94d11fb: drawdown=87.61%, expectancy=-3.05%, trades=21
Most Stable Strategies:
- LAB_STRATEGY_0022_8e6d73be: positive years=60.00%, years=5, adjusted p=1
- LAB_STRATEGY_0043_38b2c944: positive years=50.00%, years=10, adjusted p=1
- LAB_STRATEGY_0020_b6966663: positive years=50.00%, years=8, adjusted p=1
Indicator Attribution Summary:
- Positive marginal associations: candle_component, complete_trade_plan, confidence, data_quality, entry_timing_state, final_verdict, price_component, stop_distance_pct, strategy_score, volume_component
- Negative marginal associations: candle_component, complete_trade_plan, data_quality, entry_timing_state, final_verdict, price_component, setup_type, strategy_score
Benchmark Summary:
- RAW_RECORDED_APPROVAL: expectancy=-2.76%, precision=34.29%, trades=70
- NO_TRADE: expectancy=NOT_ESTIMABLE%, precision=NOT_ESTIMABLE%, trades=0
- APPROVAL_POLICY_V1: expectancy=NOT_ESTIMABLE%, precision=NOT_ESTIMABLE%, trades=0
Top Strategy Time Stability: 10 annual periods, 32 rolling 20-trade windows, 2 rolling 50-trade windows.
Configured Cost Impact: gross expectancy 0.64% versus net 0.34%.
Final Conclusion: NO_RELIABLE_STRATEGY_FOUND
Highest-Value Missing Evidence: Authoritative completed outcomes with corporate-action-complete bar histories are required for fill, stop, target, and holdout validation.
No strategy was promoted, no threshold changed, and no capital was allocated.
PRODUCTION_INFLUENCE=false
```

## 17. Quality Gates

- `poetry run pytest -q`: 1,627 passed in 169.36 seconds.
- `poetry run ruff check .`: all checks passed.
- `poetry run mypy alpha`: no issues in 446 source files.
- `poetry build`: built `alpha-1.3.0.dev0.tar.gz` and
  `alpha-1.3.0.dev0-py3-none-any.whl`.

## 18. Production Isolation Confirmation

The Recommendation Engine, Approval Engine, replay semantics, forward-validation
cohorts, learning thresholds, portfolio allocation, live market data, broker/order APIs,
and capital deployment behavior were not modified by this milestone. No strategy is
automatically promoted. The lab only produces governed research evidence.

`PRODUCTION_INFLUENCE=false`.
