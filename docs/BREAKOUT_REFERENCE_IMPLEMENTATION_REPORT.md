# Point-in-Time Breakout Reference Reconstruction Implementation Report

This report records evidence from the completed historical reconstruction milestone. It does not recommend or apply changes to weights, thresholds, approvals, entries, stops, or targets.

## Required Implementation Record

1. **Files changed:** `alpha/historical_replay/breakout_reference.py`, `alpha/historical_replay/breakout_reference_service.py`, `alpha/historical_replay/breakout_intelligence.py`, `alpha/historical_replay/__init__.py`, `alpha/cli.py`, `tests/historical_replay/test_breakout_reference.py`, `tests/historical_replay/test_breakout_reference_cli.py`, `docs/BREAKOUT_INTELLIGENCE_ENGINE.md`, `docs/POINT_IN_TIME_BREAKOUT_REFERENCE_RECONSTRUCTION.md`, and this report.
2. **Architecture:** a typed `PointInTimeBreakoutReferenceEngine` reconstructs evidence independently from outcome evaluation; an immutable, versioned sidecar repository persists records; integrity and readiness services audit the sidecar; a narrow adapter supplies ready records to the existing Breakout Intelligence classifier.
3. **Authoritative OHLCV source:** Project Alpha's configured canonical DuckDB `daily_prices` repository, reported as `PROJECT_ALPHA_CANONICAL_DAILY_PRICES`. Exchange sessions are derived from distinct persisted trading dates. Historical security identity is joined from the point-in-time analytical store. No current-symbol fallback is used.
4. **Exact cutoff semantics:** before-open and intraday decisions use the previous completed exchange session; a candidate-session close is allowed only when an after-close timestamp is proven; non-trading dates use the previous completed exchange session. Bars later than the allowed cutoff are excluded before validation and reconstruction.
5. **Date-only replay records:** the conservative repository-wide policy is previous completed trading session only, recorded as `LEGACY_DATE_ONLY_PREVIOUS_SESSION`. Candidate-day close is not presumed known.
6. **Adjustment and corporate-action policy:** reconstruction uses one internally consistent `RAW_UNADJUSTED` representation for references and comparison prices. A known split before the cutoff starts a new comparable segment; a split after the cutoff is ignored; mixed adjustment modes or unexplained material discontinuities are excluded. No dividend adjustment is invented for raw series.
7. **Reference methodologies:** typed support exists for `PRIOR_SWING_HIGH`, `RANGE_RESISTANCE`, and `ROLLING_HIGH`. The real dataset and classifier adapter use `PRIOR_SWING_HIGH`; methods are never silently substituted.
8. **Dataset schema and version:** `breakout-reference-record-v1` in `breakout_reference_dataset_v1`, algorithm `point-in-time-breakout-reference-v1`.
9. **Persistence:** immutable JSON sidecar `.alpha/breakout_reference_dataset_v1.json`, keyed by replay run, candidate, method, cutoff/configuration, and algorithm version. Original replay rows are unchanged.
10. **Provenance:** each record carries source identity, source dataset, retrieval/reconstruction timestamps, raw and normalized checksums, adjustment mode, algorithm and schema versions, configuration hash, security-master evidence, cutoff rule, warnings, exclusions, and readiness status. Semantic hashes exclude operational timestamps.
11. **CLI commands:** `replay breakout-reference-reconstruct`, `breakout-reference-readiness`, `breakout-reference-integrity`, `breakout-reference-provenance`, and `breakout-reference-sample`, with deterministic text/JSON/CSV exports and applicable filters.
12. **Tests:** 21 focused tests cover cutoff boundaries, future-bar/swing/retest exclusion, all three reference methods, no-reference semantics, deterministic hashes, malformed series, sessions/timezones, identity/listing/delisting/symbol migration, corporate actions, persistence/reuse, adapter behavior, exports, CLI validation, dry run, readiness, integrity, and unchanged classifier integration.
13. **Validation:** `poetry run pytest` passed 1,244 tests in 107.22 seconds; `poetry run ruff check .` passed; `poetry run mypy alpha` passed across 358 source files; `poetry build` produced both sdist and wheel. The focused reconstruction suite passed 27 tests.
14. **Total replay candidates:** 1,546.
15. **Candidates attempted:** 1,546.
16. **Ready records:** 889.
17. **Valid `REFERENCE_NOT_FORMED` records:** 0.
18. **Unreconstructable records:** 657.
19. **Readiness percentage:** 57.50%.
20. **Availability by year:** 2016 297/880 (33.75%); 2017 38/40 (95.00%); 2018 32/40 (80.00%); 2019 37/40 (92.50%); 2020 36/40 (90.00%); 2021 88/90 (97.78%); 2022 68/80 (85.00%); 2023 73/80 (91.25%); 2024 87/90 (96.67%); 2025 72/90 (80.00%); 2026 61/76 (80.26%).
21. **Top exclusions:** `INSUFFICIENT_LOOKBACK=578`, `CORPORATE_ACTION_AMBIGUITY=45`, `MISSING_BARS=24`, `SOURCE_UNAVAILABLE=10`.
22. **Ambiguous-cutoff count:** 0.
23. **Unresolved-symbol count:** 0.
24. **Corporate-action ambiguity count:** 45.
25. **Provenance-completeness rate:** 100.00%.
26. **Determinism:** PASS; the second persisted run reused all 1,546 records and created none.
27. **Leakage audit:** PASS; every future-bar, future-swing, post-candidate-retest, outcome-field, and future-market-state violation count is zero.
28. **Historical readiness:** `BREAKOUT_HISTORY_BLOCKED_BY_SOURCE_GAPS`. Readiness requires at least 95% usable history, complete provenance, and passing determinism/leakage audits.
29. **Before versus after `INSUFFICIENT_EVIDENCE`:** 1,500 before the adapter and 649 after it, a reduction of 851. The sidecar has 889 ready records; 851 join the 1,500-row completed breakout-audit population. This is a classifiability observation, not a performance conclusion.
30. **Policy integrity:** classifier thresholds, breakout-state definitions, recommendation logic and weights, approval policy, entry timing, stops, targets, production verdicts, and production influence are unchanged. Every report states `PRODUCTION_INFLUENCE=false`.

## Full Readiness Output

```text
Breakout Reference Historical Readiness
Dataset Version: breakout_reference_dataset_v1
Total Replay Candidates: 1546
Unique Symbols: 308
Date Range: 2016-07-11 to 2026-07-10
Candidates Attempted: 1546
Ready Records: 889
Valid REFERENCE_NOT_FORMED Records: 0
Unreconstructable Records: 657
Readiness Percentage: 57.50%
Availability By Year: 2016=297/880 (33.75%); 2017=38/40 (95.00%); 2018=32/40 (80.00%); 2019=37/40 (92.50%); 2020=36/40 (90.00%); 2021=88/90 (97.78%); 2022=68/80 (85.00%); 2023=73/80 (91.25%); 2024=87/90 (96.67%); 2025=72/90 (80.00%); 2026=61/76 (80.26%)
Availability By Symbol: 3IINFOTECH=0/1 (0.00%); AAATECH=0/1 (0.00%); AAREYDRUGS=0/1 (0.00%); ABAN=2/2 (100.00%); ADANIPORTS=0/2 (0.00%); ADANIPOWER=16/18 (88.89%); ADLABS=0/1 (0.00%); AKSHAR=0/1 (0.00%); AKSHOPTFBR=2/4 (50.00%); ALOKINDS=4/5 (80.00%)
Availability By Data Source: PROJECT_ALPHA_CANONICAL_DAILY_PRICES=889/1546 (57.50%)
Availability By Reference Method: PRIOR_SWING_HIGH=889/1546 (57.50%)
Availability By Timing Semantics: LEGACY_DATE_ONLY_PREVIOUS_SESSION=889/1546 (57.50%)
Top Exclusion Reasons: CORPORATE_ACTION_AMBIGUITY=45; INSUFFICIENT_LOOKBACK=578; MISSING_BARS=24; SOURCE_UNAVAILABLE=10
Median Usable Lookback: 121.000000
Minimum Usable Lookback: 62
Ambiguous Cutoff Count: 0
Corporate-Action Ambiguity Count: 45
Unresolved Symbol Count: 0
Provenance Completeness Rate: 100.00%
Deterministic Reconstruction Check: PASS
Leakage Audit Result: PASS
Overall Readiness Conclusion: BREAKOUT_HISTORY_BLOCKED_BY_SOURCE_GAPS
Ready requires at least 95% usable history, complete provenance, and passing determinism/leakage audits.
PRODUCTION_INFLUENCE=false
```

## Full Integrity Output

```text
Breakout Reference Integrity Audit
Records Checked: 1546
Future Bar Violations: 0
Future Swing Confirmation Violations: 0
Post-Candidate Retest Violations: 0
Outcome-Derived Field Violations: 0
Future Market-State Violations: 0
Semantic Hash Violations: 0
Duplicate-Key Conflicts: 0
Configuration Hash Violations: 0
Source Checksum Violations: 0
Identity Violations: 0
Listing-Interval Violations: 0
Adjustment Consistency Violations: 0
Duplicate-Bar Violations: 0
Invalid-OHLC Violations: 0
Incomplete Ready Lineage: 0
Exclusions Without Reason: 0
Determinism: PASS
Future Leakage: PASS
Identity: PASS
Series Integrity: PASS
Lineage: PASS
Overall Integrity: PASS
PRODUCTION_INFLUENCE=false
```

## Full Breakout Intelligence Output

```text
Breakout Intelligence Engine
Replay Period: 2016-07-11 to 2026-06-30
Raw Observations: 1500
Unique Opportunities: 736
Breakout Observations: 1500
Completed Breakout Outcomes: 1500
Frozen Confirmation Baseline Precision: 48.3%
Breakout Class Distribution: BREAKOUT_FORMING=362, EXTENDED_BREAKOUT=99, FAILED_BREAKOUT=54, INSUFFICIENT_EVIDENCE=649, NO_BREAKOUT=214, PREMATURE_BREAKOUT=23, UNCONFIRMED_BREAKOUT=99
Precision By Breakout Class: BREAKOUT_FORMING=20.7%, EXTENDED_BREAKOUT=21.7%, FAILED_BREAKOUT=0.0%, INSUFFICIENT_EVIDENCE=27.2%, NO_BREAKOUT=9.3%, PREMATURE_BREAKOUT=18.2%
Expectancy By Breakout Class: BREAKOUT_FORMING=-14.4%, EXTENDED_BREAKOUT=-16.3%, FAILED_BREAKOUT=-33.9%, INSUFFICIENT_EVIDENCE=-13.8%, NO_BREAKOUT=-24.5%, PREMATURE_BREAKOUT=-11.7%
Effective Sample Size By Class: BREAKOUT_FORMING=128.8, EXTENDED_BREAKOUT=66.2, FAILED_BREAKOUT=42.5, INSUFFICIENT_EVIDENCE=152.9, NO_BREAKOUT=103.4, PREMATURE_BREAKOUT=20.6
Healthy-Breakout Count: 0
Weak-Breakout Count: 0
Premature-Breakout Count: 23
Retrospective False-Breakout Count: 1106
Weak-RS Count: 0
False-Breakout and Weak-RS Overlap: both=0, false_only=421, weak_rs_only=0
Relative-Strength Timing Relationship: RS_UNAVAILABLE (1500)
Strongest Independent Evidence Groups: full_confirmation_without_rs, breakout_plus_volume, breakout_evidence_only
Largest Lineage Overlaps: PRICE_STRUCTURE_EVIDENCE/opportunity_quality_score=0.82, RELATIVE_STRENGTH_EVIDENCE/relative_strength_component=0.78, VOLUME_EVIDENCE/participation_confirmation=0.67
Best Class-Based Policy: NO_EXHAUSTED_OR_EXTENDED
Best-Policy Precision: 23.2%
Confidence Interval: [19.8%, 27.1%]
Best-Policy Effective Sample Size: 142.78
Coverage: 67.8%
Annual Signals: 45.36
Expectancy: -12.7%
Delay: 0.12 days
Missed Move: 0.1%
Worst Outer Fold: 9.3%
Concentration Status: CONCENTRATED
Causal Relationship Conclusion: INDEPENDENT_FAILURE_MECHANISMS
Breakout-Layer Value Conclusion: BREAKOUT_CLASSIFICATION_REDUNDANT
Policy Conclusion: CURRENT_CONFIRMATION_RULE_REMAINS_SUPERIOR
PRODUCTION_INFLUENCE=false
```

The existing command prints historical outcome fields. They are reproduced verbatim above because the requested validation command was run; this milestone did not calculate, tune against, or interpret those fields.

## Full Breakout Classification Output

```text
Breakout Classification Audit
PRODUCTION_INFLUENCE=false
- 3IINFOTECH 2016-08-12: INSUFFICIENT_EVIDENCE confidence LOW; reason DATA_INSUFFICIENT
- AAATECH 2021-07-01: INSUFFICIENT_EVIDENCE confidence LOW; reason DATA_INSUFFICIENT
- AAREYDRUGS 2025-04-01: INSUFFICIENT_EVIDENCE confidence LOW; reason DATA_INSUFFICIENT
- ABAN 2016-10-10: UNCONFIRMED_BREAKOUT confidence LOW; reason CLEARED_BUT_UNCONFIRMED
- ABAN 2016-10-17: UNCONFIRMED_BREAKOUT confidence LOW; reason CLEARED_BUT_UNCONFIRMED
- ADANIPORTS 2016-08-10: INSUFFICIENT_EVIDENCE confidence LOW; reason DATA_INSUFFICIENT
- ADANIPORTS 2016-08-16: INSUFFICIENT_EVIDENCE confidence LOW; reason DATA_INSUFFICIENT
- ADANIPOWER 2016-09-09: INSUFFICIENT_EVIDENCE confidence LOW; reason DATA_INSUFFICIENT
- ADANIPOWER 2016-10-20: UNCONFIRMED_BREAKOUT confidence LOW; reason CLEARED_BUT_UNCONFIRMED
- ADANIPOWER 2016-12-02: UNCONFIRMED_BREAKOUT confidence LOW; reason CLEARED_BUT_UNCONFIRMED
- ADANIPOWER 2016-12-05: UNCONFIRMED_BREAKOUT confidence LOW; reason CLEARED_BUT_UNCONFIRMED
- ADANIPOWER 2016-12-06: UNCONFIRMED_BREAKOUT confidence LOW; reason CLEARED_BUT_UNCONFIRMED
- ADANIPOWER 2016-12-07: UNCONFIRMED_BREAKOUT confidence LOW; reason CLEARED_BUT_UNCONFIRMED
- ADANIPOWER 2016-12-13: BREAKOUT_FORMING confidence LOW; reason APPROACHING_RESISTANCE
- ADANIPOWER 2016-12-15: BREAKOUT_FORMING confidence LOW; reason APPROACHING_RESISTANCE
- ADANIPOWER 2016-12-30: NO_BREAKOUT confidence LOW; reason RESISTANCE_NOT_CLEARED
- ADANIPOWER 2017-01-02: NO_BREAKOUT confidence LOW; reason RESISTANCE_NOT_CLEARED
- ADANIPOWER 2018-10-01: NO_BREAKOUT confidence LOW; reason RESISTANCE_NOT_CLEARED
- ADANIPOWER 2019-07-01: EXTENDED_BREAKOUT confidence LOW; reason EXTENDED_FROM_SUPPORT
- ADANIPOWER 2020-01-01: BREAKOUT_FORMING confidence LOW; reason APPROACHING_RESISTANCE
- ADANIPOWER 2022-04-01: EXTENDED_BREAKOUT confidence LOW; reason EXTENDED_FROM_SUPPORT
- ADANIPOWER 2025-10-01: INSUFFICIENT_EVIDENCE confidence LOW; reason DATA_INSUFFICIENT
- ADANIPOWER 2016-10-07: NO_BREAKOUT confidence LOW; reason RESISTANCE_NOT_CLEARED
- ADANIPOWER 2016-10-14: BREAKOUT_FORMING confidence LOW; reason APPROACHING_RESISTANCE
- ADANIPOWER 2016-10-19: PREMATURE_BREAKOUT confidence LOW; reason STRUCTURE_IMPROVING_BUT_CONFIRMATION_INCOMPLETE
- ADLABS 2016-09-26: INSUFFICIENT_EVIDENCE confidence LOW; reason DATA_INSUFFICIENT
- AKSHAR 2024-01-03: INSUFFICIENT_EVIDENCE confidence LOW; reason DATA_INSUFFICIENT
- AKSHOPTFBR 2016-09-12: INSUFFICIENT_EVIDENCE confidence LOW; reason DATA_INSUFFICIENT
- AKSHOPTFBR 2016-09-14: INSUFFICIENT_EVIDENCE confidence LOW; reason DATA_INSUFFICIENT
- AKSHOPTFBR 2023-01-02: NO_BREAKOUT confidence LOW; reason RESISTANCE_NOT_CLEARED
- ALOKINDS 2020-04-01: INSUFFICIENT_EVIDENCE confidence LOW; reason DATA_INSUFFICIENT
- ALOKINDS 2024-01-02: BREAKOUT_FORMING confidence LOW; reason APPROACHING_RESISTANCE
- ALOKINDS 2024-01-03: EXTENDED_BREAKOUT confidence LOW; reason EXTENDED_FROM_SUPPORT
- ALOKINDS 2024-01-05: EXTENDED_BREAKOUT confidence LOW; reason EXTENDED_FROM_SUPPORT
- ALOKINDS 2020-10-01: FAILED_BREAKOUT confidence LOW; reason FAILED_AT_TIMESTAMP
- ALOKTEXT 2016-12-19: EXTENDED_BREAKOUT confidence LOW; reason EXTENDED_FROM_SUPPORT
- ALOKTEXT 2016-12-20: EXTENDED_BREAKOUT confidence LOW; reason EXTENDED_FROM_SUPPORT
- ALOKTEXT 2019-04-01: NO_BREAKOUT confidence LOW; reason RESISTANCE_NOT_CLEARED
- AMTEKAUTO 2016-07-26: INSUFFICIENT_EVIDENCE confidence LOW; reason DATA_INSUFFICIENT
- ANANTRAJ 2016-07-20: INSUFFICIENT_EVIDENCE confidence LOW; reason DATA_INSUFFICIENT
```
