# Point-in-Time Feature Attribution & Orthogonal Edge Audit v1.0

## Purpose

This subsystem tests which observations available at a tradable-opportunity onset
are associated with later success or failure. It is diagnostic research only. It
does not change recommendation weights, thresholds, setup definitions, approval
rules, or production behavior.

`PRODUCTION_INFLUENCE=false`

## Research Contract

The engine freezes the canonical and Setup Discovery parents, the source commit,
dataset version, chronological partitions, feature engine version, outcome
definition version, and transaction-cost policy in every manifest. The default
round-trip cost is 0.20%, but the rate and policy ID are configurable and persisted.

The primary population is `ALL_MARKET_OPPORTUNITIES`: every objectively tradable
onset reconstructed before future-event association, including onsets that never
became major moves. `LINKED_HINDSIGHT` is retained only as a labelled diagnostic
cohort. It is never substituted for the primary population.

The compatibility cohort `ALL_TRADABLE_ONSETS` refers to the same pre-association
onset records. Candidate, miss, rejection, and captured cohorts are annotations on
that frozen population.

## Processing Order

1. Validate frozen Candidate Research and SDE source manifests.
2. Reconstruct all point-in-time tradable onsets without future-event input.
3. Freeze population records and their evidence hashes.
4. Attach pre-registered 20, 60, and 120-session outcomes.
5. Build feature values from bars dated no later than each onset.
6. Fit percentile cutoffs on development only and freeze them.
7. Audit quality, leakage, missingness, univariate edge, conditional behavior,
   redundancy, bounded interactions, orthogonal value, chronological stability,
   and information decay.
8. Produce confidence tiers and the Top 20 Feature Cards.
9. Export immutable research artifacts and expose aggregate evidence to IRD.

## Outcomes

The pre-registered primary outcome is `TARGET_BEFORE_STOP`. Stop wins when stop and
target occur in the same bar. Secondary outcomes are
`POSITIVE_AFTER_COSTS_60D`, `ACHIEVED_2R`, and `HIGH_QUALITY_WINNER`.

Net returns, MFE, and MAE are evaluated independently at 20, 60, and 120 sessions.
Incomplete horizons remain missing. They are not converted into failures or wins.

Stop distance, target distance, and reward/risk are explicitly marked as coupled to
the primary outcome definition. They remain useful descriptive fields, but their
apparent target-before-stop attribution cannot be claimed as orthogonal evidence.

## Feature Evidence

The immutable registry covers price structure, trend persistence, volume and
turnover, volatility, base geometry, trade feasibility, relative strength, market
context, and canonical components. Raw OHLCV features are reconstructed in symbol
batches. Missing values remain missing.

Each feature receives separate evidence for:

- univariate and holdout strength;
- data quality and operational availability;
- conditional behavior and Simpson-reversal warnings;
- correlation, mutual information, and source-lineage overlap;
- bounded, interpretable interactions;
- incremental holdout AUC and Brier improvement;
- direction, support, era, regime, sector, and liquidity stability;
- information decay at 20, 60, and 120 sessions;
- negative or inverse association with successful trades.

Feature tiers are:

- Tier A: stable, orthogonal, and high quality;
- Tier B: stable but context dependent;
- Tier C: weak evidence;
- Tier D: inverse or failure-risk evidence;
- Tier E: research only, unstable, unavailable, or data blocked.

No tier is a production promotion decision.

## Known Data Limits

The legacy warehouse does not support authoritative full-history benchmark,
regime, breadth, sector membership, delivery percentage, spread, order-book,
ownership, earnings, or institutional-flow evidence. Relative-strength and market
context features are therefore blocked rather than reconstructed from current
mappings.

Regime and sector stability are explicitly unavailable until authoritative
point-in-time histories exist. Market-cap stability is also deferred because the
warehouse has no point-in-time shares-outstanding or free-float history. Canonical
component history is sparse and candidate-selected, so its attribution is labelled
accordingly and cannot represent every onset.

## Commands

```text
poetry run python -m alpha feature-attribution report
poetry run python -m alpha feature-attribution population
poetry run python -m alpha feature-attribution features
poetry run python -m alpha feature-attribution quality
poetry run python -m alpha feature-attribution leakage
poetry run python -m alpha feature-attribution univariate
poetry run python -m alpha feature-attribution conditional
poetry run python -m alpha feature-attribution redundancy
poetry run python -m alpha feature-attribution interactions
poetry run python -m alpha feature-attribution stability
poetry run python -m alpha feature-attribution missing-information
poetry run python -m alpha feature-attribution case-study --symbol KALYANKJIL
```

The report command accepts date, symbol, support, dataset-version, cost-policy,
JSON, CSV, and output controls. Artifact-reading commands provide feature, group,
outcome, and partition filters where applicable.

## Artifacts

The export directory contains the population, registry, Parquet snapshots, outcome
labels, quality and leakage audits, univariate and conditional attribution,
negative-feature audit, redundancy clusters, interaction results, chronological
stability, orthogonal probes, information decay, separate rankings, missing-data
audit, case studies, Top 20 Feature Cards, executive report, and manifest.

## Interpretation Rules

- Association is not causality.
- Development evidence alone cannot justify a conclusion.
- A strong univariate feature may be redundant.
- An inverse feature can be more useful as a disqualifier than another bullish
  feature.
- Missing or non-causal data fails closed.
- Legacy data is provisional.
- Human approval and a separate validated milestone are required before any
  production change.
