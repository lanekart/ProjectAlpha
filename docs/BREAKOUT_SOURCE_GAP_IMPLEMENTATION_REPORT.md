# Breakout Source-Gap Audit Implementation Report

## 1. Files Changed

- `alpha/historical_replay/breakout_source_gap.py`
- `alpha/historical_replay/breakout_source_gap_service.py`
- `alpha/historical_replay/__init__.py`
- `alpha/cli.py`
- `tests/historical_replay/test_breakout_source_gap.py`
- `docs/BREAKOUT_SOURCE_GAP_AUDIT.md`
- `docs/BREAKOUT_INTELLIGENCE_ENGINE.md`
- `docs/BREAKOUT_SOURCE_GAP_IMPLEMENTATION_REPORT.md`

## 2. Diagnostic Architecture

`BreakoutSourceGapAuditEngine` consumes immutable point-in-time reconstruction
records plus `BreakoutCandidateDiagnosticContext`. It emits one deterministic primary
cause, secondary causes, source-path disposition, attribution confidence, and
recovery class per candidate. The same attributed population feeds the source
coverage matrix, selection-bias report, recovery scenarios, grouped views, and
deterministic JSON/CSV exports.

`build_project_breakout_source_gap_audit` joins the reference sidecar to raw candidate,
decision, outcome, entry-timing, breadth, canonical DuckDB, raw archive, and extracted
cache evidence. Historical symbols and the existing cutoff remain unchanged. Raw and
extracted caches are treated as lineage for the canonical source, not independent
providers.

Primary-cause precedence is documented in `BREAKOUT_SOURCE_GAP_AUDIT.md`. Outcome
fields remain in a separate post-candidate diagnostic and never affect attribution,
recovery, or reconstruction.

## 3. Tests Added

Sixty-four deterministic tests cover:

- every required gap cause and unknown fallback
- cause and recovery precedence, including competing paths
- every recovery class
- representative, year-, regime-, setup-, score-, survival-, and outcome-divergent
  populations
- insufficient samples and repeated-symbol concentration
- historical-symbol, current-symbol, fallback, cache, cutoff, filter, correct
  rejection, and true-absence source paths
- all groupings, filters, sample limits, date and symbol filters
- all five CLI commands and deterministic JSON/CSV exports
- explicit `PRODUCTION_INFLUENCE=false`

The full existing reconstruction, classifier, recommendation, approval, timing,
stop, target, and provider test suites also passed.

## 4. Validation Results

- `poetry run pytest`: 1,308 passed in 105.13 seconds
- `poetry run ruff check .`: passed
- `poetry run mypy alpha`: passed, 360 source files checked
- `poetry build`: sdist and wheel built successfully
- all five required real-data commands: passed
- all five required grouped views: passed

Database-backed CLI commands were run serially, as required by Alpha's local DuckDB
single-process lock policy.

## 5. CLI Commands Added

```bash
poetry run python -m alpha replay breakout-source-gap-audit
poetry run python -m alpha replay breakout-selection-bias
poetry run python -m alpha replay breakout-source-coverage
poetry run python -m alpha replay breakout-recovery-readiness
poetry run python -m alpha replay breakout-gap-sample --limit 30
```

## 6-24. Source-Gap and Recovery Findings

- Total candidates: 1,546
- Ready records: 889
- Unreconstructable records: 657
- Overall readiness: 57.50%
- Unique affected symbols: 158
- Affected years: 2016 through 2026
- True source absence: 563
- Implementation-path gaps: 0
- Identity-related: 0
- Corporate-action-related: 45
- Cutoff-related: 0
- Legitimately insufficient local history: 10
- Unknown cause: 0
- Existing-source direct recovery: 0
- Identity repair recovery: 0
- Normalization or implementation repair recovery: 0
- Cutoff resolution recovery: 0
- New external source required: 608 candidates across 114 symbols
- Legitimately unrecoverable: 0
- Recovery uncertain: 49 candidates across 44 symbols
- Projected ready after existing-source recovery: 889
- Projected readiness after existing-source recovery: 57.50%

Primary causes:

| Cause | Count |
|---|---:|
| `INSUFFICIENT_PRE_CANDIDATE_LOOKBACK` | 563 |
| `CORPORATE_ACTION_AMBIGUITY` | 45 |
| `MULTI_SESSION_GAP` | 24 |
| `PARTIAL_LOOKBACK_AVAILABLE` | 15 |
| `LEGITIMATELY_INSUFFICIENT_TRADING_HISTORY` | 10 |

Secondary causes overlap by design and therefore exceed 657 in aggregate:

| Cause | Count |
|---|---:|
| `NO_ARCHIVE_RECORD` | 563 |
| `PARTIAL_LOOKBACK_AVAILABLE` | 563 |
| `ARCHIVE_RECORD_INCOMPLETE` | 24 |

The ten locally short histories are low-confidence attribution cases. Because no
official listing effective dates are present, they remain recovery-uncertain rather
than being declared permanently unrecoverable.

## 25. Ready-vs-Unavailable by Year

| Year | Total | Ready | Unavailable | Inclusion |
|---:|---:|---:|---:|---:|
| 2016 | 880 | 297 | 583 | 33.75% |
| 2017 | 40 | 38 | 2 | 95.00% |
| 2018 | 40 | 32 | 8 | 80.00% |
| 2019 | 40 | 37 | 3 | 92.50% |
| 2020 | 40 | 36 | 4 | 90.00% |
| 2021 | 90 | 88 | 2 | 97.78% |
| 2022 | 80 | 68 | 12 | 85.00% |
| 2023 | 80 | 73 | 7 | 91.25% |
| 2024 | 90 | 87 | 3 | 96.67% |
| 2025 | 90 | 72 | 18 | 80.00% |
| 2026 | 76 | 61 | 15 | 80.26% |

Year total-variation distance is 0.5533. Candidate-date ordinal SMD is 1.1246. The
ready sample is materially more recent.

## 26. Differences by Regime

- `NEGATIVE`: 17/20 ready, 85.00% inclusion
- `NEUTRAL`: 872/1,526 ready, 57.14% inclusion
- Market-regime total-variation distance: 0.0146

Regime imbalance is small relative to the year and setup effects, but the historical
regime field is itself sparse in variety.

## 27. Differences by Setup

- `DISTRIBUTION`: 39/42 ready, 92.86% inclusion
- `MOMENTUM CONTINUATION`: 754/1,390 ready, 54.24% inclusion
- `NO VALID SETUP`: 1/1 ready, 100.00% inclusion
- `TREND FAILURE`: 95/113 ready, 84.07% inclusion
- Setup total-variation distance: 0.1199

Momentum Continuation is materially underrepresented in the ready-only sample.

## 28. Differences by Recommendation Score

- Mean score: ready 54.3123, unavailable 55.2166
- Score SMD: -0.0604
- Score-bucket total-variation distance: 0.0764
- Largest score-bucket difference: `HIGH`, 0.0764

The continuous score difference is small; score-bucket composition is a minor to
moderate observed difference.

## 29. Symbol Survival and Continuity

- Ready symbols: 222
- Unavailable symbols: 158
- Ready symbol HHI: 0.0225
- Unavailable symbol HHI: 0.0286
- Absolute HHI difference: 0.0061
- Survival/continuity total-variation distance: 0.1373
- Largest category difference:
  `SOURCE_CONTINUITY_ENDED_BEFORE_SOURCE_END`, 0.1373

Candidate rows are clustered by symbol. The effect sizes are diagnostic and are not
treated as independent observations.

## 30. Completed-Outcome Availability

- Ready: 771/889, 86.73%
- Unavailable: 640/657, 97.41%
- Absolute difference: 10.68 percentage points

This metric is reported only in the post-candidate diagnostic and does not influence
the pre-outcome bias conclusion.

## 31. Post-Candidate Outcome Diagnostics

These values are diagnostic only and were not used to reconstruct or classify a gap:

- Positive 20-day return rate: ready 46.82%, unavailable 39.84%, difference 6.98
  percentage points
- Average stored 20-day forward return: ready 0.3392, unavailable 11.3334,
  absolute difference 10.9942
- Target 1 hit rate: 0.0000 in both groups
- Stop hit rate: 0.0000 in both groups
- Outcome sample sizes: 771 ready and 640 unavailable

The forward-return divergence is not interpreted causally. Its scale warrants source
and unit validation before any later performance use.

## 32-35. Conclusions and Policy Integrity

- Missingness mechanism: `MIXED_MISSINGNESS`
- Ready-sample bias: `READY_SAMPLE_HAS_MATERIAL_OBSERVED_BIAS`
- Overall next step: `NEW_HISTORICAL_SOURCE_REQUIRED`
- Restricted breakout predictive-value validation remains blocked.

No reconstruction algorithm, breakout classifier, threshold, recommendation,
approval, entry-timing, stop, target, provider architecture, or production policy was
changed. Production influence remains false.

## Full `breakout-source-gap-audit` Output

```text
Breakout Source-Gap Attribution Audit
Audit Version: breakout-source-gap-audit-v1
Total Candidates: 1546
Ready Records: 889
Unreconstructable Records: 657
Overall Readiness: 57.50%
Unique Affected Symbols: 158
Affected Year Range: 2016 to 2026
Primary Gap Causes: CORPORATE_ACTION_AMBIGUITY=45; INSUFFICIENT_PRE_CANDIDATE_LOOKBACK=563; LEGITIMATELY_INSUFFICIENT_TRADING_HISTORY=10; MULTI_SESSION_GAP=24; PARTIAL_LOOKBACK_AVAILABLE=15
Secondary Gap Causes: ARCHIVE_RECORD_INCOMPLETE=24; NO_ARCHIVE_RECORD=563; PARTIAL_LOOKBACK_AVAILABLE=563
True Source Absence: 563
Implementation-Path Gaps: 0
Identity-Related: 0
Corporate-Action-Related: 45
Cutoff Ambiguity: 0
Legitimately Insufficient Trading History: 10
Unknown Cause: 0
Recoverable Using Existing Sources: 0
Recoverable After Identity Repair: 0
Requires New External Source: 608
Legitimately Unrecoverable: 0
Recovery Uncertain: 49
Ready-Sample Bias Conclusion: READY_SAMPLE_HAS_MATERIAL_OBSERVED_BIAS
Missingness Mechanism: MIXED_MISSINGNESS
Projected Readiness After Existing-Source Recovery: 57.50%
Projected Readiness If New-Source Records Remain Unavailable: 57.50%
Overall Next-Step Conclusion: NEW_HISTORICAL_SOURCE_REQUIRED
No reconstruction, classifier, recommendation, approval, timing, stop, target, or production policy changed.
PRODUCTION_INFLUENCE=false
```

## Full `breakout-selection-bias` Output

```text
Breakout Ready-vs-Unavailable Selection-Bias Audit
Total Candidates: 1546
Ready / Unavailable: 889 / 657
Candidate Inclusion Probability: 57.50%
Unique Symbols Ready / Unavailable: 222 / 158
Ready Symbol HHI: 0.0225
Unavailable Symbol HHI: 0.0286
Absolute Symbol HHI Difference: 0.0061
Candidate rows are clustered by symbol; effect sizes are diagnostic and are not treated as independent observations.
Pre-Outcome Numeric Effect Sizes:
- recommendation_score: ready n=889, unavailable n=657, means 54.3123 vs 55.2166, SMD -0.0604
- candidate_date_ordinal: ready n=889, unavailable n=657, means 737652.0742 vs 736471.0381, SMD 1.1246
- liquidity_proxy: ready n=889, unavailable n=657, means 0.3799 vs 0.4251, SMD -0.1474
- listing_age_days: ready n=0, unavailable n=0, means unavailable vs unavailable, SMD unavailable
- price_component: ready n=889, unavailable n=657, means 0.7065 vs 0.7168, SMD -0.0940
- volume_component: ready n=889, unavailable n=657, means 0.5710 vs 0.5531, SMD 0.1399
- trend_component: ready n=0, unavailable n=0, means unavailable vs unavailable, SMD unavailable
- regime_confidence: ready n=0, unavailable n=0, means unavailable vs unavailable, SMD unavailable
- candidate_rank: ready n=889, unavailable n=657, means 5.4432 vs 5.5449, SMD -0.0354
- bars_usable: ready n=889, unavailable n=657, means 112.0202 vs 38.5495, SMD 2.9342
Pre-Outcome Distribution Differences:
- year: n=889/657, TV distance 0.5533, largest 2016 (0.5533)
- sector: n=889/657, TV distance 0.0067, largest UNAVAILABLE (0.0067)
- liquidity_bucket: n=889/657, TV distance 0.1030, largest VERY_LOW (0.0995)
- listing_age_bucket: n=889/657, TV distance 0.0000, largest UNAVAILABLE (0.0000)
- setup_type: n=889/657, TV distance 0.1199, largest MOMENTUM CONTINUATION (0.1199)
- recommendation_verdict: n=889/657, TV distance 0.1520, largest SELL (0.0933)
- recommendation_score_bucket: n=889/657, TV distance 0.0764, largest HIGH (0.0764)
- price_component_bucket: n=889/657, TV distance 0.0204, largest HIGH (0.0204)
- volume_component_bucket: n=889/657, TV distance 0.0611, largest LOW (0.0611)
- trend_component_bucket: n=889/657, TV distance 0.0000, largest UNAVAILABLE (0.0000)
- entry_timing_state: n=889/657, TV distance 0.2128, largest LATE_ENTRY (0.2060)
- market_regime: n=889/657, TV distance 0.0146, largest NEGATIVE (0.0146)
- regime_confidence_bucket: n=889/657, TV distance 0.0000, largest UNAVAILABLE (0.0000)
- breadth_state: n=889/657, TV distance 0.1284, largest WEAK_PARTICIPATION (0.1284)
- provider: n=889/657, TV distance 0.0000, largest PROJECT_ALPHA_CANONICAL_DAILY_PRICES (0.0000)
- lookback_requirement: n=889/657, TV distance 0.0000, largest 121 (0.0000)
- symbol_change_status: n=889/657, TV distance 0.0000, largest UNAVAILABLE_NO_EFFECTIVE_DATED_ALIAS (0.0000)
- survival_or_continuity_status: n=889/657, TV distance 0.1373, largest SOURCE_CONTINUITY_ENDED_BEFORE_SOURCE_END (0.1373)
- replay_version: n=889/657, TV distance 0.0187, largest market-intelligence-composite-v1 (0.0187)
Post-Candidate Outcome Diagnostics (not used for reconstruction):
- completed_outcome_availability: n=889/657, ready 0.8673, unavailable 0.9741, difference 0.1068
- positive_20d_forward_return_rate: n=771/640, ready 0.4682, unavailable 0.3984, difference 0.0698
- average_20d_forward_return: n=771/640, ready 0.3392, unavailable 11.3334, difference 10.9942
- target_1_hit_rate: n=771/640, ready 0.0000, unavailable 0.0000, difference 0.0000
- stop_hit_rate: n=771/640, ready 0.0000, unavailable 0.0000, difference 0.0000
Missingness Mechanism: MIXED_MISSINGNESS
Ready-Sample Bias Conclusion: READY_SAMPLE_HAS_MATERIAL_OBSERVED_BIAS
Warning: Outcome comparisons are post-candidate diagnostics and are not used to reconstruct evidence.
Warning: Absence of a large observed difference is not proof of representativeness.
Warning: Unavailable fields are retained as UNAVAILABLE and are not imputed.
PRODUCTION_INFLUENCE=false
```

## Full `breakout-recovery-readiness` Output

```text
Breakout Recovery Readiness Audit
Total Candidates: 1546
Current Ready Records: 889
Current Readiness: 57.50%
Recovery Distribution: RECOVERY_UNCERTAIN=49; REQUIRES_NEW_EXTERNAL_SOURCE=608
Existing Source Direct: 0
Identity Repair: 0
Normalization Repair: 0
Cutoff Resolution: 0
New External Source Required: 608
Legitimately Unrecoverable: 0
Recovery Uncertain: 49
Projected Ready After Existing-Source Recovery: 889
Projected Readiness After Existing-Source Recovery: 57.50%
Scenarios are deterministic feasibility cases, not recovery promises.
- REQUIRES_NEW_EXTERNAL_SOURCE: candidates 608, symbols 114, years 2016 to 2026, kind DATA_ACQUISITION_REQUIRED; source unavailable in current repository inventory; action acquire authoritative pre-boundary OHLCV or corporate-action evidence later; projected readiness 57.50%
- RECOVERY_UNCERTAIN: candidates 49, symbols 44, years 2016 to 2026, kind FURTHER_DIAGNOSIS; source not established; action collect stronger identity, suspension, archive, or source-path evidence; projected readiness 57.50%
PRODUCTION_INFLUENCE=false
```
