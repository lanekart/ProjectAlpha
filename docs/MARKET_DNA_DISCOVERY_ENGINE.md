# Market DNA Discovery Engine

## Purpose

Market DNA is an outcome-first research subsystem. It asks which frozen,
point-in-time characteristics differ across explicit historical outcome cohorts. It
does not create live signals, change approval gates, allocate capital, or execute
trades.

`PRODUCTION_INFLUENCE=false` is enforced in snapshots, patterns, hypotheses,
registries, publication specifications, CLI output, Research Registry records, and IRD
evidence.

## Evidence Boundary

The current dataset contains 1,500 reconstructed completed outcomes and no
authoritative completed historical outcomes. Every current result is therefore
`RECONSTRUCTED` and cannot be described as causal, out-of-sample validated,
forward-observed, deployable, or measured forward ROI.

Discovery and evaluation currently use the same population. Market DNA makes no
unchanged holdout claim. An authoritative, corporate-action-complete chronological
population and a genuinely untouched holdout are required before a pattern may become
a Strategy Lab hypothesis candidate.

## Data Flow

1. `HistoricalSignalGenerator` supplies the existing point-in-time discovery dataset.
2. `FeatureSnapshotBuilder` separates pre-decision features from post-decision labels.
3. `FeatureQualityAuditEngine` checks timestamps, scale, missingness, lineage, and
   quarantine state.
4. `OutcomeCohortRegistry` defines 16 explicit, versioned outcome predicates.
5. `MatchedCohortEngine` performs deterministic matching by horizon, setup, and year.
6. `DistributionAnalysis` and `EffectSizeEngine` calculate distributions, prevalence,
   enrichment, effect sizes, confidence intervals, odds ratios, risk ratios, and raw
   significance.
7. `InteractionDiscovery` tests a bounded set of fixed-grid two-feature conjunctions.
8. `FalseDiscoveryControl` applies Benjamini-Hochberg false-discovery correction.
9. `ClusterDiscovery` forms feature-only clusters before attaching outcome labels.
10. `StabilityAnalysis` applies temporal, sample, lineage, and concentration rules.
11. `DNARegistry` permanently stores accepted and rejected patterns.
12. `HypothesisGenerator` and `StrategyLabBridge` can create inert research
    specifications only after the evidence contract is met.

## Feature Contract

Market DNA composes the existing Strategy Discovery feature allow-list. The current
inventory contains:

- 11 clean usable features;
- 4 cautionary features, of which the three normalized component scores are permitted
  with lineage safeguards and raw cross-symbol entry price is not searched;
- 6 quarantined features.

Quarantined inputs include retracement while its calibration direction is unresolved,
invalid market-regime reference labels, unavailable historical sector membership, and
future-derived return, MFE, and MAE fields.

Future outcomes remain available only to define labels. Cohort-defining fields are
excluded from their own feature comparisons. For example, `raw_approved=false` cannot
be reported as DNA for a cohort defined as rejected.

## Outcome Cohorts

The versioned registry includes strong, moderate, and small winners; flat outcomes;
small, large, and catastrophic losers; high-MFE and high-MAE cohorts; profitable
rejections; approved profitable and unprofitable cohorts; missed-entry winner proxies;
stop-hit-then-recovered proxies; target-achieved proxies; and time-expired proxies.

Each report retains the exact predicate, horizon, cost profile, sample, dates, symbols,
evidence class, corporate-action status, and reconstruction status. Target, stop,
missed-entry, and expiry labels are explicitly described as reconstructed proxies when
authoritative event ordering is unavailable.

## Statistical Discipline

Thresholds are fixed in the feature manifest before outcomes are inspected. The engine
does not optimize arbitrary post-hoc cutoffs. Findings report effect size and
concentration alongside p-values. False-discovery control covers the complete feature
and interaction families.

Matched comparisons are used when at least the configured minimum number of pairs is
available. Otherwise, the full non-cohort baseline is used and the matching limitation
remains visible. Interaction search is bounded, deterministic, and retains failed
minimum-cell tests as rejected evidence.

## Pattern Status

Every tested feature condition and interaction becomes an immutable DNA pattern with
exactly one status:

- `INVALID_DATA`
- `LEAKAGE_RISK`
- `LINEAGE_CONFOUNDED`
- `INSUFFICIENT_SAMPLE`
- `MULTIPLE_TESTING_FAILURE`
- `CONCENTRATED`
- `UNSTABLE`
- `RECONSTRUCTED_RESEARCH_ONLY`
- `ROBUST_RESEARCH_PATTERN`
- `STRATEGY_HYPOTHESIS_CANDIDATE`

A statistically interesting reconstructed association remains
`RECONSTRUCTED_RESEARCH_ONLY`. It is not promoted merely because it survived
false-discovery correction.

## Strategy Lab Bridge

`market-dna publish-hypothesis` accepts only a registered
`STRATEGY_HYPOTHESIS_CANDIDATE`. It writes a versioned, immutable and inert Strategy Lab
specification containing the originating pattern IDs, conditions, entry logic,
horizon, evidence class, and assumptions.

Publication does not run a backtest. The specification must separately pass Strategy
Lab, chronological walk-forward validation, robustness testing, and shadow forward
validation. Automatic execution and production influence are both false.

## Persistence and Exports

The default immutable registry is `.alpha/market_dna/dna_registry.json`. The inert
bridge registry is `.alpha/market_dna/strategy_lab_hypotheses.json`. JSON and CSV
exports are deterministic and retain failed patterns.

## CLI

```text
poetry run python -m alpha market-dna inventory
poetry run python -m alpha market-dna cohorts
poetry run python -m alpha market-dna discover
poetry run python -m alpha market-dna winners
poetry run python -m alpha market-dna losers
poetry run python -m alpha market-dna catastrophic-losses
poetry run python -m alpha market-dna missed-opportunities
poetry run python -m alpha market-dna interactions
poetry run python -m alpha market-dna hierarchy
poetry run python -m alpha market-dna hypotheses
poetry run python -m alpha market-dna publish-hypothesis --hypothesis ID
poetry run python -m alpha market-dna report
```

Discovery filters include horizon, cohort, setup, symbols, dates, evidence class,
minimum sample, interaction bound, and export destination. Sector filters fail closed
while historical sector evidence remains quarantined.

## Production Boundary

Market DNA is imported only by its CLI and research diagnostic registration. It is not
wired into recommendation, approval, allocation, execution, live market data, or
forward-validation decision paths. Existing `APPROVAL_POLICY_V1` and forward cohorts
remain unchanged.

`PRODUCTION_INFLUENCE=false`.
