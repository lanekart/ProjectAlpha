# Market DNA CLI Transcript

Generated from the deterministic default research registry. The publication failure is expected and demonstrates fail-closed behavior.

## `poetry run python -m alpha market-dna inventory`

```text
Market DNA Point-in-Time Feature Inventory
Features Registered: 21
Usable: 11
Usable With Caution: 4
Quarantined: 6
- strategy_score: CONTINUOUS; quality=USABLE; unit=points; source=candidate decision record
- final_verdict: CATEGORICAL; quality=USABLE; unit=category; source=candidate decision record
- raw_approved: BOOLEAN; quality=USABLE; unit=boolean; source=candidate decision record
- confidence: CATEGORICAL; quality=USABLE; unit=category; source=candidate decision record
- data_quality: CATEGORICAL; quality=USABLE; unit=category; source=candidate decision record
- setup_type: CATEGORICAL; quality=USABLE; unit=category; source=candidate decision record
- entry_timing_state: CATEGORICAL; quality=USABLE; unit=category; source=candidate decision record
- long_trade_permission: BOOLEAN; quality=USABLE; unit=boolean; source=candidate decision record
- complete_trade_plan: BOOLEAN; quality=USABLE; unit=boolean; source=candidate decision record
- entry_price: CONTINUOUS; quality=USABLE_WITH_CAUTION; unit=INR; source=candidate decision record
- stop_distance_pct: CONTINUOUS; quality=USABLE; unit=percent; source=candidate decision record
- reward_risk: CONTINUOUS; quality=USABLE; unit=ratio; source=candidate decision record
- price_component: CONTINUOUS; quality=USABLE_WITH_CAUTION; unit=normalized score; source=candidate_learning.CandidateDecisionRecord.indicator_scores
- volume_component: CONTINUOUS; quality=USABLE_WITH_CAUTION; unit=normalized score; source=candidate_learning.CandidateDecisionRecord.indicator_scores
- candle_component: CONTINUOUS; quality=USABLE_WITH_CAUTION; unit=normalized score; source=candidate_learning.CandidateDecisionRecord.indicator_scores
- retracement_component: CATEGORICAL; quality=QUARANTINED; unit=normalized score; source=candidate_learning.CandidateDecisionRecord.indicator_scores
  Limitation: Previously inversely predictive; calibration direction is unresolved.
- market_regime: CATEGORICAL; quality=QUARANTINED; unit=category; source=candidate market-state snapshot
  Limitation: Reference-label scale defect invalidates predictive-quality evidence.
- sector: CATEGORICAL; quality=QUARANTINED; unit=category; source=historical sector membership
  Limitation: Authoritative point-in-time historical sector membership is unavailable.
- realised_return_pct: CATEGORICAL; quality=QUARANTINED; unit=percent; source=future outcome window
  Limitation: Future-derived outcome fields cannot be discovery features.
- mfe_pct: CATEGORICAL; quality=QUARANTINED; unit=percent; source=future outcome window
  Limitation: Future-derived outcome fields cannot be discovery features.
- mae_pct: CATEGORICAL; quality=QUARANTINED; unit=percent; source=future outcome window
  Limitation: Future-derived outcome fields cannot be discovery features.
Future outcomes are retained as labels only and cannot enter discovery features.
PRODUCTION_INFLUENCE=false

Exit code: 0
```

## `poetry run python -m alpha market-dna cohorts`

```text
Market DNA Versioned Outcome Cohorts
Cohorts Registered: 16
- STRONG_WINNERS: Strong winners
  Predicate: net_return_pct >= 20
  Horizon: PRIMARY_RECORDED_HORIZON | Cost Profile: strategy-lab-execution-v1-30bps
- MODERATE_WINNERS: Moderate winners
  Predicate: 10 <= net_return_pct < 20
  Horizon: PRIMARY_RECORDED_HORIZON | Cost Profile: strategy-lab-execution-v1-30bps
- SMALL_WINNERS: Small winners
  Predicate: 1 < net_return_pct < 10
  Horizon: PRIMARY_RECORDED_HORIZON | Cost Profile: strategy-lab-execution-v1-30bps
- FLAT_OUTCOMES: Flat outcomes
  Predicate: -1 <= net_return_pct <= 1
  Horizon: PRIMARY_RECORDED_HORIZON | Cost Profile: strategy-lab-execution-v1-30bps
- SMALL_LOSERS: Small losers
  Predicate: -10 < net_return_pct < -1
  Horizon: PRIMARY_RECORDED_HORIZON | Cost Profile: strategy-lab-execution-v1-30bps
- LARGE_LOSERS: Large losers
  Predicate: -25 < net_return_pct <= -10
  Horizon: PRIMARY_RECORDED_HORIZON | Cost Profile: strategy-lab-execution-v1-30bps
- CATASTROPHIC_LOSERS: Catastrophic losers
  Predicate: net_return_pct <= -25
  Horizon: PRIMARY_RECORDED_HORIZON | Cost Profile: strategy-lab-execution-v1-30bps
- HIGH_MFE_OPPORTUNITIES: High-MFE opportunities
  Predicate: mfe_pct >= 15
  Horizon: PRIMARY_RECORDED_HORIZON | Cost Profile: strategy-lab-execution-v1-30bps
- HIGH_MAE_FAILURES: High-MAE failures
  Predicate: mae_pct <= -15
  Horizon: PRIMARY_RECORDED_HORIZON | Cost Profile: strategy-lab-execution-v1-30bps
- PROFITABLE_REJECTED: Profitable rejected candidates
  Predicate: raw_approved == false and net_return_pct > 1
  Horizon: PRIMARY_RECORDED_HORIZON | Cost Profile: strategy-lab-execution-v1-30bps
- APPROVED_PROFITABLE: Approved profitable candidates
  Predicate: raw_approved == true and net_return_pct > 1
  Horizon: PRIMARY_RECORDED_HORIZON | Cost Profile: strategy-lab-execution-v1-30bps
- APPROVED_UNPROFITABLE: Approved unprofitable candidates
  Predicate: raw_approved == true and net_return_pct <= 0
  Horizon: PRIMARY_RECORDED_HORIZON | Cost Profile: strategy-lab-execution-v1-30bps
- MISSED_ENTRY_WINNERS: Missed-entry winner proxies
  Predicate: entry_missed_proxy == true and net_return_pct > 1
  Horizon: PRIMARY_RECORDED_HORIZON | Cost Profile: strategy-lab-execution-v1-30bps
- STOP_HIT_THEN_RECOVERED: Stop-hit then recovered proxies
  Predicate: stop_touched == true and net_return_pct > 1
  Horizon: PRIMARY_RECORDED_HORIZON | Cost Profile: strategy-lab-execution-v1-30bps
- TARGET_ACHIEVED: Target-achieved proxies
  Predicate: target_1_touched == true
  Horizon: PRIMARY_RECORDED_HORIZON | Cost Profile: strategy-lab-execution-v1-30bps
- TIME_EXPIRED: Time-expired proxies
  Predicate: target_1_touched == false and stop_touched == false
  Horizon: PRIMARY_RECORDED_HORIZON | Cost Profile: strategy-lab-execution-v1-30bps
PRODUCTION_INFLUENCE=false
Market DNA Cohort Population Report
Dataset: strategy-discovery-v1-reconstructed-ea5acfc503940ed1
- STRONG_WINNERS: sample=34; symbols=26; average net return=44.11%; matched pairs=34; unmatched=0
  Predicate: net_return_pct >= 20
- MODERATE_WINNERS: sample=45; symbols=31; average net return=13.74%; matched pairs=44; unmatched=1
  Predicate: 10 <= net_return_pct < 20
- SMALL_WINNERS: sample=140; symbols=69; average net return=4.84%; matched pairs=139; unmatched=1
  Predicate: 1 < net_return_pct < 10
- FLAT_OUTCOMES: sample=69; symbols=39; average net return=-0.05%; matched pairs=69; unmatched=0
  Predicate: -1 <= net_return_pct <= 1
- SMALL_LOSERS: sample=342; symbols=101; average net return=-5.84%; matched pairs=339; unmatched=3
  Predicate: -10 < net_return_pct < -1
- LARGE_LOSERS: sample=511; symbols=128; average net return=-16.70%; matched pairs=490; unmatched=21
  Predicate: -25 < net_return_pct <= -10
- CATASTROPHIC_LOSERS: sample=359; symbols=121; average net return=-43.45%; matched pairs=304; unmatched=55
  Predicate: net_return_pct <= -25
- HIGH_MFE_OPPORTUNITIES: sample=123; symbols=73; average net return=16.16%; matched pairs=122; unmatched=1
  Predicate: mfe_pct >= 15
- HIGH_MAE_FAILURES: sample=951; symbols=223; average net return=-25.12%; matched pairs=516; unmatched=435
  Predicate: mae_pct <= -15
- PROFITABLE_REJECTED: sample=198; symbols=95; average net return=11.98%; matched pairs=196; unmatched=2
  Predicate: raw_approved == false and net_return_pct > 1
- APPROVED_PROFITABLE: sample=21; symbols=14; average net return=20.15%; matched pairs=21; unmatched=0
  Predicate: raw_approved == true and net_return_pct > 1
- APPROVED_UNPROFITABLE: sample=46; symbols=36; average net return=-13.44%; matched pairs=46; unmatched=0
  Predicate: raw_approved == true and net_return_pct <= 0
- MISSED_ENTRY_WINNERS: sample=184; symbols=93; average net return=10.96%; matched pairs=182; unmatched=2
  Predicate: entry_missed_proxy == true and net_return_pct > 1
- STOP_HIT_THEN_RECOVERED: sample=57; symbols=32; average net return=6.91%; matched pairs=57; unmatched=0
  Predicate: stop_touched == true and net_return_pct > 1
- TARGET_ACHIEVED: sample=64; symbols=39; average net return=25.75%; matched pairs=64; unmatched=0
  Predicate: target_1_touched == true
- TIME_EXPIRED: sample=199; symbols=104; average net return=-0.75%; matched pairs=197; unmatched=2
  Predicate: target_1_touched == false and stop_touched == false
PRODUCTION_INFLUENCE=false

Exit code: 0
```

## `poetry run python -m alpha market-dna discover`

```text
Market DNA Outcome-First Discovery
Report: market-dna-edf02ac74e1b184de7ee8e84
Dataset: strategy-discovery-v1-reconstructed-ea5acfc503940ed1
Evidence Class: RECONSTRUCTED
Rows Analysed: 1500
Outcome Cohorts: 16
Feature Conditions and Interactions Tested: 1031
Findings Surviving FDR: 370
Pattern Statuses:
- CONCENTRATED: 98
- INSUFFICIENT_SAMPLE: 453
- LINEAGE_CONFOUNDED: 7
- MULTIPLE_TESTING_FAILURE: 370
- RECONSTRUCTED_RESEARCH_ONLY: 82
- UNSTABLE: 21
Strategy Hypotheses: 0
Conclusion: NO_ROBUST_MARKET_DNA_FOUND
No holdout or causal claim is made from the discovery population.
PRODUCTION_INFLUENCE=false

Exit code: 0
```

## `poetry run python -m alpha market-dna winners`

```text
Market DNA Winner Characteristics
1. price_component|GREATER_THAN_OR_EQUAL|0.65
   Cohort=MODERATE_WINNERS; population=44; condition matches=44; prevalence=100.0000% vs 86.3636%; enrichment=1.1579
   Effect=0.7565; raw p=0.011164; adjusted p=0.032692; stability=STABLE
2. strategy_score|GREATER_THAN_OR_EQUAL|40
   Cohort=MODERATE_WINNERS; population=44; condition matches=44; prevalence=100.0000% vs 88.6364%; enrichment=1.1282
   Effect=0.6877; raw p=0.021311; adjusted p=0.057892; stability=EMERGING
3. entry_timing_state|EQUAL|BUY
   Cohort=STRONG_WINNERS; population=34; condition matches=9; prevalence=26.4706% vs 8.8235%; enrichment=3.0000
   Effect=0.4776; raw p=0.056310; adjusted p=0.129672; stability=STABLE
4. confidence|EQUAL|HIGH
   Cohort=STRONG_WINNERS; population=34; condition matches=9; prevalence=26.4706% vs 8.8235%; enrichment=3.0000
   Effect=0.4776; raw p=0.056310; adjusted p=0.129672; stability=STABLE
5. long_trade_permission|EQUAL|true
   Cohort=STRONG_WINNERS; population=34; condition matches=9; prevalence=26.4706% vs 8.8235%; enrichment=3.0000
   Effect=0.4776; raw p=0.056310; adjusted p=0.129672; stability=STABLE
6. strategy_score|GREATER_THAN_OR_EQUAL|75
   Cohort=STRONG_WINNERS; population=34; condition matches=9; prevalence=26.4706% vs 8.8235%; enrichment=3.0000
   Effect=0.4776; raw p=0.056310; adjusted p=0.129672; stability=STABLE
7. final_verdict|EQUAL|BUY
   Cohort=STRONG_WINNERS; population=34; condition matches=7; prevalence=20.5882% vs 5.8824%; enrichment=3.5000
   Effect=0.4520; raw p=0.073570; adjusted p=0.164028; stability=STABLE
8. strategy_score|GREATER_THAN_OR_EQUAL|40
   Cohort=STRONG_WINNERS; population=34; condition matches=34; prevalence=100.0000% vs 91.1765%; enrichment=1.0968
   Effect=0.6032; raw p=0.076466; adjusted p=0.168949; stability=EMERGING
9. candle_component|GREATER_THAN_OR_EQUAL|0.65
   Cohort=MODERATE_WINNERS; population=44; condition matches=31; prevalence=70.4545% vs 52.2727%; enrichment=1.3478
   Effect=0.3760; raw p=0.079870; adjusted p=0.173346; stability=UNSTABLE
10. volume_component|GREATER_THAN_OR_EQUAL|0.65
   Cohort=STRONG_WINNERS; population=34; condition matches=18; prevalence=52.9412% vs 32.3529%; enrichment=1.6364
   Effect=0.4196; raw p=0.086087; adjusted p=0.182007; stability=STABLE
Associations are not causal; reconstructed findings remain research-only.
PRODUCTION_INFLUENCE=false

Exit code: 0
```

## `poetry run python -m alpha market-dna losers`

```text
Market DNA Loser Characteristics
1. stop_distance_pct|LESS_THAN_OR_EQUAL|10
   Cohort=SMALL_LOSERS; population=339; condition matches=186; prevalence=54.8673% vs 41.0029%; enrichment=1.3381
   Effect=0.2784; raw p=0.000303; adjusted p=0.001532; stability=STABLE
2. price_component|GREATER_THAN_OR_EQUAL|0.65
   Cohort=SMALL_LOSERS; population=339; condition matches=280; prevalence=82.5959% vs 73.7463%; enrichment=1.1200
   Effect=0.2152; raw p=0.005285; adjusted p=0.017575; stability=EMERGING
3. long_trade_permission|EQUAL|false
   Cohort=LARGE_LOSERS; population=490; condition matches=465; prevalence=94.8980% vs 90.4082%; enrichment=1.0497
   Effect=0.1741; raw p=0.007069; adjusted p=0.022433; stability=EMERGING
4. raw_approved|EQUAL|false
   Cohort=LARGE_LOSERS; population=490; condition matches=473; prevalence=96.5306% vs 92.8571%; enrichment=1.0396
   Effect=0.1664; raw p=0.010314; adjusted p=0.030661; stability=EMERGING
5. price_component|GREATER_THAN_OR_EQUAL|0.55
   Cohort=SMALL_LOSERS; population=339; condition matches=324; prevalence=95.5752% vs 92.0354%; enrichment=1.0385
   Effect=0.1483; raw p=0.055902; adjusted p=0.129672; stability=EMERGING
6. stop_distance_pct|LESS_THAN_OR_EQUAL|5
   Cohort=SMALL_LOSERS; population=339; condition matches=25; prevalence=7.3746% vs 4.4248%; enrichment=1.6667
   Effect=0.1262; raw p=0.103112; adjusted p=0.212506; stability=WEAKENING
7. strategy_score|GREATER_THAN_OR_EQUAL|40
   Cohort=SMALL_LOSERS; population=339; condition matches=301; prevalence=88.7906% vs 84.9558%; enrichment=1.0451
   Effect=0.1138; raw p=0.139288; adjusted p=0.265840; stability=STABLE
8. entry_timing_state|EQUAL|AVOID
   Cohort=LARGE_LOSERS; population=490; condition matches=334; prevalence=68.1633% vs 63.6735%; enrichment=1.0705
   Effect=0.0948; raw p=0.138161; adjusted p=0.265840; stability=WEAKENING
9. confidence|EQUAL|LOW
   Cohort=LARGE_LOSERS; population=490; condition matches=226; prevalence=46.1224% vs 41.4286%; enrichment=1.1133
   Effect=0.0947; raw p=0.138624; adjusted p=0.265840; stability=WEAKENING
10. final_verdict|EQUAL|AVOID
   Cohort=LARGE_LOSERS; population=490; condition matches=226; prevalence=46.1224% vs 41.4286%; enrichment=1.1133
   Effect=0.0947; raw p=0.138624; adjusted p=0.265840; stability=WEAKENING
Associations are not causal; reconstructed findings remain research-only.
PRODUCTION_INFLUENCE=false

Exit code: 0
```

## `poetry run python -m alpha market-dna catastrophic-losses`

```text
Market DNA Catastrophic-Loss Characteristics
1. final_verdict|EQUAL|SELL
   Cohort=CATASTROPHIC_LOSERS; population=304; condition matches=145; prevalence=47.6974% vs 26.3158%; enrichment=1.8125
   Effect=0.4474; raw p=0.000000; adjusted p=0.000000; stability=WEAKENING
2. confidence|EQUAL|REJECT
   Cohort=CATASTROPHIC_LOSERS; population=304; condition matches=145; prevalence=47.6974% vs 26.3158%; enrichment=1.8125
   Effect=0.4474; raw p=0.000000; adjusted p=0.000000; stability=WEAKENING
3. final_verdict|EQUAL|SELL
   Cohort=HIGH_MAE_FAILURES; population=516; condition matches=109; prevalence=21.1240% vs 7.1705%; enrichment=2.9459
   Effect=0.4129; raw p=0.000000; adjusted p=0.000000; stability=STABLE
4. confidence|EQUAL|REJECT
   Cohort=HIGH_MAE_FAILURES; population=516; condition matches=109; prevalence=21.1240% vs 7.1705%; enrichment=2.9459
   Effect=0.4129; raw p=0.000000; adjusted p=0.000000; stability=STABLE
5. entry_timing_state|EQUAL|AVOID
   Cohort=HIGH_MAE_FAILURES; population=516; condition matches=365; prevalence=70.7364% vs 53.2946%; enrichment=1.3273
   Effect=0.3617; raw p=0.000000; adjusted p=0.000000; stability=WEAKENING
6. entry_timing_state|EQUAL|AVOID
   Cohort=CATASTROPHIC_LOSERS; population=304; condition matches=253; prevalence=83.2237% vs 68.0921%; enrichment=1.2222
   Effect=0.3565; raw p=0.000014; adjusted p=0.000102; stability=EMERGING
7. long_trade_permission|EQUAL|false
   Cohort=HIGH_MAE_FAILURES; population=516; condition matches=493; prevalence=95.5426% vs 88.9535%; enrichment=1.0741
   Effect=0.2522; raw p=0.000076; adjusted p=0.000433; stability=STABLE
8. raw_approved|EQUAL|false
   Cohort=HIGH_MAE_FAILURES; population=516; condition matches=500; prevalence=96.8992% vs 92.6357%; enrichment=1.0460
   Effect=0.1956; raw p=0.002102; adjusted p=0.007781; stability=EMERGING
9. reward_risk|GREATER_THAN_OR_EQUAL|2
   Cohort=HIGH_MAE_FAILURES; population=516; condition matches=467; prevalence=90.5039% vs 84.3023%; enrichment=1.0736
   Effect=0.1882; raw p=0.002682; adjusted p=0.009673; stability=STABLE
10. reward_risk|GREATER_THAN_OR_EQUAL|1.5
   Cohort=HIGH_MAE_FAILURES; population=516; condition matches=467; prevalence=90.5039% vs 84.3023%; enrichment=1.0736
   Effect=0.1882; raw p=0.002682; adjusted p=0.009673; stability=STABLE
Associations are not causal; reconstructed findings remain research-only.
PRODUCTION_INFLUENCE=false

Exit code: 0
```

## `poetry run python -m alpha market-dna missed-opportunities`

```text
Market DNA Missed-Opportunity Characteristics
1. long_trade_permission|EQUAL|false
   Cohort=MISSED_ENTRY_WINNERS; population=182; condition matches=182; prevalence=100.0000% vs 82.4176%; enrichment=1.2133
   Effect=0.8654; raw p=0.000000; adjusted p=0.000000; stability=STABLE
2. raw_approved|EQUAL|false
   Cohort=MISSED_ENTRY_WINNERS; population=182; condition matches=182; prevalence=100.0000% vs 89.0110%; enrichment=1.1235
   Effect=0.6758; raw p=0.000004; adjusted p=0.000033; stability=EMERGING
3. stop_distance_pct|LESS_THAN_OR_EQUAL|10
   Cohort=MISSED_ENTRY_WINNERS; population=182; condition matches=89; prevalence=48.9011% vs 28.5714%; enrichment=1.7115
   Effect=0.4209; raw p=0.000069; adjusted p=0.000410; stability=STABLE
4. stop_distance_pct|LESS_THAN_OR_EQUAL|10
   Cohort=PROFITABLE_REJECTED; population=196; condition matches=92; prevalence=46.9388% vs 27.5510%; enrichment=1.7037
   Effect=0.4044; raw p=0.000072; adjusted p=0.000425; stability=STABLE
5. strategy_score|GREATER_THAN_OR_EQUAL|40
   Cohort=PROFITABLE_REJECTED; population=196; condition matches=190; prevalence=96.9388% vs 86.7347%; enrichment=1.1176
   Effect=0.3938; raw p=0.000225; adjusted p=0.001162; stability=STABLE
6. confidence|EQUAL|MEDIUM
   Cohort=MISSED_ENTRY_WINNERS; population=182; condition matches=75; prevalence=41.2088% vs 23.6264%; enrichment=1.7442
   Effect=0.3789; raw p=0.000339; adjusted p=0.001697; stability=STABLE
7. final_verdict|EQUAL|WATCHLIST
   Cohort=MISSED_ENTRY_WINNERS; population=182; condition matches=75; prevalence=41.2088% vs 23.6264%; enrichment=1.7442
   Effect=0.3789; raw p=0.000339; adjusted p=0.001697; stability=STABLE
8. stop_distance_pct|LESS_THAN_OR_EQUAL|5
   Cohort=PROFITABLE_REJECTED; population=196; condition matches=17; prevalence=8.6735% vs 1.0204%; enrichment=8.5000
   Effect=0.3955; raw p=0.000419; adjusted p=0.001995; stability=STABLE
9. stop_distance_pct|LESS_THAN_OR_EQUAL|5
   Cohort=MISSED_ENTRY_WINNERS; population=182; condition matches=16; prevalence=8.7912% vs 1.0989%; enrichment=8.0000
   Effect=0.3920; raw p=0.000713; adjusted p=0.003253; stability=STABLE
10. price_component|GREATER_THAN_OR_EQUAL|0.65
   Cohort=PROFITABLE_REJECTED; population=196; condition matches=178; prevalence=90.8163% vs 78.5714%; enrichment=1.1558
   Effect=0.3468; raw p=0.000761; adjusted p=0.003409; stability=WEAKENING
Associations are not causal; reconstructed findings remain research-only.
PRODUCTION_INFLUENCE=false

Exit code: 0
```

## `poetry run python -m alpha market-dna interactions`

```text
Market DNA Bounded Interaction Discovery
Interactions Retained After Minimum-Cell Checks: 50
- DNA_INTERACTION_44A14334FDF23C87: confidence|EQUAL|REJECT, final_verdict|EQUAL|SELL
  Cohort=CATASTROPHIC_LOSERS; sample=195; enrichment=3.6457; adjusted p=0.000000; fold consistency=90.91%; lineage penalty=False
- DNA_INTERACTION_8C34E212432361B0: price_component|GREATER_THAN_OR_EQUAL|0.65, strategy_score|GREATER_THAN_OR_EQUAL|40
  Cohort=STRONG_WINNERS; sample=33; enrichment=1.5740; adjusted p=0.000625; fold consistency=100.00%; lineage penalty=True
- DNA_INTERACTION_38AEE4A036FC4403: price_component|GREATER_THAN_OR_EQUAL|0.65, setup_type|EQUAL|MOMENTUM CONTINUATION
  Cohort=STRONG_WINNERS; sample=33; enrichment=1.5169; adjusted p=0.000900; fold consistency=100.00%; lineage penalty=False
- DNA_INTERACTION_82C9EDB578DED842: candle_component|GREATER_THAN_OR_EQUAL|0.45, strategy_score|GREATER_THAN_OR_EQUAL|40
  Cohort=STRONG_WINNERS; sample=33; enrichment=1.5025; adjusted p=0.000900; fold consistency=100.00%; lineage penalty=True
- DNA_INTERACTION_FF028C9CEF730BD6: candle_component|GREATER_THAN_OR_EQUAL|0.45, price_component|GREATER_THAN_OR_EQUAL|0.65
  Cohort=STRONG_WINNERS; sample=32; enrichment=1.5112; adjusted p=0.000900; fold consistency=100.00%; lineage penalty=True
- DNA_INTERACTION_49F69C3A3C83B760: price_component|GREATER_THAN_OR_EQUAL|0.65, reward_risk|GREATER_THAN_OR_EQUAL|2
  Cohort=STRONG_WINNERS; sample=31; enrichment=1.5542; adjusted p=0.000900; fold consistency=100.00%; lineage penalty=False
- DNA_INTERACTION_70864F8BF6098B49: complete_trade_plan|EQUAL|true, price_component|GREATER_THAN_OR_EQUAL|0.65
  Cohort=STRONG_WINNERS; sample=31; enrichment=1.5542; adjusted p=0.000900; fold consistency=100.00%; lineage penalty=False
- DNA_INTERACTION_A6B4B078A6D0B487: price_component|GREATER_THAN_OR_EQUAL|0.65, reward_risk|GREATER_THAN_OR_EQUAL|1.5
  Cohort=STRONG_WINNERS; sample=31; enrichment=1.5542; adjusted p=0.000900; fold consistency=100.00%; lineage penalty=False
- DNA_INTERACTION_BA06284D12C5BD1A: price_component|GREATER_THAN_OR_EQUAL|0.55, strategy_score|GREATER_THAN_OR_EQUAL|40
  Cohort=STRONG_WINNERS; sample=34; enrichment=1.4110; adjusted p=0.001106; fold consistency=100.00%; lineage penalty=True
- DNA_INTERACTION_32A409067A699BB2: price_component|GREATER_THAN_OR_EQUAL|0.65, reward_risk|GREATER_THAN_OR_EQUAL|3
  Cohort=STRONG_WINNERS; sample=30; enrichment=1.5510; adjusted p=0.001280; fold consistency=100.00%; lineage penalty=False
Search is bounded and deterministic; no unrestricted interaction mining occurred.
PRODUCTION_INFLUENCE=false

Exit code: 0
```

## `poetry run python -m alpha market-dna hierarchy`

```text
Market DNA Hierarchical and Cluster Discovery
- UNIVERSAL: population=1500; strongest=DNA_FINDING_BE8ED5FBDC07AC3E; enrichment=2.9459
  Limitation: Universal scope still reflects reconstructed evidence.
- SETUP:DISTRIBUTION: population=42; strongest=NOT_ESTIMABLE; enrichment=NOT_ESTIMABLE
  Limitation: Subgroup findings require an explicit outside-subgroup comparison.
- SETUP:MOMENTUM CONTINUATION: population=1345; strongest=DNA_FINDING_BA6B90801CFDB3CE; enrichment=23.6287
  Limitation: Subgroup findings require an explicit outside-subgroup comparison.
- SETUP:NO VALID SETUP: population=1; strongest=NOT_ESTIMABLE; enrichment=NOT_ESTIMABLE
  Limitation: Subgroup findings require an explicit outside-subgroup comparison.
- SETUP:TREND FAILURE: population=112; strongest=NOT_ESTIMABLE; enrichment=NOT_ESTIMABLE
  Limitation: Subgroup findings require an explicit outside-subgroup comparison.
- HORIZON:10d: population=56; strongest=NOT_ESTIMABLE; enrichment=NOT_ESTIMABLE
  Limitation: Subgroup findings require an explicit outside-subgroup comparison.
- HORIZON:1d: population=1; strongest=NOT_ESTIMABLE; enrichment=NOT_ESTIMABLE
  Limitation: Subgroup findings require an explicit outside-subgroup comparison.
- HORIZON:20d: population=1411; strongest=DNA_FINDING_8C235B731D9BD213; enrichment=24.8723
  Limitation: Subgroup findings require an explicit outside-subgroup comparison.
- HORIZON:3d: population=22; strongest=NOT_ESTIMABLE; enrichment=NOT_ESTIMABLE
  Limitation: Subgroup findings require an explicit outside-subgroup comparison.
- HORIZON:5d: population=10; strongest=NOT_ESTIMABLE; enrichment=NOT_ESTIMABLE
  Limitation: Subgroup findings require an explicit outside-subgroup comparison.
- SECTOR_AND_REGIME: population=0; strongest=NOT_ESTIMABLE; enrichment=NOT_ESTIMABLE
  Limitation: Sector is unavailable point-in-time and market regime is quarantined.
Feature-Only Clusters:
- DNA_CLUSTER_01: sample=402; winner rate=5.97%; average net return=-27.16%; profile=strategy_score=LOW, stop_distance_pct=LOW, reward_risk=LOW, price_component=MID, volume_component=MID, candle_component=MID
- DNA_CLUSTER_02: sample=461; winner rate=10.63%; average net return=-17.13%; profile=strategy_score=LOW, stop_distance_pct=LOW, reward_risk=LOW, price_component=MID, volume_component=LOW, candle_component=LOW
- DNA_CLUSTER_03: sample=504; winner rate=28.97%; average net return=-6.77%; profile=strategy_score=MID, stop_distance_pct=LOW, reward_risk=LOW, price_component=HIGH, volume_component=HIGH, candle_component=HIGH
Clusters are descriptive profiles, not strategies.
PRODUCTION_INFLUENCE=false

Exit code: 0
```

## `poetry run python -m alpha market-dna hypotheses`

```text
Market DNA Governed Strategy Hypotheses
Hypotheses Generated: 0
No pattern met the evidence, stability, concentration, and holdout requirements.
Publication creates an inert Strategy Lab specification and never executes it.
PRODUCTION_INFLUENCE=false

Exit code: 0
```

## `poetry run python -m alpha market-dna publish-hypothesis --hypothesis DNA_HYPOTHESIS_DOES_NOT_EXIST`

```text
Usage: python -m alpha market-dna publish-hypothesis [OPTIONS]
Try 'python -m alpha market-dna publish-hypothesis --help' for help.
╭─ Error ──────────────────────────────────────────────────────────────────────╮
│ Invalid value: hypothesis is not an eligible registered candidate            │
╰──────────────────────────────────────────────────────────────────────────────╯

Exit code: 2
```

## `poetry run python -m alpha market-dna report`

```text
Project Alpha Market DNA Discovery Report
Report: market-dna-edf02ac74e1b184de7ee8e84
Dataset / Evidence: strategy-discovery-v1-reconstructed-ea5acfc503940ed1 / RECONSTRUCTED
Rows / Excluded: 1500 / 46
Outcome Cohorts Evaluated: 16
Features: usable=11; cautious=4; quarantined=6
Winner DNA:
- MODERATE_WINNERS: price_component|GREATER_THAN_OR_EQUAL|0.65; enrichment=1.1579; adjusted p=0.032692; stability=STABLE
- MODERATE_WINNERS: strategy_score|GREATER_THAN_OR_EQUAL|40; enrichment=1.1282; adjusted p=0.057892; stability=EMERGING
- STRONG_WINNERS: entry_timing_state|EQUAL|BUY; enrichment=3.0000; adjusted p=0.129672; stability=STABLE
- STRONG_WINNERS: confidence|EQUAL|HIGH; enrichment=3.0000; adjusted p=0.129672; stability=STABLE
- STRONG_WINNERS: long_trade_permission|EQUAL|true; enrichment=3.0000; adjusted p=0.129672; stability=STABLE
Loser and Catastrophic-Loss DNA:
- CATASTROPHIC_LOSERS: final_verdict|EQUAL|SELL; enrichment=1.8125; adjusted p=0.000000; stability=WEAKENING
- CATASTROPHIC_LOSERS: confidence|EQUAL|REJECT; enrichment=1.8125; adjusted p=0.000000; stability=WEAKENING
- CATASTROPHIC_LOSERS: entry_timing_state|EQUAL|AVOID; enrichment=1.2222; adjusted p=0.000102; stability=EMERGING
- LARGE_LOSERS: long_trade_permission|EQUAL|false; enrichment=1.0497; adjusted p=0.022433; stability=EMERGING
- LARGE_LOSERS: raw_approved|EQUAL|false; enrichment=1.0396; adjusted p=0.030661; stability=EMERGING
Missed-Opportunity DNA:
- PROFITABLE_REJECTED: stop_distance_pct|LESS_THAN_OR_EQUAL|10; enrichment=1.7037; adjusted p=0.000425; stability=STABLE
- PROFITABLE_REJECTED: strategy_score|GREATER_THAN_OR_EQUAL|40; enrichment=1.1176; adjusted p=0.001162; stability=STABLE
- PROFITABLE_REJECTED: stop_distance_pct|LESS_THAN_OR_EQUAL|5; enrichment=8.5000; adjusted p=0.001995; stability=STABLE
- PROFITABLE_REJECTED: price_component|GREATER_THAN_OR_EQUAL|0.65; enrichment=1.1558; adjusted p=0.003409; stability=WEAKENING
- PROFITABLE_REJECTED: entry_timing_state|EQUAL|ACCUMULATE; enrichment=1.6304; adjusted p=0.005987; stability=WEAKENING
Statistical Control:
- BENJAMINI_HOCHBERG_FDR_BY_FEATURE_AND_INTERACTION_FAMILY: tested=1031; surviving=370; rejected=661
Temporal Stability: stable patterns=399
Concentration / Fragility: concentrated patterns=98
Bounded Interactions Retained: 50
Descriptive Clusters: 3
Strategy Hypotheses Generated: 0
Final Conclusion: NO_ROBUST_MARKET_DNA_FOUND
Highest-Value Missing Evidence: Authoritative completed outcomes with corporate-action-complete chronological bars and a genuinely untouched holdout population.
No DNA score was added to recommendations, approval, allocation, or execution.
PRODUCTION_INFLUENCE=false

Exit code: 0
```


