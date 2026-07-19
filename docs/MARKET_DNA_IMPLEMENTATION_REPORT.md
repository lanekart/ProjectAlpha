# Market DNA Discovery Engine Implementation Report

## 1. Files Changed

The milestone adds the `alpha.market_dna` package, the `market-dna` CLI group,
Research Registry and IRD registration, deterministic tests, and architecture
documentation.

Core package files:

- `models.py`
- `outcome_cohort_registry.py`
- `feature_manifest.py`
- `feature_snapshot_builder.py`
- `cohort_builder.py`
- `distribution_analysis.py`
- `effect_size_engine.py`
- `feature_enrichment.py`
- `matched_cohort.py`
- `interaction_discovery.py`
- `cluster_discovery.py`
- `hierarchical_dna.py`
- `stability_analysis.py`
- `lineage_analysis.py`
- `multiple_testing_control.py`
- `hypothesis_generator.py`
- `dna_matcher.py`
- `dna_registry.py`
- `strategy_lab_bridge.py`
- `exporting.py`
- `research_integration.py`
- `service.py`
- `rendering.py`

Integration files:

- `alpha/application/market_dna_cli.py`
- `alpha/cli.py`
- `alpha/research/models.py`
- `alpha/research/diagnostic_registry.py`
- `tests/research/test_institutional_research_director.py`
- `docs/MARKET_DNA_DISCOVERY_ENGINE.md`

## 2. Tests Added

`tests/market_dna/test_market_dna.py` adds 18 deterministic tests covering cohort
versioning and construction, costs, point-in-time enforcement, leakage and quarantine
handling, scale and missingness, effect sizes, enrichment, confidence intervals, odds
and risk ratios, continuous distributions, deterministic matching, bounded
interactions, cluster label isolation, false-discovery correction, lineage overlap,
temporal stability, concentration, immutable hashing, research-only DNA matching,
inert Strategy Lab publication, immutable persistence, JSON/CSV export, Research
Registry integration, IRD registration, CLI rendering, filter validation, and
production isolation.

## 3. Outcome Cohort Definitions

All definitions use `PRIMARY_RECORDED_HORIZON` and execution cost profile
`strategy-lab-execution-v1-30bps`.

| Cohort | Exact predicate |
|---|---|
| Strong winners | `net_return_pct >= 20` |
| Moderate winners | `10 <= net_return_pct < 20` |
| Small winners | `1 < net_return_pct < 10` |
| Flat outcomes | `-1 <= net_return_pct <= 1` |
| Small losers | `-10 < net_return_pct < -1` |
| Large losers | `-25 < net_return_pct <= -10` |
| Catastrophic losers | `net_return_pct <= -25` |
| High-MFE opportunities | `mfe_pct >= 15` |
| High-MAE failures | `mae_pct <= -15` |
| Profitable rejected | `raw_approved == false and net_return_pct > 1` |
| Approved profitable | `raw_approved == true and net_return_pct > 1` |
| Approved unprofitable | `raw_approved == true and net_return_pct <= 0` |
| Missed-entry winners | `entry_missed_proxy == true and net_return_pct > 1` |
| Stop-hit then recovered | `stop_touched == true and net_return_pct > 1` |
| Target achieved | `target_1_touched == true` |
| Time expired | `target_1_touched == false and stop_touched == false` |

The last four event-oriented definitions are explicitly reconstructed proxies because
the current source cannot prove authoritative intrabar event ordering.

## 4. Dataset and Evidence Class

- Dataset: `strategy-discovery-v1-reconstructed-ea5acfc503940ed1`
- Analysed outcomes: 1,500
- Excluded outcomes: 46
- Evidence class: `RECONSTRUCTED`
- Authoritative completed historical outcomes: 0
- Corporate-action-complete outcome population: unavailable
- Genuine untouched holdout: unavailable

No current result is described as causal, forward validated, deployable, or measured
forward ROI.

## 5. Feature Inventory and Quarantine

- Registered: 21
- Usable: 11
- Usable with caution: 4
- Quarantined: 6

Usable features are strategy score, final verdict, raw approval, confidence, data
quality, setup type, entry timing state, long-trade permission, complete trade plan,
stop distance, and reward/risk. Entry price and normalized price, volume, and candle
components are cautionary. Raw entry price is not searched across symbols.

Retracement is quarantined because its calibration direction remains unresolved.
Market regime is quarantined because of the reference-label scale defect. Sector is
quarantined because authoritative point-in-time membership is absent. Realised return,
MFE, and MAE are outcome labels and are prohibited from the discovery feature set.

## 6. Winner DNA Results

The strongest FDR-surviving winner association was normalized price component at or
above 0.65 in moderate winners: 44 matched observations, 100.00% prevalence versus
86.36%, enrichment 1.1579, effect size 0.7565, and adjusted p-value 0.032692. This is
an association in reconstructed data, not a production rule.

## 7. Large-Winner DNA Results

Strong-winner associations included BUY entry timing, HIGH confidence, long-trade
permission, and strategy score at or above 75. Each occurred in 9 of 34 matched strong
winners versus 3 of 34 matched controls, enrichment 3.0000. Their adjusted p-value was
0.129672, so none survived the controlled evidence threshold.

## 8. Loser DNA Results

The strongest ordinary-loser association was stop distance at or below 10% among
small losers: 186 of 339 observations versus 139 of 339 controls, enrichment 1.3381,
effect size 0.2784, adjusted p-value 0.001532, and stable temporal classification.
This should be tested as a stop-structure hypothesis only after authoritative event
data exist; it must not be interpreted as evidence that tighter stops cause losses.

## 9. Catastrophic-Loss DNA Results

SELL verdict and REJECT confidence were enriched 1.8125 times in catastrophic losses
and 2.9459 times in high-MAE failures. These fields are closely related decision
outputs and are retained with lineage awareness. AVOID timing was enriched 1.2222 in
catastrophic losses. The result shows that Alpha often identified damaged candidates;
it does not establish a tradable short strategy.

## 10. Missed-Opportunity DNA Results

Profitable rejected candidates were enriched for stop distance at or below 10%
(1.7037, adjusted p-value 0.000425), score at or above 40 (1.1176, adjusted p-value
0.001162), and price component at or above 0.65 (1.1558, adjusted p-value 0.003409).
The 5% stop-distance condition had 8.5000 enrichment but only 17 condition matches,
making concentration and threshold fragility especially important. No approval gate
was changed.

## 11. Matched-Cohort Results

Matching is deterministic by recorded horizon, setup family, and calendar year. The
16 cohorts produced 2,820 matched pairs and 523 unmatched cohort observations. The
largest limitation is the high-MAE cohort, where 435 of 951 observations could not be
matched under the fixed contract. Findings retain this limitation rather than falling
back silently.

## 12. Individual Feature Enrichment Leaderboard

| Outcome | Condition | Enrichment | Adjusted p | Stability |
|---|---|---:|---:|---|
| Moderate winners | `price_component >= 0.65` | 1.1579 | 0.032692 | STABLE |
| Small losers | `stop_distance_pct <= 10` | 1.3381 | 0.001532 | STABLE |
| Catastrophic losers | `final_verdict == SELL` | 1.8125 | 0.000000 | WEAKENING |
| High-MAE failures | `final_verdict == SELL` | 2.9459 | 0.000000 | STABLE |
| Profitable rejected | `stop_distance_pct <= 10` | 1.7037 | 0.000425 | STABLE |
| Profitable rejected | `strategy_score >= 40` | 1.1176 | 0.001162 | STABLE |

## 13. Interaction Leaderboard

The search tested a bounded, deterministic set and retained 50 records after minimum
cell checks. The leading interaction was `confidence == REJECT` plus
`final_verdict == SELL` for catastrophic losers: sample 195, enrichment 3.6457,
adjusted p-value 0.000000, and 90.91% fold consistency. The leading winner interaction
was `price_component >= 0.65` plus `strategy_score >= 40`: sample 33, enrichment
1.5740, adjusted p-value 0.000625, 100% fold consistency, and an explicit lineage
penalty. No interaction was promoted to a strategy hypothesis.

## 14. Cluster Discovery Results

Three clusters were formed using only pre-trade features; outcomes were attached only
after assignment. Cluster sizes were 402, 461, and 504. Their winner rates were 5.97%,
10.63%, and 28.97%, while average net returns were -27.16%, -17.13%, and -6.77%.
All three remain descriptive profiles, not strategies.

## 15. Hierarchical DNA Results

Universal, setup, and horizon scopes were evaluated. Groups below the minimum sample
contract report `NOT_ESTIMABLE`. Sector and regime hierarchy reports no population
because those features are quarantined. Large setup and 20-day subgroups contain
reconstructed associations, but no explicit outside-subgroup generalisation test or
authoritative holdout exists, so they remain research-only.

## 16. Temporal Stability Results

The engine labelled 399 tested records stable before applying the complete status
hierarchy. Stability uses chronological folds and early/late consistency; it never
rewrites earlier observations using current-period strength.

## 17. Concentration and Fragility

Ninety-eight patterns were classified `CONCENTRATED`. The engine measures symbol,
setup, year, and fold concentration. Concentrated, lineage-confounded, unstable, and
small-cell records cannot become strategy hypotheses even if their p-values are low.

## 18. Multiple-Testing Results

- Procedure: Benjamini-Hochberg FDR by feature and interaction family
- Hypotheses tested: 1,031
- Surviving family-level correction: 370
- Rejected after correction: 661

Surviving FDR is necessary but not sufficient. Evidence class, sample size, lineage,
stability, concentration, and holdout requirements are applied afterward.

## 19. Accepted and Rejected DNA Patterns

Final immutable status counts:

- `INSUFFICIENT_SAMPLE`: 453
- `MULTIPLE_TESTING_FAILURE`: 370
- `CONCENTRATED`: 98
- `RECONSTRUCTED_RESEARCH_ONLY`: 82
- `UNSTABLE`: 21
- `LINEAGE_CONFOUNDED`: 7

There were no `STRATEGY_HYPOTHESIS_CANDIDATE` records. Rejected findings are retained
in the registry and deterministic exports.

## 20. Generated Strategy Hypotheses

Generated hypotheses: 0. No pattern met the combined evidence, stability,
concentration, lineage, and holdout contract.

## 21. Strategy Lab Publication Specification

No specification was published. The publication command rejects unknown or ineligible
IDs. A synthetic authoritative candidate is covered in tests and produces an inert,
versioned specification with `execute_automatically=false` and
`production_influence=false`.

## 22. Research Registry Entry

Latest entry:

- ID: `market-dna-edf02ac74e1b184de7ee8e84`
- Subsystem: `MARKET_DNA`
- Status: `COMPLETED`
- Decision: `INCONCLUSIVE`
- Statistical confidence: `LOW`
- Evidence: cohort enrichment, effect size, false-discovery adjustment, temporal
  stability, and concentration
- Production influence: false

## 23. IRD Roadmap Impact

IRD registers `market-dna-discovery` as an available diagnostic with schema
`market-dna-v1.2`. It adds a P2 evidence project: acquire authoritative completed
outcomes with corporate-action-complete chronological bars and an untouched holdout.
The roadmap cites 1,031 tested patterns, zero governed hypotheses, and
`NO_ROBUST_MARKET_DNA_FOUND`. It does not report reconstructed evidence as measured
forward ROI.

## 24. CLI Outputs

All commands completed deterministically against the same report ID.
The complete verbatim outputs and exit codes for all 12 commands are retained in
`docs/MARKET_DNA_CLI_TRANSCRIPT.md`; the decision-relevant transcript is reproduced
below for readability.

```text
$ poetry run python -m alpha market-dna inventory
Market DNA Point-in-Time Feature Inventory
Features Registered: 21
Usable: 11
Usable With Caution: 4
Quarantined: 6
Future outcomes are retained as labels only and cannot enter discovery features.
PRODUCTION_INFLUENCE=false

$ poetry run python -m alpha market-dna cohorts
Market DNA Versioned Outcome Cohorts
Cohorts Registered: 16
Market DNA Cohort Population Report
Dataset: strategy-discovery-v1-reconstructed-ea5acfc503940ed1
Strong winners: sample=34; matched pairs=34; unmatched=0
Moderate winners: sample=45; matched pairs=44; unmatched=1
Small winners: sample=140; matched pairs=139; unmatched=1
Flat outcomes: sample=69; matched pairs=69; unmatched=0
Small losers: sample=342; matched pairs=339; unmatched=3
Large losers: sample=511; matched pairs=490; unmatched=21
Catastrophic losers: sample=359; matched pairs=304; unmatched=55
High-MFE opportunities: sample=123; matched pairs=122; unmatched=1
High-MAE failures: sample=951; matched pairs=516; unmatched=435
Profitable rejected: sample=198; matched pairs=196; unmatched=2
Approved profitable: sample=21; matched pairs=21; unmatched=0
Approved unprofitable: sample=46; matched pairs=46; unmatched=0
Missed-entry winners: sample=184; matched pairs=182; unmatched=2
Stop-hit then recovered: sample=57; matched pairs=57; unmatched=0
Target achieved: sample=64; matched pairs=64; unmatched=0
Time expired: sample=199; matched pairs=197; unmatched=2
PRODUCTION_INFLUENCE=false

$ poetry run python -m alpha market-dna discover
Market DNA Outcome-First Discovery
Report: market-dna-edf02ac74e1b184de7ee8e84
Dataset: strategy-discovery-v1-reconstructed-ea5acfc503940ed1
Evidence Class: RECONSTRUCTED
Rows Analysed: 1500
Outcome Cohorts: 16
Feature Conditions and Interactions Tested: 1031
Findings Surviving FDR: 370
Pattern Statuses: CONCENTRATED=98; INSUFFICIENT_SAMPLE=453;
LINEAGE_CONFOUNDED=7; MULTIPLE_TESTING_FAILURE=370;
RECONSTRUCTED_RESEARCH_ONLY=82; UNSTABLE=21
Strategy Hypotheses: 0
Conclusion: NO_ROBUST_MARKET_DNA_FOUND
No holdout or causal claim is made from the discovery population.
PRODUCTION_INFLUENCE=false

$ poetry run python -m alpha market-dna winners
Market DNA Winner Characteristics
1. price_component >= 0.65; cohort=MODERATE_WINNERS; population=44;
   condition matches=44; enrichment=1.1579; adjusted p=0.032692; STABLE
2. strategy_score >= 40; cohort=MODERATE_WINNERS; population=44;
   condition matches=44; enrichment=1.1282; adjusted p=0.057892; EMERGING
3. entry_timing_state == BUY; cohort=STRONG_WINNERS; population=34;
   condition matches=9; enrichment=3.0000; adjusted p=0.129672; STABLE
Associations are not causal; reconstructed findings remain research-only.
PRODUCTION_INFLUENCE=false

$ poetry run python -m alpha market-dna losers
Market DNA Loser Characteristics
1. stop_distance_pct <= 10; cohort=SMALL_LOSERS; population=339;
   condition matches=186; enrichment=1.3381; adjusted p=0.001532; STABLE
2. price_component >= 0.65; cohort=SMALL_LOSERS; population=339;
   condition matches=280; enrichment=1.1200; adjusted p=0.017575; EMERGING
3. long_trade_permission == false; cohort=LARGE_LOSERS; population=490;
   condition matches=465; enrichment=1.0497; adjusted p=0.022433; EMERGING
Associations are not causal; reconstructed findings remain research-only.
PRODUCTION_INFLUENCE=false

$ poetry run python -m alpha market-dna catastrophic-losses
Market DNA Catastrophic-Loss Characteristics
1. final_verdict == SELL; cohort=CATASTROPHIC_LOSERS; population=304;
   condition matches=145; enrichment=1.8125; adjusted p=0.000000; WEAKENING
2. confidence == REJECT; cohort=CATASTROPHIC_LOSERS; population=304;
   condition matches=145; enrichment=1.8125; adjusted p=0.000000; WEAKENING
3. final_verdict == SELL; cohort=HIGH_MAE_FAILURES; population=516;
   condition matches=109; enrichment=2.9459; adjusted p=0.000000; STABLE
Associations are not causal; reconstructed findings remain research-only.
PRODUCTION_INFLUENCE=false

$ poetry run python -m alpha market-dna missed-opportunities
Market DNA Missed-Opportunity Characteristics
1. long_trade_permission == false; cohort=MISSED_ENTRY_WINNERS; population=182;
   condition matches=182; enrichment=1.2133; adjusted p=0.000000; STABLE
2. raw_approved == false; cohort=MISSED_ENTRY_WINNERS; population=182;
   condition matches=182; enrichment=1.1235; adjusted p=0.000033; EMERGING
3. stop_distance_pct <= 10; cohort=MISSED_ENTRY_WINNERS; population=182;
   condition matches=89; enrichment=1.7115; adjusted p=0.000410; STABLE
4. stop_distance_pct <= 10; cohort=PROFITABLE_REJECTED; population=196;
   condition matches=92; enrichment=1.7037; adjusted p=0.000425; STABLE
Associations are not causal; reconstructed findings remain research-only.
PRODUCTION_INFLUENCE=false

$ poetry run python -m alpha market-dna interactions
Market DNA Bounded Interaction Discovery
Interactions Retained After Minimum-Cell Checks: 50
- confidence == REJECT + final_verdict == SELL; cohort=CATASTROPHIC_LOSERS;
  sample=195; enrichment=3.6457; adjusted p=0.000000; folds=90.91%
- price_component >= 0.65 + strategy_score >= 40; cohort=STRONG_WINNERS;
  sample=33; enrichment=1.5740; adjusted p=0.000625; lineage penalty=True
Search is bounded and deterministic; no unrestricted interaction mining occurred.
PRODUCTION_INFLUENCE=false

$ poetry run python -m alpha market-dna hierarchy
Market DNA Hierarchical and Cluster Discovery
- UNIVERSAL: population=1500; enrichment=2.9459
- SETUP:MOMENTUM CONTINUATION: population=1345; enrichment=23.6287
- HORIZON:20d: population=1411; enrichment=24.8723
- SECTOR_AND_REGIME: population=0; strongest=NOT_ESTIMABLE
Feature-Only Clusters: DNA_CLUSTER_01=402; DNA_CLUSTER_02=461;
DNA_CLUSTER_03=504
Subgroup results require outside-group comparison and remain reconstructed.
Clusters are descriptive profiles, not strategies.
PRODUCTION_INFLUENCE=false

$ poetry run python -m alpha market-dna hypotheses
Market DNA Governed Strategy Hypotheses
Hypotheses Generated: 0
No pattern met the evidence, stability, concentration, and holdout requirements.
Publication creates an inert Strategy Lab specification and never executes it.
PRODUCTION_INFLUENCE=false

$ poetry run python -m alpha market-dna publish-hypothesis \
    --hypothesis DNA_HYPOTHESIS_DOES_NOT_EXIST
Invalid value: hypothesis is not an eligible registered candidate

$ poetry run python -m alpha market-dna report
Project Alpha Market DNA Discovery Report
Report: market-dna-edf02ac74e1b184de7ee8e84
Dataset / Evidence: strategy-discovery-v1-reconstructed-ea5acfc503940ed1 / RECONSTRUCTED
Rows / Excluded: 1500 / 46
Outcome Cohorts Evaluated: 16
Features: usable=11; cautious=4; quarantined=6
Statistical Control: tested=1031; surviving=370; rejected=661
Temporal Stability: stable patterns=399
Concentration / Fragility: concentrated patterns=98
Bounded Interactions Retained: 50
Descriptive Clusters: 3
Strategy Hypotheses Generated: 0
Final Conclusion: NO_ROBUST_MARKET_DNA_FOUND
Highest-Value Missing Evidence: Authoritative completed outcomes with
corporate-action-complete chronological bars and a genuinely untouched holdout.
No DNA score was added to recommendations, approval, allocation, or execution.
PRODUCTION_INFLUENCE=false
```

Deterministic full-fidelity exports were also generated:

- JSON: 6.4 MB
- CSV: 757 KB

Both contain accepted and rejected records and preserve production influence false.

## 25. Quality Gates

Focused Market DNA and IRD tests passed before the full-suite run. The final gate
results are recorded here after completion:

- `poetry run pytest -q`: 1,645 passed in 186.84 seconds
- `poetry run ruff check .`: all checks passed
- `poetry run mypy alpha`: no issues in 471 source files
- `poetry build`: sdist and wheel built successfully

## 26. Production Isolation Confirmation

Recommendation, approval, allocation, execution, live trading, and forward cohorts
were not changed by this milestone. `APPROVAL_POLICY_V1` is unchanged. Market DNA is
reachable only from its CLI and research diagnostic registration. No DNA match score
is exposed to live output.

`PRODUCTION_INFLUENCE=false`.
